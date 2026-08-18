"""Test việc nhận lại tab cũ — không cần chạy Chrome thật."""

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
