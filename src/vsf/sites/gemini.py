"""Điều khiển giao diện web Gemini.

Dùng chính 2 thread chat có sẵn của người dùng để giữ nguyên ngữ cảnh hội thoại
(không tạo chat mới, không dùng API).
"""

from __future__ import annotations

import re

from playwright.sync_api import Page

from ..config import sel, sel_list, settings
from ..waits import human_delay, wait_stable, wait_until

# Sentinel cho "chưa đọc được" — phân biệt với "đọc được và đúng là rỗng".
_PENDING = "\x00__vsf_pending__"

# Nhãn trợ năng Gemini gắn đầu mỗi khối; innerText lấy cả nó.
_SPOKEN_PREFIX = re.compile(r"^\s*Gemini đã nói\s*", re.IGNORECASE)


def _strip_prefix(text: str) -> str:
    return _SPOKEN_PREFIX.sub("", text).strip()


def _editor(page: Page):
    return page.locator(sel("gemini", "editor")).first


def cancel_stuck_generation(page: Page) -> bool:
    """Huỷ lượt sinh câu trả lời đang treo từ phiên chạy trước, nếu có.

    Một lượt bị treo (Gemini không bao giờ sinh xong) để lại nút "Ngừng tạo câu
    trả lời" thay chỗ send_button VÔ THỜI HẠN. Không huỷ thì mọi tin nhắn gửi
    sau đó lặng lẽ xếp hàng phía sau và không bao giờ có phản hồi — nhìn giống
    hệt timeout do ảnh tải chậm nhưng bản chất khác hẳn (đã kiểm chứng bằng
    cách bấm tay: response xuất hiện ngay khi huỷ xong).
    """
    btn = page.locator(sel("gemini", "stop_button"))
    if btn.count() == 0:
        return False
    btn.first.click()
    page.wait_for_timeout(1000)
    return True


def open_chat(page: Page, url: str) -> None:
    """Mở đúng thread chat và CHỜ lịch sử hội thoại nạp xong.

    Chờ lịch sử là bắt buộc: ô nhập hiện ra trước các khối model-response tới
    vài giây. Nếu đo response_count lúc đó sẽ ra 0, và ngay khi lịch sử nạp xong
    tool sẽ tưởng nhầm đó là câu trả lời mới rồi đọc nội dung của lượt CŨ.
    """
    if not page.url.startswith(url.split("?")[0]):
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_selector(sel("gemini", "editor"), timeout=60_000)
    if "accounts.google.com" in page.url:
        raise RuntimeError(
            "Chưa đăng nhập Google trong profile của tool. Chạy `vsf login` trước."
        )
    cancel_stuck_generation(page)

    try:
        page.wait_for_selector(sel("gemini", "response"), timeout=30_000)
    except Exception:
        # Thread rỗng thật sự cũng hợp lệ — chỉ là chưa có lượt nào.
        return
    # Số khối còn tăng dần trong lúc render -> chờ nó đứng yên.
    wait_stable(
        lambda: response_count(page),
        stable_seconds=2.0,
        timeout=45.0,
        what="lịch sử hội thoại Gemini",
    )


def response_count(page: Page) -> int:
    return page.locator(sel("gemini", "response")).count()


def _is_complete(page: Page) -> bool:
    """Khối phản hồi cuối đã sinh xong chưa?

    Căn cứ: nút đánh giá/sao chép chỉ được gắn vào khi Gemini kết thúc.
    """
    blocks = page.locator(sel("gemini", "response"))
    n = blocks.count()
    if n == 0:
        return False
    last = blocks.nth(n - 1)
    return any(last.locator(css).count() for css in sel_list("gemini", "response_complete"))


def type_prompt(page: Page, text: str) -> None:
    """Nhập text vào ô soạn thảo Quill.

    Dùng execCommand('insertText') thay vì gán innerText: Quill/Angular chỉ cập
    nhật model khi có beforeinput/input event thật, và đây là cách rẻ nhất tạo ra
    chúng cho text dài (nhanh hơn nhiều so với gõ từng phím).

    `insertText` với '\\n' nhúng bên trong CHỈ giữ lại dòng đầu tiên — mọi dòng
    sau đó biến mất, lặng lẽ cắt cụt bất kỳ prompt nhiều đoạn nào (đã gặp:
    profile_prompt/reformat_prompt nhiều dòng bị cắt còn mỗi câu mở đầu, Gemini
    trả lời lạc đề với phần còn lại của thread thay vì làm theo prompt). Phải
    tách theo dòng và chèn `insertLineBreak` giữa các dòng — khác với
    `insertParagraph` (cũng bị cắt) hay Shift+Enter qua keyboard (lặp/xáo trộn
    dòng). Riêng `insertLineBreak` cũng cần `await` một `requestAnimationFrame`
    sau MỖI lệnh: bắn cả loạt execCommand liên tiếp không nhường Quill thời gian
    xử lý mutation của lệnh trước, sinh dư `<br>` (verified: cứ vài chục dòng
    lại phình gấp 4-5 lần) dù nội dung text vẫn nguyên vẹn.
    """
    ed = _editor(page)
    ed.click()
    human_delay(0.2, 0.5)
    page.evaluate(
        """async ([css, text]) => {
            const el = document.querySelector(css);
            el.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            const lines = text.split('\\n');
            const raf = () => new Promise(r => requestAnimationFrame(r));
            for (let i = 0; i < lines.length; i++) {
                if (i > 0) {
                    document.execCommand('insertLineBreak', false, null);
                    await raf();
                }
                document.execCommand('insertText', false, lines[i]);
                await raf();
            }
        }""",
        [sel("gemini", "editor"), text],
    )
    # Nút gửi chỉ xuất hiện khi model đã nhận được text -> đây là xác nhận đáng tin.
    # 30s (không phải 15s cũ): thread chat #2 càng dài (nhiều ảnh + JSON tích luỹ
    # qua nhiều POI) UI càng render chậm về cuối một batch dài.
    page.wait_for_selector(sel("gemini", "send_button"), timeout=30_000)


def send(page: Page) -> None:
    page.locator(sel("gemini", "send_button")).first.click()


def wait_for_response(page: Page, previous_count: int) -> str:
    """Chờ Gemini trả lời xong rồi trả về text của khối phản hồi mới.

    Ba tầng: (1) chờ xuất hiện khối model-response mới, (2) chờ Gemini báo đã
    sinh xong qua nút đánh giá/sao chép, (3) chờ text ngừng thay đổi cho chắc.
    """
    cfg = settings()["gemini"]

    # Dùng chung ngưỡng với _is_complete bên dưới (không phải 180s cố định cũ):
    # thread càng dài, Gemini càng lâu mới BẮT ĐẦU sinh khối phản hồi mới, nên
    # tầng "chờ xuất hiện" cũng cần room như tầng "chờ sinh xong", không phải
    # một ngưỡng ngắn hơn tách biệt.
    wait_until(
        lambda: response_count(page) > previous_count,
        timeout=cfg["response_timeout"],
        what="khối phản hồi mới của Gemini",
    )

    def read() -> str:
        """Đọc text khối cuối. Trả về sentinel khi CHƯA đọc được.

        Không được trả "" khi lỗi: wait_stable sẽ thấy "" lặp lại và kết luận
        câu trả lời đã ổn định, rồi tool ghi nhận một kết quả rỗng.
        """
        blocks = page.locator(sel("gemini", "response"))
        n = blocks.count()
        if n == 0:
            return _PENDING
        try:
            text = (
                blocks.nth(n - 1)
                .locator(sel("gemini", "response_text"))
                .inner_text(timeout=5_000)
            )
        except Exception:
            return _PENDING
        return text if text.strip() else _PENDING

    # Tín hiệu hoàn tất chính: nút đánh giá/sao chép chỉ được gắn vào khối khi
    # Gemini đã sinh xong. Chỉ dựa vào "text ngừng đổi" là SAI — Gemini hay đứng
    # yên nhiều giây giữa chừng (lúc tìm kiếm web, hoặc trước khi bung một khối
    # JSON lớn), và ta sẽ cắt mất phần lớn câu trả lời.
    try:
        wait_until(
            lambda: _is_complete(page),
            timeout=cfg["response_timeout"],
            what="Gemini sinh xong câu trả lời",
        )
    except TimeoutError:
        # Hết giờ vẫn chưa thấy nút hoàn tất: đọc những gì đang có còn hơn mất
        # trắng, nhưng phải đánh dấu để người dùng biết có thể bị cụt.
        text = read()
        if text is _PENDING:
            raise
        return _strip_prefix(text)

    answer = wait_stable(
        read,
        stable_seconds=cfg["stable_seconds"],
        timeout=cfg["response_timeout"],
        what="câu trả lời của Gemini",
    )
    if answer is _PENDING:
        raise RuntimeError("Gemini không trả về nội dung nào đọc được")
    return _strip_prefix(answer)


def ask(page: Page, prompt: str) -> str:
    """Gửi một prompt và trả về câu trả lời đầy đủ."""
    before = response_count(page)
    type_prompt(page, prompt)
    human_delay()
    send(page)
    return wait_for_response(page, before)
