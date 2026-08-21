"""Các endpoint JSON cho giao diện quản lý."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import queue
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..batch import export as batch_export
from ..batch import ingest, reindex, store
from ..batch.outcome import missing_steps
from ..config import PROJECT_ROOT, output_dir, set_output_dir, settings
from ..errors import FLAG_LABELS, flag_label, flag_severity, flags_from_warnings
from ..models import POIRecord
from ..pipeline import all_steps, export_row
from ..profiles import DEFAULT as DEFAULT_PROFILE
from ..profiles import PROFILES, get_profile, profile_for
from ..schema import build_row
from .runner import RUNNER

router = APIRouter(prefix="/api")


# -- Mô hình đầu vào --------------------------------------------------------


class BatchCreate(BaseModel):
    out_dir: str = Field(..., description="Thư mục kết quả, vd output_19_8")
    name: str = ""
    text: str = Field("", description="Danh sách POI: CSV có tiêu đề, hoặc mỗi dòng một tên")
    profile: str = Field(DEFAULT_PROFILE, description="Bộ dataset: food | accom")


class StartRequest(BaseModel):
    resume: bool = True
    limit: int | None = None


class RerunRequest(BaseModel):
    only: str | None = None
    address: str | None = None
    force_food: bool = False


class RowPatch(BaseModel):
    # `null` = XOÁ override của cột đó, khác hẳn `""` = ép cột đó rỗng. Thiếu
    # phân biệt này thì nút "về mặc định" của một cột (vd tick lại 3 ảnh gallery)
    # chỉ ghi được chuỗi rỗng, tức là khoá cột lại ở giá trị trống vĩnh viễn chứ
    # không trả nó về cho pipeline tính.
    overrides: dict[str, str | None]


class TikTokPick(BaseModel):
    index: int


# -- Tiện ích ---------------------------------------------------------------


def _batch_or_404(batch_id: int) -> dict[str, Any]:
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(404, f"Không có lô #{batch_id}")
    return batch


def _job_or_404(job_id: int) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Không có job #{job_id}")
    return job


def _out_path(batch: dict[str, Any]) -> Path:
    path = Path(batch["out_dir"])
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_record(job: dict[str, Any], batch: dict[str, Any]) -> POIRecord:
    out = _out_path(batch)
    record = POIRecord.load_or_new(out, job["poi_name"], index=job["seq"] or None)
    # Cùng một phép bắc cầu mà reindex dùng. Thiếu chỗ này thì bản ghi cũ hiện
    # đầy cờ ở bảng danh sách (đọc từ DB) nhưng trắng trơn ở trang chi tiết (đọc
    # từ đĩa) — cùng một POI, hai câu trả lời khác nhau.
    if not record.flags and record.warnings:
        record.flags = flags_from_warnings(record.warnings)
    return record


def _row_for(record: POIRecord, tiktok_index: int = 0) -> dict[str, str]:
    cfg = profile_for(record).settings()
    return build_row(
        record,
        cfg["dataset"],
        tiktok_index=tiktok_index,
        ward_map=cfg.get("ward_map", {}),
    )


# -- Lô ---------------------------------------------------------------------


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    return {"batches": store.list_batches(), "running": RUNNER.running_batch}


@router.post("/batches")
def create_batch(payload: BatchCreate) -> dict[str, Any]:
    pois = ingest.parse(payload.text)
    if not pois:
        raise HTTPException(400, "Không đọc được POI nào từ danh sách.")
    if payload.profile not in PROFILES:
        raise HTTPException(400, f"Profile phải là một trong: {', '.join(PROFILES)}")

    store.init()
    batch_id = store.get_or_create_batch(
        payload.out_dir, payload.name or payload.out_dir, profile=payload.profile
    )
    for poi in pois:
        store.upsert_job(
            batch_id,
            poi.name,
            seq=poi.seq,
            address_hint=poi.address,
            place_id=poi.place_id,
            force_food=poi.force_food,
            only_step=poi.only_step,
            profile=poi.profile or payload.profile,
        )
    return {
        "batch_id": batch_id,
        "added": len(pois),
        "profile": payload.profile,
        "with_place_id": sum(1 for p in pois if p.place_id),
        "with_address": sum(1 for p in pois if p.address),
    }


@router.post("/batches/{batch_id}/start")
def start_batch(batch_id: int, payload: StartRequest | None = None) -> dict[str, Any]:
    _batch_or_404(batch_id)
    payload = payload or StartRequest()
    try:
        RUNNER.start(batch_id, resume=payload.resume, limit=payload.limit)
    except RuntimeError as exc:
        # 409: yêu cầu hợp lệ nhưng xung đột với trạng thái hiện tại.
        raise HTTPException(409, str(exc)) from None
    return {"ok": True, "batch_id": batch_id}


@router.post("/batches/{batch_id}/pause")
def pause_batch(batch_id: int) -> dict[str, Any]:
    _batch_or_404(batch_id)
    RUNNER.pause(batch_id)
    return {"ok": True, "note": "Sẽ dừng sau khi POI đang chạy kết thúc."}


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: int) -> dict[str, Any]:
    _batch_or_404(batch_id)
    RUNNER.cancel(batch_id)
    return {"ok": True, "note": "Sẽ dừng sau khi POI đang chạy kết thúc."}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int) -> dict[str, Any]:
    """Bỏ lô khỏi chỉ mục. KHÔNG xoá file nào trên đĩa."""
    _batch_or_404(batch_id)
    if RUNNER.running_batch == batch_id:
        raise HTTPException(409, "Lô đang chạy. Tạm dừng trước khi xoá.")
    removed = store.delete_batch(batch_id)
    return {
        "ok": True,
        "removed_jobs": removed,
        "note": "Chỉ xoá khỏi chỉ mục — data.json và row.tsv vẫn còn trên đĩa.",
    }


@router.post("/batches/{batch_id}/retry")
def retry_batch(batch_id: int, everything: bool = False) -> dict[str, Any]:
    _batch_or_404(batch_id)
    return {"requeued": store.reset_jobs(batch_id, only_failed=not everything)}


@router.get("/batches/{batch_id}/jobs")
def list_jobs(
    batch_id: int,
    status: str | None = None,
    flag: str | None = None,
) -> dict[str, Any]:
    _batch_or_404(batch_id)
    return {"jobs": store.list_jobs(batch_id, status=status, flag=flag)}


@router.post("/reindex")
def do_reindex(dir: str | None = None) -> dict[str, Any]:
    results = [reindex.reindex_dir(dir)] if dir else reindex.reindex_all()
    return {"results": results, "total": sum(r["total"] for r in results)}


# -- Job --------------------------------------------------------------------


@router.get("/jobs")
def list_all_jobs(
    status: str | None = None,
    flag: str | None = None,
    severity: str | None = Query(None, description="block | warn"),
) -> dict[str, Any]:
    """Mọi job trên mọi lô — nguồn cho màn hình triage."""
    jobs = store.list_jobs(None, status=status, flag=flag)
    if severity:
        jobs = [j for j in jobs if any(flag_severity(f) == severity for f in j["flags"])]
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, tiktok: int = 0) -> dict[str, Any]:
    job = _job_or_404(job_id)
    batch = _batch_or_404(job["batch_id"])
    record = _load_record(job, batch)
    profile = profile_for(record)
    return {
        "job": job,
        "batch": batch,
        "record": {
            "poi_name": record.poi_name,
            "profile": profile.name,
            "slug": record.slug,
            "address_hint": record.address_hint,
            "place_id_hint": getattr(record, "place_id_hint", ""),
            "category_l1": record.category_l1,
            "category_l2": record.category_l2,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "steps": record.steps,
            "step_runs": record.step_runs,
            "warnings": record.warnings,
            "flags": record.all_flags(),
            "overrides": record.overrides,
            "missing_steps": missing_steps(record),
            "google_maps": record.google_maps,
            "gemini_profile": record.gemini_profile,
            "menu": record.menu,
            "rooms": getattr(record, "rooms", {}),
            "tiktok": record.tiktok,
            "facebook": record.facebook,
        },
        "row": _row_for(record, tiktok_index=tiktok),
        # Cột và bước LUÔN theo profile của bản ghi — giao diện không có danh
        # sách nào của riêng nó, đây là nguồn sự thật duy nhất.
        "profile": profile.name,
        "columns": profile.COLUMNS,
        "steps": profile.STEPS,
    }


@router.patch("/jobs/{job_id}/row")
def patch_row(job_id: int, payload: RowPatch) -> dict[str, Any]:
    """Ghi phần sửa tay vào data.json rồi xuất lại row.tsv.

    Sửa nằm ở `overrides` chứ không ghi đè dữ liệu gốc: chạy lại một bước sau này
    sẽ làm mới dữ liệu Google/Gemini mà KHÔNG xoá chỗ người dùng đã sửa.

    Giá trị `null` cho một cột nghĩa là BỎ phần sửa tay của cột đó, trả nó về giá
    trị pipeline tự tính.
    """
    job = _job_or_404(job_id)
    batch = _batch_or_404(job["batch_id"])
    out = _out_path(batch)
    record = _load_record(job, batch)

    columns = profile_for(record).COLUMNS
    unknown = sorted(set(payload.overrides) - set(columns))
    if unknown:
        raise HTTPException(400, f"Không phải cột của dataset: {', '.join(unknown)}")

    for col, value in payload.overrides.items():
        if value is None:
            record.overrides.pop(col, None)
        else:
            record.overrides[col] = value
    record.save(out)
    path = export_row(record, out=out)
    return {"ok": True, "overrides": record.overrides, "row_path": str(path)}


@router.delete("/jobs/{job_id}/row")
def clear_overrides(job_id: int) -> dict[str, Any]:
    job = _job_or_404(job_id)
    batch = _batch_or_404(job["batch_id"])
    out = _out_path(batch)
    record = _load_record(job, batch)
    record.overrides = {}
    record.save(out)
    export_row(record, out=out)
    return {"ok": True}


@router.post("/jobs/{job_id}/tiktok")
def pick_tiktok(job_id: int, payload: TikTokPick) -> dict[str, Any]:
    """Chọn tay ứng viên TikTok — tương đương `vsf export --tiktok N`."""
    job = _job_or_404(job_id)
    batch = _batch_or_404(job["batch_id"])
    out = _out_path(batch)
    record = _load_record(job, batch)
    if not 0 <= payload.index < len(record.tiktok):
        raise HTTPException(400, f"Chỉ có {len(record.tiktok)} ứng viên TikTok.")

    picked = record.tiktok[payload.index]
    # Ghi vào overrides chứ không xáo lại thứ tự danh sách ứng viên: điểm số và
    # score_breakdown phải giữ nguyên để sau này còn biết vì sao máy chọn khác.
    record.overrides["raw_url"] = picked.get("url", "")
    record.overrides["video_posted_date"] = (picked.get("posted_at") or "")[:10]
    record.save(out)
    path = export_row(record, tiktok_index=payload.index, out=out)
    return {"ok": True, "picked": picked, "row_path": str(path)}


@router.post("/jobs/{job_id}/rerun")
def rerun_job(job_id: int, payload: RerunRequest) -> dict[str, Any]:
    """Đưa một job về hàng đợi, tuỳ chọn chỉ chạy lại đúng một bước."""
    job = _job_or_404(job_id)
    # Xét theo bước của ĐÚNG profile job này: `--only menu` trên một job lưu trú
    # là lệnh vô nghĩa và phải bị chặn ngay, chứ không để worker chạy một bước
    # không có trong chuỗi rồi ghi "ok".
    steps = get_profile(job.get("profile") or DEFAULT_PROFILE).STEPS
    if payload.only and payload.only not in steps:
        raise HTTPException(400, f"--only phải là một trong: {', '.join(steps)}")

    store.upsert_job(
        job["batch_id"],
        job["poi_name"],
        seq=job["seq"],
        address_hint=payload.address if payload.address is not None else job["address_hint"],
        force_food=payload.force_food,
        only_step=payload.only,
        status="queued",
        attempts=0,
        error_code=None,
        error_message=None,
    )
    return {"ok": True, "note": "Đã xếp lại hàng đợi. Bấm Chạy để worker xử lý."}


# -- Thống kê ---------------------------------------------------------------


@router.get("/stats")
def stats() -> dict[str, Any]:
    """Số liệu cho trang tổng quan.

    Tỉ lệ ok theo bước là tín hiệu phát hiện selector hỏng: một bước tụt dốc đột
    ngột so với các bước khác nghĩa là Google/TikTok vừa đổi giao diện.
    """
    jobs = store.list_jobs(None)
    by_status = Counter(j["status"] for j in jobs)
    flags = Counter(f for j in jobs for f in j["flags"])

    step_stats: dict[str, dict[str, int]] = {}
    for step in all_steps():
        counter = Counter(j["steps"].get(step, "missing") for j in jobs)
        step_stats[step] = dict(counter)

    # Tỉ lệ ô trống theo cột: cột nào hay trống thì hoặc nguồn không có, hoặc
    # bước cào nó đang hỏng. Đọc từ row.tsv đã ghi, không dựng lại toàn bộ.
    #
    # Đếm THEO TỪNG PROFILE. Gộp chung thì `menu` (chỉ có ở food) trông như trống
    # 100% ở mọi POI lưu trú, và `room_price` trống ở mọi quán ăn — hai con số vô
    # nghĩa lại đứng đầu bảng "cột hay trống nhất".
    blanks: dict[str, Counter] = {}
    rows_seen: Counter = Counter()
    # Profile nào ĐANG có lô, kể cả lô chưa xuất dòng nào. Chỉ liệt kê profile
    # đã đọc được row.tsv thì bảng "cột hay trống" biến mất sạch lúc đợt mới
    # chưa chạy xong POI đầu tiên — đúng lúc người dùng nhìn vào nhiều nhất.
    profiles_seen: set[str] = set()
    for batch in store.list_batches():
        batch_profile = batch.get("profile") or DEFAULT_PROFILE
        if batch_profile not in PROFILES:
            batch_profile = DEFAULT_PROFILE
        profiles_seen.add(batch_profile)
        out = _out_path(batch)
        if not out.is_dir():
            continue
        for folder in out.iterdir():
            tsv = folder / "row.tsv"
            if not tsv.is_file():
                continue
            try:
                with tsv.open(encoding="utf-8") as fh:
                    row = next(csv.DictReader(fh, delimiter="\t"), None)
            except OSError:
                continue
            if row is None:
                continue
            rows_seen[batch_profile] += 1
            counter = blanks.setdefault(batch_profile, Counter())
            for col in get_profile(batch_profile).COLUMNS:
                if not (row.get(col) or "").strip():
                    counter[col] += 1

    listed = sorted(profiles_seen) or [DEFAULT_PROFILE]
    return {
        "total": len(jobs),
        "by_status": dict(by_status),
        "flags": [
            {
                "code": code,
                "label": flag_label(code),
                "severity": flag_severity(code),
                "count": n,
            }
            for code, n in flags.most_common()
        ],
        "known_flags": [
            {"code": c, "label": lbl, "severity": sev} for c, (lbl, sev) in FLAG_LABELS.items()
        ],
        "steps": step_stats,
        "rows_seen": sum(rows_seen.values()),
        "rows_seen_by_profile": {name: rows_seen[name] for name in listed},
        "blank_by_column": [
            {
                "profile": name,
                "column": c,
                "blank": blanks.get(name, Counter()).get(c, 0),
                "total": rows_seen[name],
            }
            for name in listed
            for c in get_profile(name).COLUMNS
        ],
    }


@router.get("/export/{batch_id}.tsv")
def export_batch(batch_id: int) -> PlainTextResponse:
    batch = _batch_or_404(batch_id)
    out = _out_path(batch)
    if not out.is_dir():
        raise HTTPException(404, f"Không thấy thư mục {out}")

    try:
        rows, _, profile_name = batch_export.collect(out)
    except ValueError as exc:  # thư mục trộn hai profile
        raise HTTPException(409, str(exc)) from None
    if not rows:
        raise HTTPException(404, "Chưa có row.tsv nào trong đợt này.")

    columns = get_profile(profile_name).COLUMNS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in columns})

    name = Path(batch["out_dir"]).name or f"batch_{batch_id}"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/tab-separated-values; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tong_hop_{name}.tsv"'},
    )


# -- Môi trường -------------------------------------------------------------


@router.get("/doctor")
def doctor() -> dict[str, Any]:
    """Chạy bộ kiểm tra môi trường. Chậm (mở Chrome, điều hướng 4 trang)."""
    from .. import health

    try:
        checks = health.check_all()
    except Exception as exc:
        raise HTTPException(503, f"Không kiểm tra được môi trường: {exc}") from None
    return {
        "checks": [c.as_dict() for c in checks],
        "healthy": health.healthy(checks),
        "degraded": health.degraded(checks),
    }


@router.get("/config")
def get_config() -> dict[str, Any]:
    """Các ngưỡng/tham số đang có hiệu lực — để giao diện giải thích quyết định.

    `profiles` là bảng tra theo tên: cột, bước, nhãn l2 và giá trị mặc định của
    TỪNG bộ dataset. Giao diện tra theo profile của job đang xem chứ không giữ
    danh sách riêng — chép cứng ở phía client là cách chắc chắn nhất để hai bên
    trôi lệch nhau.
    """
    cfg = settings()
    return {
        "default_profile": DEFAULT_PROFILE,
        "profiles": {
            name: {
                "columns": p.COLUMNS,
                "steps": p.STEPS,
                "category_l1": p.category_l1,
                "l2_values": p.settings()["category"].get("l2_values", []),
                "dataset": p.settings()["dataset"],
            }
            for name, p in PROFILES.items()
        },
        "output_dir": str(output_dir()),
        "tiktok": cfg.get("tiktok", {}),
        "gmaps": {k: v for k, v in cfg.get("gmaps", {}).items() if isinstance(v, (int, float))},
        "batch": cfg.get("batch", {}),
    }


# -- Sự kiện trực tiếp ------------------------------------------------------


@router.get("/events")
async def events() -> StreamingResponse:
    """Luồng SSE các sự kiện của worker.

    Dùng SSE chứ không WebSocket: luồng ở đây một chiều (server -> trình duyệt),
    và `EventSource` tự kết nối lại khi đứt mà không cần viết thêm dòng nào.
    """
    q = RUNNER.broker.subscribe()

    async def stream():
        loop = asyncio.get_running_loop()
        try:
            yield ": đã kết nối\n\n"
            while True:
                try:
                    # Chờ trong executor: hàng đợi là của thread, không phải asyncio.
                    event = await loop.run_in_executor(None, q.get, True, 20)
                except queue.Empty:
                    # Nhịp giữ kết nối: proxy hay đóng luồng im lặng quá lâu.
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        finally:
            RUNNER.broker.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events/history")
def event_history(
    batch_id: int | None = None, job_id: int | None = None, after_id: int = 0, limit: int = 200
) -> dict[str, Any]:
    """Sự kiện đã ghi — để mở giao diện giữa chừng vẫn thấy lịch sử."""
    return {
        "events": store.list_events(
            batch_id=batch_id, job_id=job_id, after_id=after_id, limit=limit
        )
    }
