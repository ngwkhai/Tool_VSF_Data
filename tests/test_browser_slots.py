"""Test việc nhận lại tab cũ — không cần chạy Chrome thật."""

import re

from vsf.browser import Session, slot_url_prefixes


class FakePage:
    def __init__(self, url: str):
        self.url = url
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, urls: list[str]):
        self._pages = [FakePage(u) for u in urls]
        self.new_page_calls = 0

    @property
    def pages(self):
        return [p for p in self._pages if not p.closed]

    def new_page(self):
        self.new_page_calls += 1
        page = FakePage("about:blank")
        self._pages.append(page)
        return page


def _session(urls: list[str]) -> Session:
    s = Session()
    s._context = FakeContext(urls)
    return s


PROFILE = slot_url_prefixes()["gemini_profile"][0]
MENU = slot_url_prefixes()["gemini_menu"][0]


def test_slot_prefixes_distinguish_the_two_gemini_chats():
    # Hai chat cùng domain -> tiền tố phải là URL thread đầy đủ, không phải domain.
    assert PROFILE != MENU
    assert PROFILE.startswith("https://gemini.google.com/app/")


def test_adopts_existing_tabs_by_url():
    s = _session([PROFILE, "https://www.google.com/maps/place/X", "https://www.tiktok.com/search?q=a"])
    s._adopt_existing_tabs()
    assert set(s._slots) == {"gemini_profile", "gmaps", "tiktok"}


def test_adopted_tabs_are_reused_not_recreated():
    # Đây chính là lỗi người dùng gặp: mỗi lần chạy lại mở thêm tab mới.
    s = _session([PROFILE, "https://www.google.com/maps/place/X"])
    s._adopt_existing_tabs()
    before = s._context.new_page_calls
    s.page("gemini_profile")
    s.page("gmaps")
    assert s._context.new_page_calls == before


def test_two_gemini_chats_do_not_claim_the_same_tab():
    s = _session([PROFILE, MENU])
    s._adopt_existing_tabs()
    assert s._slots["gemini_profile"].url == PROFILE
    assert s._slots["gemini_menu"].url == MENU


def test_gmaps_tab_is_not_mistaken_for_gemini():
    s = _session(["https://www.google.com/maps/search/pho"])
    s._adopt_existing_tabs()
    assert "gemini_profile" not in s._slots
    assert s._slots["gmaps"].url.startswith("https://www.google.com/maps")


def test_blank_tab_is_reused_instead_of_opening_a_new_one():
    s = _session(["about:blank"])
    s._adopt_existing_tabs()
    page = s.page("gmaps")
    assert page.url == "about:blank"
    assert s._context.new_page_calls == 0


def test_opens_a_new_tab_only_when_nothing_matches():
    s = _session(["https://news.example.com"])
    s._adopt_existing_tabs()
    s.page("gmaps")
    assert s._context.new_page_calls == 1


def test_close_stray_tabs_removes_duplicates_and_blanks():
    s = _session([PROFILE, PROFILE, "about:blank", "https://www.tiktok.com/"])
    s._adopt_existing_tabs()
    closed = s.close_stray_tabs()
    assert closed == 2  # bản sao chat Gemini + tab trắng
    assert len(s._context.pages) == 2


def test_close_stray_tabs_keeps_unrelated_user_tabs():
    s = _session([PROFILE, "https://news.example.com"])
    s._adopt_existing_tabs()
    s.close_stray_tabs()
    assert any(p.url == "https://news.example.com" for p in s._context.pages)


def test_close_stray_tabs_never_closes_the_last_tab():
    s = _session(["about:blank"])
    s._adopt_existing_tabs()
    s.close_stray_tabs()
    assert len(s._context.pages) == 1


# -- Thread Gemini riêng cho từng profile -----------------------------------


def _reload_config():
    """Xoá cache lru_cache của config sau khi ghi đè file TOML trong test."""
    from vsf import config

    config.settings.cache_clear()
    config.profile_settings.cache_clear()


def _accom_config(tmp_path, monkeypatch, profile_url: str | None, menu_url: str | None):
    """Bản sao config với thread accom được đặt lại (hoặc gỡ hẳn).

    Ghi ĐÈ khoá đã có chứ không chèn thêm dòng — TOML cấm khai một khoá hai lần,
    và profile accom giờ đã khai sẵn cặp thread riêng trong config thật.
    `None` = gỡ khoá đi, để mô phỏng profile chưa có thread riêng.
    """
    import shutil

    from vsf import config

    dst = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, dst)
    f = dst / "profile_accom.toml"
    text = f.read_text(encoding="utf-8")
    for key, value in (("profile_chat_url", profile_url), ("menu_chat_url", menu_url)):
        pattern = rf'^{key} = ".*"$'
        repl = "" if value is None else f'{key} = "{value}"'
        text, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        assert n == 1, f"không thấy khoá {key} để thay trong profile_accom.toml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", dst)
    _reload_config()


def test_each_profile_gets_its_own_gemini_slot(tmp_path, monkeypatch):
    """Hai thread khác nhau KHÔNG được dùng chung một tab.

    Dùng chung thì `open_chat` thấy tab đã ở đúng tiền tố "gemini.google.com"
    rồi bỏ qua điều hướng, và prompt bay sang nhầm thread.
    """
    from vsf import browser

    a = "https://gemini.google.com/app/aaaa1111"
    b = "https://gemini.google.com/app/bbbb2222"
    try:
        _accom_config(tmp_path, monkeypatch, f"{a}?hl=vi", f"{b}?hl=vi")
        slots = browser.gemini_slots()
        assert len(slots) == 4
        assert slots["gemini_profile:accom"] == a
        assert slots["gemini_menu:accom"] == b
        # Profile mặc định giữ tên slot TRẦN -> tab đang mở vẫn được nhận lại.
        assert "gemini_profile" in slots and "gemini_menu" in slots
        assert browser.gemini_slot("profile", "accom") == "gemini_profile:accom"
        assert browser.gemini_slot("profile", "food") == "gemini_profile"
    finally:
        _reload_config()


def test_four_gemini_tabs_are_adopted_without_stealing_each_other(tmp_path, monkeypatch):
    from vsf import browser

    a = "https://gemini.google.com/app/aaaa1111"
    b = "https://gemini.google.com/app/bbbb2222"
    try:
        _accom_config(tmp_path, monkeypatch, f"{a}?hl=vi", f"{b}?hl=vi")
        s = _session([PROFILE, MENU, a, b])
        s._adopt_existing_tabs()
        assert s._slots["gemini_profile"].url == PROFILE
        assert s._slots["gemini_menu"].url == MENU
        assert s._slots["gemini_profile:accom"].url == a
        assert s._slots["gemini_menu:accom"].url == b
    finally:
        _reload_config()


def test_profile_without_its_own_thread_shares_the_default_slot(tmp_path, monkeypatch):
    """Profile chưa khai thread riêng -> dùng CHUNG slot mặc định.

    Không được đẻ ra slot thứ hai trỏ đúng một URL: `close_stray_tabs` sẽ thấy
    hai slot cùng tiền tố và đóng nhầm tab của slot kia.
    """
    from vsf import browser

    try:
        _accom_config(tmp_path, monkeypatch, None, None)
        slots = browser.gemini_slots()
        assert len(slots) == 2
        assert browser.gemini_slot("profile", "accom") == "gemini_profile"
        assert browser.gemini_slot("menu", "accom") == "gemini_menu"
    finally:
        _reload_config()


def test_real_config_gives_accom_its_own_threads():
    """Chốt hiện trạng: bốn thread khác nhau, bốn slot khác nhau."""
    from vsf import browser

    slots = browser.gemini_slots()
    assert len(slots) == 4
    assert len(set(slots.values())) == 4, "hai profile đang trỏ trùng thread"
