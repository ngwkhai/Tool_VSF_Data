"""CLI của tool."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import browser, pipeline
from .config import settings

app = typer.Typer(add_completion=False, help="Tool gán nhãn & tăng cường dữ liệu POI")
batch_app = typer.Typer(add_completion=False, help="Chạy theo lô: nạp danh sách, chạy, theo dõi")
app.add_typer(batch_app, name="batch")
console = Console()


@app.command()
def run(
    poi: str = typer.Argument(..., help="Tên POI, ví dụ: 'Bánh Canh Trần Văn Ơn'"),
    only: str = typer.Option(
        None, "--only", help=f"Chỉ chạy một bước: {' | '.join(pipeline.all_steps())}"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Bỏ qua các bước đã chạy thành công lần trước"
    ),
    index: int = typer.Option(
        None, "--index", help="Đánh số thư mục kết quả: output/<số>_<slug>/"
    ),
    out: str = typer.Option(
        None, "--out", help="Thư mục kết quả khác thay cho output/ (vd: output_12/8)"
    ),
    address: str = typer.Option(
        None,
        "--address",
        help=(
            "Địa chỉ mẫu để phân biệt quán trùng tên (vd: '223 Nguyễn Thiện Thuật'). "
            "Dùng để neo truy vấn Google Maps và chặn lại nếu Google trả về đúng "
            "quán khác. Lưu trong data.json nên chỉ cần truyền lần đầu."
        ),
    ),
    force_food: bool = typer.Option(
        False,
        # Hai tên cho CÙNG một cờ: `--force-food` là tên cũ, giữ lại để lệnh đã
        # ghi trong ghi chú/script cũ vẫn chạy; `--force-category` là tên đúng
        # từ khi có profile lưu trú.
        "--force-category",
        "--force-food",
        help=(
            "Bỏ qua cổng phân loại nhóm ngành. Dùng khi nhãn ngành của Google gây "
            "hiểu nhầm (vd quán ăn trong khách sạn bị xếp ngành 'Khách sạn', hay "
            "homestay bị xếp ngành 'Công ty du lịch'). Chỉ có hiệu lực cho lần "
            "chạy này, không ghi vào data.json."
        ),
    ),
    profile: str = typer.Option(
        "food",
        "--profile",
        help="Bộ dataset: food (POI đồ ăn, 73 cột) | accom (POI lưu trú, 72 cột)",
    ),
) -> None:
    """Thu thập dữ liệu cho một POI và ghi ra output/<slug>/data.json."""
    from .config import set_output_dir
    from .profiles import PROFILES

    set_output_dir(out)

    if profile not in PROFILES:
        console.print(f"[red]--profile phải là một trong: {', '.join(PROFILES)}[/]")
        raise typer.Exit(2)

    steps = PROFILES[profile].STEPS
    if only and only not in steps:
        console.print(
            f"[red]--only phải là một trong: {', '.join(steps)} (profile {profile})[/]"
        )
        raise typer.Exit(2)

    record = pipeline.run(
        poi,
        only=only,
        resume=resume,
        index=index,
        address=address,
        force_food=force_food,
        profile=profile,
    )

    table = Table(title=f"Kết quả: {poi}")
    table.add_column("Bước")
    table.add_column("Trạng thái")
    for step in steps:
        status = record.steps.get(step, "chưa chạy")
        mark = {"ok": "[green]✓ ok[/]", "failed": "[red]✗ lỗi[/]"}.get(status, f"[dim]{status}[/]")
        table.add_row(step, mark)
    console.print(table)

    for warning in record.all_warnings():
        # escape(): tên bước nằm trong ngoặc vuông, rich sẽ hiểu nhầm là thẻ
        # markup và nuốt mất nếu không thoát.
        console.print("[yellow]![/] " + escape(warning))

    if any(record.steps.get(s) == "failed" for s in steps):
        raise typer.Exit(1)


@app.command()
def export(
    poi: str = typer.Argument(..., help="Tên POI đã chạy trước đó"),
    tiktok: int = typer.Option(
        0, "--tiktok", help="Chọn ứng viên TikTok thứ mấy (0 = khớp nhất)"
    ),
    out_dir: str = typer.Option(
        None, "--out", help="Thư mục kết quả khác thay cho output/ (vd: output_12/8)"
    ),
) -> None:
    """Xuất lại row.tsv từ data.json đã có, cho phép đổi link TikTok đã chọn."""
    from .config import output_dir, set_output_dir
    from .models import POIRecord

    set_output_dir(out_dir)
    out = output_dir()
    if not POIRecord.path_for(out, poi).exists():
        console.print(f"[red]Chưa có dữ liệu cho {poi!r}. Chạy `vsf run` trước.[/]")
        raise typer.Exit(1)

    record = POIRecord.load_or_new(out, poi)
    if record.tiktok:
        table = Table(title="Ứng viên TikTok")
        table.add_column("#")
        table.add_column("Điểm")
        table.add_column("Vì sao")
        table.add_column("Tài khoản")
        table.add_column("Caption", max_width=44)
        table.add_column("Ngày")
        for i, c in enumerate(record.tiktok):
            marker = "[green]→[/]" if i == tiktok else " "
            breakdown = c.get("score_breakdown") or {}
            why = ",".join(f"{k[:3]}{v}" for k, v in breakdown.items() if v)
            table.add_row(
                f"{marker}{i}",
                str(c.get("score", c.get("match_score", ""))),
                why,
                str(c.get("author") or ""),
                (c.get("caption") or "").replace("\n", " ")[:120],
                (c.get("posted_at") or "")[:10],
            )
        console.print(table)
        for i, c in enumerate(record.tiktok):
            console.print(f"[dim]{i}: {c['url']}[/]")

    console.print(f"Đã ghi [bold]{pipeline.export_row(record, tiktok_index=tiktok)}[/]")


@app.command()
def photos(
    poi: str = typer.Argument(
        None, help="Tên POI. Bỏ trống = quét cả thư mục kết quả."
    ),
    out_dir: str = typer.Option(
        None, "--out", help="Thư mục kết quả (vd: output_18_8). Mặc định: output/"
    ),
    missing_only: bool = typer.Option(
        True,
        "--missing-only/--all",
        help="Chỉ vá bản ghi thiếu ảnh đại diện hoặc chưa có bể 10 ảnh gallery",
    ),
    limit: int = typer.Option(None, "--limit", help="Dừng sau N bản ghi"),
) -> None:
    """Cào lại RIÊNG ảnh đại diện + 10 ảnh gallery, không chạy lại bước nào khác.

    Dùng để vá các bản ghi cũ mất `raw_cover_image_url` mà không phải đốt lại
    toàn bộ bước `maps` (giờ mở cửa, 10 bài đánh giá, ảnh thực đơn).
    """
    from .browser import Session
    from .config import output_dir, set_output_dir
    from .models import POIRecord

    set_output_dir(out_dir)
    out = output_dir()

    if poi:
        if not POIRecord.path_for(out, poi).exists():
            console.print(f"[red]Chưa có dữ liệu cho {poi!r}.[/]")
            raise typer.Exit(1)
        folders = [POIRecord.path_for(out, poi).parent]
    else:
        folders = sorted(p.parent for p in out.glob("*/data.json"))

    todo = []
    for folder in folders:
        record = POIRecord.load_folder(folder)
        maps = record.google_maps or {}
        # Dòng stub (POI sai nhóm ngành) không có cột ảnh nào để vá — bỏ qua,
        # đừng đốt một lượt mở trang chỉ để ghi lại đúng dòng stub cũ.
        # So với nhóm ngành CỦA PROFILE bản ghi: so cứng với "FOOD" thì mọi POI
        # lưu trú (category_l1 = "ACCOM") bị bỏ qua sạch trong im lặng.
        from .profiles import profile_for

        if record.category_l1 and record.category_l1 != profile_for(record).category_l1:
            continue
        needs = not (maps.get("photos") or {}).get("hero") or not (
            (maps.get("gallery_candidates") or {}).get("images")
        )
        if missing_only and not needs:
            continue
        todo.append(record)

    if limit:
        todo = todo[:limit]
    if not todo:
        console.print("[green]Không có bản ghi nào cần vá ảnh.[/]")
        return

    console.print(f"Sẽ vá ảnh cho [bold]{len(todo)}[/] bản ghi trong {out}\n")
    table = Table()
    table.add_column("POI")
    table.add_column("Đại diện")
    table.add_column("Ứng viên")

    with Session() as s:
        for record in todo:
            try:
                info = pipeline.refresh_photos(s, record, out)
            except Exception as exc:  # một POI hỏng không được chặn cả loạt
                table.add_row(record.slug, f"[red]lỗi[/] {escape(str(exc)[:60])}", "-")
                continue
            mark = (
                "[green]✓[/]"
                if info["hero_after"] and not info["hero_before"]
                else "[green]ok[/]"
                if info["hero_after"]
                else "[red]vẫn trống[/]"
            )
            table.add_row(record.slug, mark, str(info["candidates"]))

    console.print(table)


@app.command()
def login() -> None:
    """Mở Chrome (profile riêng của tool) để bạn đăng nhập Google + TikTok + Facebook."""
    port = settings()["browser"]["cdp_port"]
    if browser.is_chrome_running(port):
        console.print(f"[green]Chrome của tool đã chạy sẵn[/] trên cổng {port}.")
    else:
        browser.launch_chrome(port)
        console.print("[green]Đã mở Chrome[/] với profile riêng của tool.")

    with browser.Session() as s:
        # Mở MỌI thread Gemini đang khai báo, không chỉ chat #1 của profile mặc
        # định: mỗi profile có thể có cặp thread riêng, và thread nào chưa từng
        # mở trong profile Chrome này thì lần chạy thật mới phát hiện là hỏng.
        for slot, url in browser.gemini_slots().items():
            s.goto(slot, url)
        s.goto("tiktok", "https://www.tiktok.com/")
        s.goto("facebook", "https://www.facebook.com/")

    console.print(
        "\nHãy đăng nhập [bold]Google[/], [bold]TikTok[/] và [bold]Facebook[/] trong "
        "cửa sổ vừa mở, rồi chạy [bold]vsf doctor[/] để kiểm tra."
    )
    console.print(
        "[dim]Facebook chỉ dùng để XÁC MINH quán qua địa chỉ Trang; chưa đăng nhập "
        "thì bước đó tự bỏ qua, phần còn lại vẫn chạy.[/]"
    )


@app.command()
def doctor() -> None:
    """Kiểm tra môi trường: profile, đăng nhập, mọi chat Gemini có truy cập được không."""
    from . import health

    checks = health.check_all()

    table = Table(title="vsf doctor")
    table.add_column("Kiểm tra")
    table.add_column("Kết quả")
    table.add_column("Chi tiết")
    for c in checks:
        # Cờ riêng chứ KHÔNG nhúng "[tuỳ chọn]" vào nhãn: Rich hiểu ngoặc vuông
        # là thẻ markup và nuốt mất tiền tố.
        mark = "[green]✓[/]" if c.ok else ("[yellow]—[/]" if c.optional else "[red]✗[/]")
        table.add_row(f"{c.label} (tuỳ chọn)" if c.optional else c.label, mark, c.detail)
    console.print(table)

    # Mục tuỳ chọn hỏng KHÔNG phải lỗi môi trường: pipeline vẫn chạy đủ, chỉ mất
    # phần tăng cường. Tính chúng vào điều kiện thoát là báo động giả.
    if missing := health.degraded(checks):
        console.print(
            "[yellow]Chạy được, nhưng thiếu phần tăng cường:[/] "
            + ", ".join(missing)
            + "\n[dim]Đăng nhập bằng `vsf login` để bật lại.[/]"
        )
    if not health.healthy(checks):
        raise typer.Exit(1)


# -- Chế độ lô ---------------------------------------------------------------


def _resolve_batch(batch: int | None, out: str | None) -> int:
    """Xác định lô cần thao tác từ `--batch` hoặc `--out`, báo lỗi rõ nếu mơ hồ."""
    from .batch import store

    store.init()
    if batch is not None:
        if store.get_batch(batch) is None:
            console.print(f"[red]Không có lô id={batch}. Xem `vsf batch status`.[/]")
            raise typer.Exit(2)
        return batch
    if out:
        return store.get_or_create_batch(out, out)

    batches = store.list_batches()
    if not batches:
        console.print("[red]Chưa có lô nào. Tạo bằng `vsf batch add <file>`.[/]")
        raise typer.Exit(2)
    if len(batches) > 1:
        console.print(
            "[red]Có nhiều lô — chỉ rõ bằng --batch <id> hoặc --out <thư mục>.[/]\n"
            "[dim]Xem danh sách: vsf batch status[/]"
        )
        raise typer.Exit(2)
    return int(batches[0]["id"])


@batch_app.command("add")
def batch_add(
    source: str = typer.Argument(..., help="File danh sách POI (.csv/.tsv/.txt)"),
    out: str = typer.Option(..., "--out", help="Thư mục kết quả của đợt, vd output_19_8"),
    name: str = typer.Option("", "--name", help="Tên đợt hiển thị trong giao diện"),
    profile: str = typer.Option(
        "food",
        "--profile",
        help="Bộ dataset của cả đợt: food (73 cột) | accom (72 cột)",
    ),
) -> None:
    """Nạp danh sách POI vào hàng đợi của một đợt."""
    from .batch import ingest, store
    from .profiles import PROFILES

    if profile not in PROFILES:
        console.print(f"[red]--profile phải là một trong: {', '.join(PROFILES)}[/]")
        raise typer.Exit(2)

    path = Path(source)
    if not path.is_file():
        console.print(f"[red]Không thấy file {source}[/]")
        raise typer.Exit(2)

    pois = ingest.parse_file(path)
    if not pois:
        console.print("[red]Không đọc được POI nào từ file.[/]")
        raise typer.Exit(1)

    store.init()
    batch_id = store.get_or_create_batch(out, name or out, profile=profile)
    for poi in pois:
        store.upsert_job(
            batch_id,
            poi.name,
            seq=poi.seq,
            address_hint=poi.address,
            place_id=poi.place_id,
            force_food=poi.force_food,
            only_step=poi.only_step,
            # Dòng nào khai profile riêng thì thắng; còn lại theo cả đợt.
            profile=poi.profile or profile,
        )

    console.print(
        f"[green]Đã nạp {len(pois)} POI[/] ({profile}) vào lô [bold]#{batch_id}[/] ({out}).\n"
        f"[dim]Chạy: vsf batch run --batch {batch_id}[/]"
    )


@batch_app.command("run")
def batch_run(
    batch: int = typer.Option(None, "--batch", help="Id lô (bỏ trống nếu chỉ có một lô)"),
    out: str = typer.Option(None, "--out", help="Chọn lô theo thư mục kết quả"),
    limit: int = typer.Option(None, "--limit", help="Chỉ chạy tối đa N POI rồi dừng"),
    fresh: bool = typer.Option(
        False, "--fresh", help="Chạy lại cả các bước đã ok (mặc định là bỏ qua)"
    ),
) -> None:
    """Chạy hết các POI đang chờ trong lô, tuần tự trên một phiên Chrome."""
    from .batch import store, worker

    batch_id = _resolve_batch(batch, out)
    # Huỷ/tạm dừng của lần trước còn treo thì `run` phải gỡ, nếu không worker
    # thấy cờ dừng ngay vòng lặp đầu tiên rồi thoát trong im lặng.
    if store.batch_status(batch_id) in ("paused", "cancelled"):
        store.set_batch_status(batch_id, "idle")

    tally = worker.run_batch(batch_id, resume=not fresh, limit=limit)
    if not tally:
        console.print("[yellow]Không có POI nào đang chờ.[/]")
        return

    console.print("\n[bold]Kết cục:[/] " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    if tally.get("failed") or tally.get("needs_review"):
        raise typer.Exit(1)


@batch_app.command("status")
def batch_status(
    batch: int = typer.Option(None, "--batch", help="Id lô; bỏ trống để xem tất cả"),
    flag: str = typer.Option(None, "--flag", help="Chỉ hiện POI mang cờ này"),
    status: str = typer.Option(None, "--status", help="Lọc theo trạng thái job"),
) -> None:
    """Xem tiến độ các lô, hoặc chi tiết job của một lô."""
    from .batch import store
    from .errors import flag_label

    store.init()
    if batch is None and not flag and not status:
        batches = store.list_batches()
        if not batches:
            console.print("[dim]Chưa có lô nào. `vsf batch reindex` để nạp dữ liệu đã có.[/]")
            return
        table = Table(title="Các đợt gán nhãn")
        table.add_column("#")
        table.add_column("Tên")
        table.add_column("Thư mục")
        table.add_column("Tổng", justify="right")
        table.add_column("Chi tiết")
        for b in batches:
            detail = "  ".join(f"{k}={v}" for k, v in sorted(b["counts"].items()))
            table.add_row(str(b["id"]), b["name"], b["out_dir"], str(b["total"]), detail)
        console.print(table)
        return

    jobs = store.list_jobs(batch, status=status, flag=flag)
    if not jobs:
        console.print("[dim]Không có job nào khớp.[/]")
        return

    table = Table(title=f"Job ({len(jobs)})")
    table.add_column("#", justify="right")
    table.add_column("STT", justify="right")
    table.add_column("POI", max_width=38)
    table.add_column("Trạng thái")
    table.add_column("Cờ", max_width=46)
    marks = {
        "done": "[green]done[/]",
        "failed": "[red]failed[/]",
        "needs_review": "[yellow]needs_review[/]",
        "running": "[cyan]running[/]",
    }
    for j in jobs:
        labels = ", ".join(flag_label(f) for f in j["flags"])
        table.add_row(
            str(j["id"]),
            str(j["seq"]),
            escape(j["poi_name"]),
            marks.get(j["status"], f"[dim]{j['status']}[/]"),
            escape(labels),
        )
    console.print(table)


@batch_app.command("retry")
def batch_retry(
    batch: int = typer.Option(None, "--batch", help="Id lô"),
    out: str = typer.Option(None, "--out", help="Chọn lô theo thư mục kết quả"),
    everything: bool = typer.Option(
        False,
        "--all",
        help="Đưa lại cả job đã done/needs_review vào hàng đợi, không chỉ job failed",
    ),
) -> None:
    """Đưa các job hỏng về hàng đợi để chạy lại."""
    from .batch import store

    batch_id = _resolve_batch(batch, out)
    n = store.reset_jobs(batch_id, only_failed=not everything)
    console.print(f"[green]Đã đưa {n} job về hàng đợi.[/]")


@batch_app.command("export")
def batch_export(
    batch: int = typer.Option(None, "--batch", help="Id lô"),
    out: str = typer.Option(None, "--out", help="Chọn lô theo thư mục kết quả"),
    target: str = typer.Option(None, "-o", "--output", help="Đường dẫn file tổng hợp"),
) -> None:
    """Gộp row.tsv của cả đợt thành một file TSV duy nhất."""
    from .batch import export as batch_exporter
    from .batch import store
    from .profiles import get_profile

    batch_id = _resolve_batch(batch, out)
    info = store.get_batch(batch_id)
    assert info is not None
    try:
        result = batch_exporter.merge(info["out_dir"], target)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    except ValueError as exc:  # thư mục trộn hai profile
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    if not result.rows:
        console.print("[red]Không gom được dòng nào.[/]")
        raise typer.Exit(1)

    n_cols = len(get_profile(result.profile).COLUMNS)
    console.print(
        f"Đã ghi [bold]{result.path}[/] "
        f"({len(result.rows)} dòng, {n_cols} cột, profile {result.profile})"
    )
    console.print(
        f"  có raw_url: {result.with_url} | để trống: {len(result.rows) - result.with_url}"
    )
    for note in result.skipped:
        console.print(f"  [dim][bỏ qua] {escape(note)}[/]")


@batch_app.command("reindex")
def batch_reindex(
    dirs: list[str] = typer.Argument(None, help="Thư mục đợt; bỏ trống = quét mọi output*"),
) -> None:
    """Dựng lại hàng đợi từ các data.json có sẵn trên đĩa.

    An toàn để chạy bất cứ lúc nào: đĩa là nguồn sự thật, DB chỉ là chỉ mục.
    """
    from .batch import reindex

    results = [reindex.reindex_dir(d) for d in dirs] if dirs else reindex.reindex_all()
    table = Table(title="Đã nạp lại chỉ mục")
    table.add_column("#")
    table.add_column("Thư mục")
    table.add_column("POI", justify="right")
    table.add_column("Chi tiết")
    for r in results:
        detail = "  ".join(f"{k}={v}" for k, v in sorted(r["counts"].items()))
        table.add_row(str(r["batch_id"]), r["out_dir"], str(r["total"]), detail)
    console.print(table)
    console.print(f"[green]Tổng: {sum(r['total'] for r in results)} POI[/]")


@app.command()
def ui(
    port: int = typer.Option(8000, "--port", help="Cổng HTTP"),
    host: str = typer.Option("127.0.0.1", "--host", help="Địa chỉ lắng nghe"),
    reload: bool = typer.Option(False, "--reload", help="Tự nạp lại khi sửa code (khi phát triển)"),
) -> None:
    """Mở giao diện quản lý trên trình duyệt."""
    try:
        from .server.app import serve
    except ModuleNotFoundError as exc:
        console.print(
            f"[red]Thiếu thư viện cho giao diện ({exc.name}).[/]\n"
            '[dim]Cài bằng: uv pip install -e ".[ui]"[/]'
        )
        raise typer.Exit(2) from None

    console.print(f"[green]Giao diện:[/] http://{host}:{port}  [dim](Ctrl+C để dừng)[/]")
    serve(host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
