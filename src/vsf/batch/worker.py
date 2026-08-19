"""Chạy một lô POI tuần tự trên MỘT phiên browser.

Vì sao tuần tự: hai thread chat Gemini (`profile_chat_url`, `menu_chat_url`) là
URL CỐ ĐỊNH dùng chung cho mọi lượt. Hai POI chạy song song sẽ gửi prompt vào
cùng một cuộc hội thoại và đọc nhầm câu trả lời của nhau. Muốn song song thật thì
phải có mỗi worker một cặp chat riêng + một Chrome profile riêng — đó là việc
khác, không phải việc của module này.

Cái đạt được ở đây không phải thông lượng mà là **không phải ngồi canh**: nạp
danh sách, bấm chạy, sáng hôm sau xem kết quả và hàng đợi triage.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from ..browser import Session
from ..config import output_dir, set_output_dir, settings
from ..errors import TERMINAL_FLAGS
from ..pipeline import export_row, prepare_record, run_record
from . import store
from .outcome import derive_status

console = Console()

EventHook = Callable[[dict[str, Any]], None]


def _cfg() -> dict[str, Any]:
    batch = settings().get("batch", {})
    return {
        "max_attempts": int(batch.get("max_attempts", 2)),
        "delay_between": float(batch.get("delay_between", 3.0)),
    }


def run_batch(
    batch_id: int,
    *,
    resume: bool = True,
    limit: int | None = None,
    db_path: Path | None = None,
    on_event: EventHook | None = None,
) -> dict[str, int]:
    """Chạy hết các job đang chờ của một lô. Trả về thống kê kết cục.

    `resume=True` (mặc định) bỏ qua các bước đã `ok` của từng POI — chạy lại một
    lô dở dang không cào lại thứ đã có.
    """
    batch = store.get_batch(batch_id, db_path=db_path)
    if batch is None:
        raise ValueError(f"Không có lô id={batch_id}")

    cfg = _cfg()
    out = Path(batch["out_dir"])
    # `output_dir()` đọc một global toàn tiến trình; đặt một lần cho cả lô rồi
    # dùng đường dẫn tuyệt đối ở mọi nơi bên dưới.
    set_output_dir(str(out))
    out = output_dir()

    def emit(event: dict[str, Any]) -> None:
        store.add_event(
            event.get("kind", "log"),
            batch_id=batch_id,
            job_id=event.get("job_id"),
            step=event.get("step"),
            payload=event,
            db_path=db_path,
        )
        if on_event is not None:
            try:
                on_event(event)
            except Exception:  # pragma: no cover - chỉ là tầng hiển thị
                pass

    store.set_batch_status(batch_id, "running", db_path=db_path)
    emit({"kind": "batch_start", "batch_id": batch_id, "out_dir": str(out)})

    tally: dict[str, int] = {}
    processed = 0

    try:
        with Session() as s:
            while True:
                if limit is not None and processed >= limit:
                    break
                # Tạm dừng/huỷ là cờ HỢP TÁC, đọc giữa hai POI. Cắt giữa chừng
                # một lượt Gemini là vứt lượt đó đi mà chẳng cứu được gì.
                state = store.batch_status(batch_id, db_path=db_path)
                if state in ("paused", "cancelled"):
                    emit({"kind": "batch_stopped", "reason": state})
                    break

                job = store.claim_next(batch_id, db_path=db_path)
                if job is None:
                    break

                processed += 1
                status = _run_one(
                    s, job, out, resume=resume, cfg=cfg, db_path=db_path, emit=emit
                )
                tally[status] = tally.get(status, 0) + 1

                if cfg["delay_between"] > 0:
                    time.sleep(cfg["delay_between"])
    finally:
        # Lô đang chạy mà tiến trình chết thì trạng thái phải phản ánh sự thật,
        # không kẹt vĩnh viễn ở 'running'.
        final = store.batch_status(batch_id, db_path=db_path)
        if final == "running":
            remaining = store.list_jobs(batch_id, status="queued", db_path=db_path)
            store.set_batch_status(
                batch_id, "idle" if remaining else "done", db_path=db_path
            )
        emit({"kind": "batch_end", "tally": tally})

    return tally


def _run_one(
    s: Session,
    job: dict[str, Any],
    out: Path,
    *,
    resume: bool,
    cfg: dict[str, Any],
    db_path: Path | None,
    emit: EventHook,
) -> str:
    """Chạy đúng một POI và ghi kết cục vào hàng đợi."""
    poi = job["poi_name"]
    console.print(f"\n[bold]▶ #{job['seq']} {poi}[/] [dim](lần thử {job['attempts']})[/]")
    emit({"kind": "job_start", "job_id": job["id"], "seq": job["seq"], "poi": poi})

    record = prepare_record(
        out,
        poi,
        index=job["seq"],
        address=job["address_hint"] or None,
        place_id=job.get("place_id") or None,
        force_food=job["force_food"],
    )

    try:
        run_record(
            s,
            record,
            poi,
            out,
            only=job["only_step"],
            resume=resume,
            on_event=lambda e: emit({**e, "job_id": job["id"], "poi": poi}),
        )
    except Exception as exc:
        # `run_record` đã bắt lỗi của TỪNG bước; tới đây là lỗi ngoài vòng lặp
        # (mất kết nối CDP, Chrome bị đóng) — cả lô nên dừng, nhưng job này phải
        # được đánh dấu trước đã.
        store.finish_job(
            job["id"],
            status="failed",
            slug=record.slug,
            flags=record.all_flags(),
            steps=record.steps,
            error_code="session_error",
            error_message=str(exc),
            db_path=db_path,
        )
        emit({"kind": "job_failed", "job_id": job["id"], "poi": poi, "error": str(exc)})
        raise

    status, error_code, error_message = derive_status(record)

    # Lỗi tạm thời và còn lượt thử -> trả về hàng đợi thay vì chốt là hỏng.
    if status == "failed" and job["attempts"] < cfg["max_attempts"]:
        status = "queued"
        emit({"kind": "job_retry", "job_id": job["id"], "poi": poi, "attempt": job["attempts"]})
    elif status == "queued":
        # `derive_status` trả 'queued' khi còn bước chưa chạy — sau một lượt đầy
        # đủ thì đó là bước bị bỏ qua có chủ ý, coi như xong.
        status = "done"

    # Chỉ xuất row.tsv khi đã đi hết; POI còn nằm trong hàng đợi thì file TSV
    # nửa vời chỉ gây hiểu nhầm lúc gộp xuất.
    if status != "queued":
        try:
            export_row(record, out=out)
        except Exception as exc:
            emit({"kind": "export_failed", "job_id": job["id"], "error": str(exc)})

    store.finish_job(
        job["id"],
        status=status,
        slug=record.slug,
        flags=record.all_flags(),
        steps=record.steps,
        error_code=error_code,
        error_message=error_message,
        db_path=db_path,
    )
    blocked = [f for f in record.all_flags() if f in TERMINAL_FLAGS]
    emit(
        {
            "kind": "job_end",
            "job_id": job["id"],
            "poi": poi,
            "status": status,
            "flags": record.all_flags(),
            "blocked": blocked,
        }
    )
    mark = {"done": "[green]✓[/]", "needs_review": "[yellow]⚑[/]"}.get(status, "[red]✗[/]")
    console.print(f"  {mark} {status}" + (f" — {error_message}" if error_message else ""))
    return status
