"""Dán ảnh vào ô soạn thảo Gemini mà KHÔNG lưu file xuống đĩa.

Cách làm: tải bytes ảnh bằng chính request context của Playwright (đi qua network
stack của Chrome nên không vướng CORS — fetch() trong page thì có thể vướng),
đưa vào page dưới dạng base64, dựng lại thành `File`, gom vào một `DataTransfer`
rồi phát `ClipboardEvent('paste')` lên ô soạn thảo.

Với trang web, việc này không khác gì người dùng bấm Cmd+V.
"""

from __future__ import annotations

import base64
from typing import Any

from playwright.sync_api import Page

from .config import sel
from .waits import wait_until

# Dựng File từ base64 rồi xếp vào hàng đợi trên window.
_PUSH_FILE_JS = """
([b64, name, mime]) => {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    window.__vsfFiles = window.__vsfFiles || [];
    window.__vsfFiles.push(new File([buf], name, {type: mime}));
    return window.__vsfFiles.length;
}
"""

# Phát sự kiện paste kèm toàn bộ file đang xếp hàng.
_DISPATCH_PASTE_JS = """
(css) => {
    const target = document.querySelector(css);
    if (!target) return {ok: false, reason: 'không thấy ô soạn thảo'};
    const files = window.__vsfFiles || [];
    if (!files.length) return {ok: false, reason: 'không có file nào trong hàng đợi'};

    const dt = new DataTransfer();
    for (const f of files) dt.items.add(f);

    target.focus();
    const ev = new ClipboardEvent('paste', {
        clipboardData: dt, bubbles: true, cancelable: true,
    });
    const delivered = target.dispatchEvent(ev);
    window.__vsfFiles = [];
    return {ok: true, count: files.length, delivered};
}
"""


def _mime_for(url: str) -> str:
    lowered = url.lower()
    if ".png" in lowered:
        return "image/png"
    if ".webp" in lowered:
        return "image/webp"
    return "image/jpeg"


def fetch_bytes(page: Page, url: str) -> bytes | None:
    """Tải ảnh qua network stack của Chrome (kèm cookie, không vướng CORS)."""
    try:
        response = page.request.get(url, timeout=30_000)
    except Exception:
        return None
    if not response.ok:
        return None
    return response.body()


def paste_images(page: Page, urls: list[str]) -> dict[str, Any]:
    """Dán danh sách ảnh vào ô soạn thảo Gemini.

    Trả về thống kê: đã dán mấy ảnh, ảnh nào tải lỗi.
    """
    editor_css = sel("gemini", "editor")
    page.evaluate("window.__vsfFiles = []")

    queued, failed = 0, []
    for i, url in enumerate(urls, start=1):
        data = fetch_bytes(page, url)
        if not data:
            failed.append(url)
            continue
        page.evaluate(
            _PUSH_FILE_JS,
            [base64.b64encode(data).decode(), f"menu_{i:02d}.jpg", _mime_for(url)],
        )
        queued += 1

    if queued == 0:
        return {"pasted": 0, "failed": failed, "error": "không tải được ảnh nào"}

    page.locator(editor_css).first.click()
    # Baseline: đo TRƯỚC khi dán vì trang luôn có sẵn 1 spinner không liên quan
    # (không phải của ảnh) -> phải trừ đi mới nhận ra đúng lúc ảnh tải xong.
    spinner_css = sel("gemini", "upload_spinner")
    baseline_spinners = page.locator(spinner_css).count()
    result = page.evaluate(_DISPATCH_PASTE_JS, editor_css)

    # send_button bật sẵn ngay khi vừa dán xong, TRƯỚC KHI ảnh tải xong thật sự
    # -> không phải tín hiệu đáng tin. Phải tự chờ spinner của từng ảnh biến mất,
    # nếu không Gemini nhận tin nhắn với ảnh dở dang và không bao giờ trả lời.
    try:
        wait_until(
            lambda: page.locator(spinner_css).count() <= baseline_spinners,
            timeout=45.0,
            poll=0.5,
            what="ảnh thực đơn tải lên Gemini xong",
        )
    except TimeoutError:
        pass
    page.wait_for_timeout(800)

    return {"pasted": queued, "failed": failed, "dispatch": result}


def upload_via_file_input(page: Page, urls: list[str]) -> dict[str, Any]:
    """Phương án dự phòng nếu Gemini không nhận sự kiện paste tổng hợp.

    set_input_files nhận thẳng buffer trong bộ nhớ, nên vẫn giữ đúng yêu cầu
    "không có file nào chạm đĩa".
    """
    payloads = []
    failed = []
    for i, url in enumerate(urls, start=1):
        data = fetch_bytes(page, url)
        if not data:
            failed.append(url)
            continue
        payloads.append({"name": f"menu_{i:02d}.jpg", "mimeType": _mime_for(url), "buffer": data})

    if not payloads:
        return {"pasted": 0, "failed": failed, "error": "không tải được ảnh nào"}

    file_input = page.locator(sel("gemini", "file_input"))
    if file_input.count() == 0:
        menu_button = page.locator(sel("gemini", "upload_menu_button"))
        if menu_button.count():
            menu_button.first.click()
            page.wait_for_timeout(1500)
        file_input = page.locator(sel("gemini", "file_input"))
    if file_input.count() == 0:
        return {"pasted": 0, "failed": failed, "error": "không tìm thấy input[type=file]"}

    spinner_css = sel("gemini", "upload_spinner")
    baseline_spinners = page.locator(spinner_css).count()
    file_input.first.set_input_files(payloads)
    try:
        wait_until(
            lambda: page.locator(spinner_css).count() <= baseline_spinners,
            timeout=45.0,
            poll=0.5,
            what="ảnh thực đơn tải lên Gemini xong",
        )
    except TimeoutError:
        pass
    page.wait_for_timeout(800)
    return {"pasted": len(payloads), "failed": failed, "via": "file_input"}
