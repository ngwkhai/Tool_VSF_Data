"""Kiểm tra môi trường, tách khỏi tầng hiển thị.

`vsf doctor` trước đây dựng sẵn danh sách kết quả rồi render thẳng ra bảng Rich
và vứt đi — API không dùng lại được gì. Ở đây logic kiểm tra trả về DỮ LIỆU;
CLI render bảng, server serialize JSON, cùng một nguồn sự thật.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from . import browser
from .config import sel, settings


@dataclass
class Check:
    """Một mục kiểm tra.

    `optional=True` nghĩa là hỏng thì tool vẫn chạy đủ, chỉ mất phần tăng cường —
    KHÔNG tính vào mã thoát. Doctor kêu sói thì lần sau không ai buồn đọc nữa.
    """

    label: str
    ok: bool
    detail: str
    optional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_all() -> list[Check]:
    """Chạy toàn bộ mục kiểm tra trong MỘT Session.

    Giữ nguyên từng phép kiểm tra của `vsf doctor` cũ, kể cả các mẹo đã đúc kết:
    soi đúng phần tử captcha thay vì tìm chuỗi "captcha" trong page source (JS
    bundle của TikTok luôn chứa chuỗi đó, tìm thô là báo động giả).
    """
    cfg = settings()
    checks: list[Check] = []

    with browser.Session() as s:
        checks.append(Check("Chrome + cổng CDP", True, f"cổng {cfg['browser']['cdp_port']}"))

        # Duyệt MỌI thread Gemini đang khai báo, không phải đúng hai cái. Từ khi
        # mỗi profile có thể khai cặp thread riêng, kiểm tra cứng 2 thread nghĩa
        # là hai thread của profile lưu trú không bao giờ được doctor rà tới —
        # và lỗi chỉ lộ ra giữa một đợt chạy đêm.
        for slot, url in browser.gemini_slots().items():
            kind = "#1 (hồ sơ POI)" if slot.startswith("gemini_profile") else "#2 (thực đơn / giá phòng)"
            owner = slot.split(":", 1)[1] if ":" in slot else "food"
            label = f"Gemini chat {kind} — profile {owner}"
            page = s.goto(slot, url, force=True)
            page.wait_for_timeout(2500)
            signed_in = "accounts.google.com" not in page.url
            has_editor = page.locator("rich-textarea, [contenteditable='true']").count() > 0
            ok = signed_in and has_editor
            detail = (
                "OK" if ok else ("chưa đăng nhập Google" if not signed_in else "không thấy ô nhập")
            )
            checks.append(Check(label, ok, detail))

        page = s.goto("tiktok", "https://www.tiktok.com/", force=True)
        page.wait_for_timeout(2500)
        blocked = page.locator(sel("tiktok", "captcha")).count() > 0
        checks.append(
            Check("TikTok truy cập được", not blocked, "bị chặn/captcha" if blocked else "OK")
        )

        # Tab "Người dùng" — nguồn tài khoản chính chủ — CHỈ chạy khi đã đăng nhập.
        # Không đăng nhập thì tool vẫn chạy được (khớp tên vẫn nhận ra phần lớn
        # tài khoản chính chủ), chỉ mất phần gỡ được POI tên Nga/Hàn.
        tiktok_signed_in = "Đăng nhập" not in page.locator("body").inner_text()
        checks.append(
            Check(
                "TikTok đăng nhập (tab Người dùng)",
                tiktok_signed_in,
                "OK" if tiktok_signed_in else "chưa đăng nhập — mất tín hiệu tài khoản chính chủ",
                optional=True,
            )
        )

        page = s.goto("facebook", "https://www.facebook.com/", force=True)
        page.wait_for_timeout(2500)
        from .sites import facebook as fb

        signed_in = fb.logged_in(page)
        checks.append(
            Check(
                "Facebook đăng nhập",
                signed_in,
                "OK" if signed_in else "chưa đăng nhập — bước facebook sẽ bị bỏ qua",
                optional=True,
            )
        )

    return checks


def healthy(checks: list[Check]) -> bool:
    """Mọi mục BẮT BUỘC đều đạt. Mục tuỳ chọn hỏng không tính là lỗi môi trường."""
    return all(c.ok for c in checks if not c.optional)


def degraded(checks: list[Check]) -> list[str]:
    """Tên các mục tuỳ chọn đang hỏng — chạy được nhưng thiếu phần tăng cường."""
    return [c.label for c in checks if c.optional and not c.ok]
