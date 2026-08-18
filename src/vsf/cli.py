"""CLI của tool."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import browser, pipeline
from .config import settings

app = typer.Typer(add_completion=False, help="Tool gán nhãn & tăng cường dữ liệu POI")
console = Console()


@app.command()
def run(
    poi: str = typer.Argument(..., help="Tên POI, ví dụ: 'Bánh Canh Trần Văn Ơn'"),
    only: str = typer.Option(
        None, "--only", help=f"Chỉ chạy một bước: {' | '.join(pipeline.STEPS)}"
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
        "--force-food",
        help=(
            "Bỏ qua cổng phân loại FOOD. Dùng khi nhãn ngành của Google gây hiểu "
            "nhầm (vd quán ăn trong khách sạn bị xếp ngành 'Khách sạn'). Chỉ có "
            "hiệu lực cho lần chạy này, không ghi vào data.json."
        ),
    ),
) -> None:
    """Thu thập dữ liệu cho một POI và ghi ra output/<slug>/data.json."""
    from .config import set_output_dir

    set_output_dir(out)

    if only and only not in pipeline.STEPS:
        console.print(f"[red]--only phải là một trong: {', '.join(pipeline.STEPS)}[/]")
        raise typer.Exit(2)

    record = pipeline.run(
        poi, only=only, resume=resume, index=index, address=address, force_food=force_food
    )

    table = Table(title=f"Kết quả: {poi}")
    table.add_column("Bước")
    table.add_column("Trạng thái")
    for step in pipeline.STEPS:
        status = record.steps.get(step, "chưa chạy")
        mark = {"ok": "[green]✓ ok[/]", "failed": "[red]✗ lỗi[/]"}.get(status, f"[dim]{status}[/]")
        table.add_row(step, mark)
    console.print(table)

    for warning in record.all_warnings():
        # escape(): tên bước nằm trong ngoặc vuông, rich sẽ hiểu nhầm là thẻ
        # markup và nuốt mất nếu không thoát.
        console.print("[yellow]![/] " + escape(warning))

    if any(record.steps.get(s) == "failed" for s in pipeline.STEPS):
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
        table.add_column("Khớp")
        table.add_column("Ngày đăng")
        table.add_column("Link")
        for i, c in enumerate(record.tiktok):
            marker = "[green]→[/]" if i == tiktok else " "
            table.add_row(f"{marker}{i}", str(c["match_score"]), (c["posted_at"] or "")[:10], c["url"])
        console.print(table)

    console.print(f"Đã ghi [bold]{pipeline.export_row(record, tiktok_index=tiktok)}[/]")


@app.command()
def login() -> None:
    """Mở Chrome (profile riêng của tool) để bạn đăng nhập Google + TikTok."""
    port = settings()["browser"]["cdp_port"]
    if browser.is_chrome_running(port):
        console.print(f"[green]Chrome của tool đã chạy sẵn[/] trên cổng {port}.")
    else:
        browser.launch_chrome(port)
        console.print("[green]Đã mở Chrome[/] với profile riêng của tool.")

    with browser.Session() as s:
        s.goto("gemini_profile", settings()["gemini"]["profile_chat_url"])
        s.goto("tiktok", "https://www.tiktok.com/")

    console.print(
        "\nHãy đăng nhập [bold]Google[/] và [bold]TikTok[/] trong cửa sổ vừa mở, "
        "rồi chạy [bold]vsf doctor[/] để kiểm tra."
    )


@app.command()
def doctor() -> None:
    """Kiểm tra môi trường: profile, đăng nhập, 2 chat Gemini có truy cập được không."""
    cfg = settings()
    rows: list[tuple[str, bool, str]] = []

    with browser.Session() as s:
        rows.append(("Chrome + cổng CDP", True, f"cổng {cfg['browser']['cdp_port']}"))

        for slot, key, label in [
            ("gemini_profile", "profile_chat_url", "Gemini chat #1 (hồ sơ POI)"),
            ("gemini_menu", "menu_chat_url", "Gemini chat #2 (thực đơn)"),
        ]:
            page = s.goto(slot, cfg["gemini"][key], force=True)
            page.wait_for_timeout(2500)
            signed_in = "accounts.google.com" not in page.url
            has_editor = page.locator("rich-textarea, [contenteditable='true']").count() > 0
            ok = signed_in and has_editor
            detail = (
                "OK"
                if ok
                else ("chưa đăng nhập Google" if not signed_in else "không thấy ô nhập")
            )
            rows.append((label, ok, detail))

        page = s.goto("tiktok", "https://www.tiktok.com/", force=True)
        page.wait_for_timeout(2500)
        # Phải soi đúng phần tử captcha. Chuỗi "captcha" luôn có trong JS bundle
        # của TikTok kể cả khi không hề bị chặn -> tìm trong page source là báo
        # động giả.
        from .config import sel

        blocked = page.locator(sel("tiktok", "captcha")).count() > 0
        rows.append(("TikTok truy cập được", not blocked, "bị chặn/captcha" if blocked else "OK"))

    table = Table(title="vsf doctor")
    table.add_column("Kiểm tra")
    table.add_column("Kết quả")
    table.add_column("Chi tiết")
    for label, ok, detail in rows:
        table.add_row(label, "[green]✓[/]" if ok else "[red]✗[/]", detail)
    console.print(table)

    if not all(ok for _, ok, _ in rows):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
