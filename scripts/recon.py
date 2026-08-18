"""Script dò selector bằng Playwright (click thật, khác hẳn JS click).

Dùng khi Google/TikTok đổi giao diện. Kết quả in ra để vá config/selectors.toml.

    .venv/bin/python scripts/recon.py gmaps "Bánh Canh Trần Văn Ơn"
    .venv/bin/python scripts/recon.py tiktok "Bánh Canh Trần Văn Ơn"
"""

from __future__ import annotations

import sys
from urllib.parse import quote

from playwright.sync_api import Page

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from vsf import browser  # noqa: E402


def probe(page: Page, label: str, selectors: dict[str, str]) -> None:
    print(f"\n--- {label} ---")
    for name, css in selectors.items():
        try:
            n = page.locator(css).count()
        except Exception as exc:  # selector sai cú pháp
            print(f"  {name:24} ERR {exc}")
            continue
        sample = ""
        if n:
            try:
                el = page.locator(css).first
                sample = (el.get_attribute("aria-label") or el.inner_text() or "")[:70]
                sample = sample.replace("\n", " / ")
            except Exception:
                sample = "(không đọc được)"
        print(f"  {name:24} n={n:<4} {sample}")


def recon_gmaps(page: Page, poi: str) -> None:
    page.goto(
        f"https://www.google.com/maps/search/{quote(poi)}?hl=vi",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("a.hfpxzc", timeout=30_000)
    href = page.locator("a.hfpxzc").first.get_attribute("href")
    print(f"Kết quả đầu: {page.locator('a.hfpxzc').first.get_attribute('aria-label')}")
    page.goto(href, wait_until="domcontentloaded")
    page.wait_for_selector("h1.DUwDvf", timeout=30_000)
    print(f"Đã vào trang địa điểm: {page.locator('h1.DUwDvf').first.inner_text()}")

    probe(page, "Panel tổng quan", {
        "place_title": "h1.DUwDvf",
        "rating_block": "div.F7nice",
        "phone": "[data-item-id^='phone:tel:']",
        "hours_day_button": "button.mWUh3d",
        "hero_image": ".RZ66Rb img",
        "secondary_image": "img.DaSXdd",
        "tab": "button[role='tab']",
    })

    print("\n[TABS] liệt kê thật:")
    tabs = page.locator("button[role='tab']")
    for i in range(tabs.count()):
        t = tabs.nth(i)
        print(f"   aria={t.get_attribute('aria-label')!r} text={t.inner_text()!r}")

    print("\n[HOURS] thử mở dropdown giờ mở cửa:")
    for css in (
        "[data-item-id='oh']",
        "button[aria-label*='Hiện giờ mở cửa trong tuần']",
        "span[aria-label='Hiện giờ mở cửa trong tuần']",
        "div.OqCZI",
    ):
        loc = page.locator(css)
        print(f"   {css:48} n={loc.count()}")
    for css in ("[data-item-id='oh']", "div.OqCZI", "button[aria-label*='giờ mở cửa']"):
        if page.locator(css).count():
            try:
                page.locator(css).first.click(timeout=5000)
                page.wait_for_timeout(1500)
                n = page.locator("button.mWUh3d").count()
                print(f"   -> click {css}: hours_day_button n={n}")
                if n >= 7:
                    for i in range(n):
                        print(f"      {page.locator('button.mWUh3d').nth(i).get_attribute('aria-label')}")
                    break
            except Exception as exc:
                print(f"   -> click {css} lỗi: {str(exc)[:80]}")

    print("\n[IMAGES] sau khi panel ổn định:")
    for css in ("img.DaSXdd", ".RZ66Rb img", ".aoRNLd img", "button img[src*='googleusercontent']"):
        loc = page.locator(css)
        print(f"   {css:44} n={loc.count()}")
        for i in range(min(4, loc.count())):
            src = loc.nth(i).get_attribute("src") or ""
            print(f"      {src[:110]}")

    print("\n[TAB] click tab đánh giá bằng Playwright (trusted click)")
    review_tab = page.locator("button[role='tab'][aria-label*='Bài đánh giá']")
    if review_tab.count() == 0:
        review_tab = page.locator("button[role='tab']").nth(1)
    review_tab.first.click()
    page.wait_for_timeout(3500)

    probe(page, "Sau khi vào tab đánh giá", {
        "review_card_jftiEf": "div.jftiEf",
        "review_card_GHT2ce": "div.GHT2ce",
        "review_author": ".d4r55",
        "review_stars_img": "span[role='img'][aria-label*='sao']",
        "review_date": ".rsqaWe",
        "review_text": ".wiI7pd",
        "more_button": "button[aria-label='Xem thêm']",
        "sort_button_aria": "button[aria-label='Sắp xếp bài đánh giá']",
        "sort_button_generic": "button.g88MCb",
        "scroll_pane": "div.m6QErb.DxyBCb",
    })

    # Liệt kê mọi nút trông giống nút sắp xếp.
    print("\n[SORT] các nút ứng viên:")
    for i in range(page.locator("button").count()):
        b = page.locator("button").nth(i)
        try:
            aria = b.get_attribute("aria-label") or ""
            txt = (b.inner_text() or "").strip()
        except Exception:
            continue
        if "ắp xếp" in aria or "ắp xếp" in txt or "Phù hợp nhất" in txt:
            print(f"   aria={aria!r} text={txt!r} class={b.get_attribute('class')}")

    print("\n[SORT] mở menu sắp xếp:")
    page.locator("button.HQzyZ").first.click()
    page.wait_for_timeout(1500)
    for css in ("div[role='menuitemradio']", "div[role='menuitem']", "li[role='menuitemradio']"):
        loc = page.locator(css)
        print(f"   {css:34} n={loc.count()}")
        for i in range(loc.count()):
            print(f"      [{i}] {loc.nth(i).inner_text()!r}  id={loc.nth(i).get_attribute('data-index')}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)

    # -- Gallery ảnh: quay lại tab Tổng quan rồi mở ảnh header ------------
    print("\n[PHOTO] quay lại Tổng quan, mở gallery:")
    page.locator("button[role='tab'][aria-label*='Tổng quan']").first.click()
    page.wait_for_timeout(2500)
    for css in ("button.aoRNLd", "button[jsaction*='pane.heroHeaderImage']", ".RZ66Rb button", "button.Yr7JMd"):
        print(f"   {css:44} n={page.locator(css).count()}")
    opened = False
    for css in ("button.aoRNLd", ".RZ66Rb button", "button[jsaction*='heroHeaderImage']"):
        if page.locator(css).count():
            try:
                page.locator(css).first.click(timeout=6000)
                page.wait_for_timeout(3500)
                if page.locator("button.LxQkid, div[role='tablist'] button").count():
                    print(f"   -> mở được bằng {css}")
                    opened = True
                    break
            except Exception as exc:
                print(f"   -> {css} lỗi: {str(exc)[:70]}")
    print(f"   gallery mở: {opened}, url={page.url[:80]}")

    print("\n[PHOTO] chip phân loại ảnh (tìm 'Thực đơn'):")
    for css in ("button.LxQkid", "div[role='tablist'] button", "button[data-tab-index]"):
        loc = page.locator(css)
        print(f"   {css:34} n={loc.count()}")
        for i in range(min(12, loc.count())):
            print(f"      [{i}] {loc.nth(i).inner_text()!r} aria={loc.nth(i).get_attribute('aria-label')!r}")


def recon_tiktok(page: Page, poi: str) -> None:
    page.goto(
        f"https://www.tiktok.com/search?q={quote(poi)}", wait_until="domcontentloaded"
    )
    page.wait_for_timeout(7000)
    print(f"URL sau khi load: {page.url}")

    probe(page, "TikTok search", {
        "captcha": "#captcha-verify-page",
        "login_modal": "div[id*='login-modal'], div[data-e2e='modal-close-inner-button']",
        "search_top_item": "div[data-e2e='search_top-item']",
        "search_card_item": "div[data-e2e='search-card-item']",
        "video_link": "a[href*='/video/']",
        "caption_1": "div[data-e2e='search-card-video-caption']",
        "caption_2": "[data-e2e='search-card-desc']",
        "author": "[data-e2e='search-card-user-unique-id']",
    })

    links = page.locator("a[href*='/video/']")
    print(f"\n[LINKS] tổng {links.count()}, 5 cái đầu:")
    for i in range(min(5, links.count())):
        href = links.nth(i).get_attribute("href") or ""
        print(f"   {href}")

    print("\n[DIAG] trạng thái trang thật:")
    print(f"   title   = {page.title()!r}")
    body = page.evaluate("document.body.innerText.slice(0, 400)")
    print(f"   bodyTxt = {body!r}")
    e2e = page.evaluate(
        "[...new Set([...document.querySelectorAll('[data-e2e]')]"
        ".map(e=>e.getAttribute('data-e2e')))].slice(0,40)"
    )
    print(f"   data-e2e có trên trang = {e2e}")
    print(f"   tổng thẻ a = {page.locator('a').count()}")
    hrefs = page.evaluate(
        "[...new Set([...document.querySelectorAll('a')].map(a=>a.getAttribute('href')||''))]"
        ".filter(h=>h).slice(0,15)"
    )
    print(f"   href mẫu = {hrefs}")


def main() -> None:
    site = sys.argv[1] if len(sys.argv) > 1 else "gmaps"
    poi = sys.argv[2] if len(sys.argv) > 2 else "Bánh Canh Trần Văn Ơn"

    with browser.Session() as s:
        page = s.goto(f"recon_{site}", "about:blank")
        if site == "gmaps":
            recon_gmaps(page, poi)
        elif site == "tiktok":
            recon_tiktok(page, poi)
        else:
            raise SystemExit(f"Không biết site {site!r}. Dùng: gmaps | tiktok")


if __name__ == "__main__":
    main()
