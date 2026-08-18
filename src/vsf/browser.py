"""Kết nối tới Chrome thật, dùng profile riêng của tool.

Chiến lược: KHÔNG để Playwright tự khởi chạy browser. Thay vào đó ta tự spawn
Chrome (detached) với cổng debug rồi attach qua CDP. Hai lợi ích:

1. Browser sống sót sau khi script kết thúc -> lần chạy sau attach tức thì,
   không phải mở lại và không mất tab.
2. Chrome không bị Playwright đánh dấu là "automated" ở tầng process, nên ít
   bị TikTok/Google chặn hơn.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .config import settings

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Che dấu vết automation phổ biến nhất. Chạy trước mọi script của trang.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


def slot_url_prefixes() -> dict[str, list[str]]:
    """URL đặc trưng của từng slot, dùng để nhận lại tab cũ.

    Thứ tự có ý nghĩa: hai chat Gemini phải khớp trước tiền tố chung
    "gemini.google.com", nếu không tab nào cũng bị nhận nhầm sang slot đầu tiên.
    """
    gemini = settings()["gemini"]
    profile_url = gemini["profile_chat_url"].split("?")[0]
    menu_url = gemini["menu_chat_url"].split("?")[0]
    return {
        "gemini_profile": [profile_url],
        "gemini_menu": [menu_url],
        "gmaps": ["https://www.google.com/maps", "https://maps.google.com"],
        "tiktok": ["https://www.tiktok.com"],
    }


def _profile_dir() -> Path:
    raw = settings()["browser"]["user_data_dir"]
    return Path(raw).expanduser()


def _cdp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_chrome_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"{_cdp_url(port)}/json/version", timeout=1) as r:
            json.load(r)
        return True
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False


def launch_chrome(port: int) -> None:
    """Spawn Chrome detached với profile riêng + cổng debug. Không chặn."""
    if not Path(CHROME_BIN).exists():
        raise RuntimeError(f"Không tìm thấy Chrome tại {CHROME_BIN}")

    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    subprocess.Popen(
        [
            CHROME_BIN,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            # Playwright vấp assertion khi attach vào service_worker của
            # extension ("Assertion error" rồi rớt kết nối CDP). Profile của tool
            # không cần extension nào cả.
            "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            # Google Maps đổi bố cục theo bề rộng cửa sổ. Cố định kích thước để
            # selector ổn định giữa các lần chạy.
            "--window-size=1600,1000",
            "--disable-blink-features=AutomationControlled",
            f"--lang={settings()['browser']['locale']}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # tách khỏi process cha -> sống sau khi script thoát
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if is_chrome_running(port):
            return
        time.sleep(0.4)
    raise RuntimeError(
        f"Chrome không mở được cổng debug {port} sau 30s. "
        f"Kiểm tra xem profile {profile} có đang bị một Chrome khác chiếm không."
    )


class Session:
    """Bọc kết nối CDP + quản lý tab theo 'slot' có tên.

    Mỗi slot (gemini_profile, gemini_menu, gmaps, tiktok) giữ đúng một tab và
    tái sử dụng qua các lần chạy, thay vì mở tab mới mỗi lần.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._slots: dict[str, Page] = {}

    def __enter__(self) -> "Session":
        port = settings()["browser"]["cdp_port"]
        if not is_chrome_running(port):
            launch_chrome(port)

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(_cdp_url(port))
        if not self._browser.contexts:
            raise RuntimeError("Chrome đang chạy nhưng không có context nào.")
        self._context = self._browser.contexts[0]
        self._context.add_init_script(_STEALTH_JS)
        self._adopt_existing_tabs()
        if settings()["browser"].get("close_stray_tabs", True):
            self.close_stray_tabs()
        return self

    def __exit__(self, *exc) -> None:
        # Chỉ ngắt kết nối. KHÔNG đóng browser — profile và tab phải sống tiếp.
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    @property
    def context(self) -> BrowserContext:
        assert self._context is not None, "Session chưa được mở"
        return self._context

    def _adopt_existing_tabs(self) -> None:
        """Nhận lại tab của lần chạy trước, nhận diện theo URL đang mở.

        Trước đây dùng nhãn `window.__vsf_slot__`, nhưng đó là biến JS nên bị xoá
        sạch mỗi lần điều hướng — kết quả là lần chạy nào cũng mở tab mới và tab
        cũ chất đống. URL thì sống sót qua mọi lần điều hướng và cả khi tool thoát.
        """
        claimed: set[int] = set()
        for slot, prefixes in slot_url_prefixes().items():
            for page in self.context.pages:
                if id(page) in claimed or page.is_closed():
                    continue
                if any(page.url.startswith(p) for p in prefixes):
                    self._slots[slot] = page
                    claimed.add(id(page))
                    break

    def close_stray_tabs(self) -> int:
        """Đóng tab trắng và tab trùng slot còn sót lại từ những lần chạy trước."""
        keep = {id(p) for p in self._slots.values()}
        closed = 0
        pages = self.context.pages
        for page in pages:
            if id(page) in keep or page.is_closed():
                continue
            url = page.url
            is_blank = url in ("", "about:blank", "chrome://newtab/")
            is_duplicate = any(
                url.startswith(p) for prefixes in slot_url_prefixes().values() for p in prefixes
            )
            # Giữ lại ít nhất một tab để cửa sổ Chrome không bị đóng theo.
            if (is_blank or is_duplicate) and len(pages) - closed > 1:
                try:
                    page.close()
                    closed += 1
                except Exception:
                    pass
        return closed

    def page(self, slot: str) -> Page:
        """Lấy (hoặc mở) tab dành riêng cho slot này."""
        page = self._slots.get(slot)
        if page is not None and not page.is_closed():
            return page

        # Có thể tab đã được mở ở lần gọi trước trong cùng phiên nhưng chưa gắn slot
        # (ví dụ tab trắng Chrome tạo sẵn) -> tận dụng thay vì mở thêm.
        claimed = {id(p) for p in self._slots.values()}
        for candidate in self.context.pages:
            if id(candidate) in claimed or candidate.is_closed():
                continue
            if candidate.url in ("", "about:blank", "chrome://newtab/"):
                self._slots[slot] = candidate
                return candidate

        page = self.context.new_page()
        self._slots[slot] = page
        return page

    def goto(self, slot: str, url: str, *, force: bool = False) -> Page:
        """Điều hướng slot tới URL. Bỏ qua nếu đã ở đúng đó (trừ khi force)."""
        page = self.page(slot)
        if force or not page.url.startswith(url.split("?")[0]):
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.bring_to_front()
        return page
