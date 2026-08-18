"""Tìm video TikTok liên quan tới POI."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page

from ..config import sel, sel_list, settings

_VIDEO_ID = re.compile(r"/video/(\d+)")


def posted_at_from_url(url: str) -> str | None:
    """Giải mã ngày đăng từ chính video ID.

    32 bit cao của ID TikTok là Unix timestamp lúc đăng. Chính xác tuyệt đối và
    không tốn thêm một lượt tải trang nào cho mỗi video.
    """
    m = _VIDEO_ID.search(url)
    if not m:
        return None
    ts = int(m.group(1)) >> 32
    # Chặn giá trị vô lý (ID lạ / đổi định dạng): TikTok ra đời 2016.
    if not (1451606400 < ts < 4102444800):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _normalize(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def match_score(poi: str, caption: str) -> float:
    """Tỉ lệ từ trong tên POI xuất hiện ở caption (đã bỏ dấu).

    Khớp theo RANH GIỚI TỪ, không theo chuỗi con: từ ngắn như "on" (từ "Ơn") nằm
    lọt trong "huong" của "hướng dẫn" và sẽ tạo điểm giả.

    Riêng từ dài >= 3 ký tự còn được đối chiếu với bản caption đã bỏ hết khoảng
    trắng, để bắt được hashtag dính liền kiểu "#banhcanhlongca".
    """
    words = [w for w in _normalize(poi).split() if len(w) > 1]
    if not words:
        return 0.0

    hay = _normalize(caption)
    squashed = re.sub(r"[^a-z0-9]", "", hay)

    hits = 0
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", hay):
            hits += 1
        elif len(word) >= 3 and word in squashed:
            hits += 1
    return hits / len(words)


def simplify(poi: str) -> str:
    """Rút gọn tên POI thành từ khoá tìm kiếm.

    TikTok không ra kết quả với tên dài đầy dấu chấm và ngoặc
    ("Bánh Cuốn Tây Sơn. Vn - Ms.Smile (Quán ăn ngon ở Nha Trang)").
    Bỏ phần chú thích trong ngoặc và cắt tại dấu ngăn đầu tiên.
    """
    text = re.sub(r"\([^)]*\)", " ", poi)
    text = re.split(r"[.\-–—|]", text)[0]
    return re.sub(r"\s+", " ", text).strip()


def _query_candidates(poi: str, region: str) -> list[str]:
    """Các truy vấn sẽ thử lần lượt: tên đầy đủ trước, rút gọn sau."""
    anchored = poi if not region or _normalize(region) in _normalize(poi) else f"{poi} {region}"
    queries = [anchored]

    short = simplify(poi)
    if short and _normalize(short) != _normalize(poi):
        if region and _normalize(region) not in _normalize(short):
            short = f"{short} {region}"
        queries.append(short)
    return queries


def _text_of(page: Page, scope, candidates: list[str]) -> str:
    for css in candidates:
        loc = scope.locator(css)
        if loc.count():
            return loc.first.inner_text().strip()
    return ""


def search(page: Page, poi: str) -> list[dict[str, Any]]:
    """Trả về danh sách ứng viên, sắp theo mức khớp tên POI giảm dần.

    Thử tên đầy đủ trước; không ra kết quả thì thử lại với tên rút gọn.
    """
    # Neo vùng như bên Google Maps: tên quán trùng nhau giữa các tỉnh.
    region = settings()["gmaps"].get("search_region", "")
    for query in _query_candidates(poi, region):
        if found := _search_once(page, poi, query):
            return found
    return []


def _search_once(page: Page, poi: str, query: str) -> list[dict[str, Any]]:
    cfg = settings()["tiktok"]
    page.goto(cfg["search_url"].format(query=quote(query)), wait_until="domcontentloaded")

    if page.locator(sel("tiktok", "captcha")).count():
        raise RuntimeError("TikTok đang chặn bằng captcha. Mở cửa sổ tool và giải thủ công.")

    # Kết quả nạp chậm (>7s) và bằng JS -> phải chờ đúng phần tử, không chờ cứng.
    try:
        page.wait_for_selector(sel("tiktok", "search_item"), timeout=45_000)
    except Exception:
        if page.locator(sel("tiktok", "captcha")).count():
            raise RuntimeError("TikTok chặn bằng captcha.") from None
        return []

    items = page.locator(sel("tiktok", "search_item"))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for i in range(items.count()):
        item = items.nth(i)
        # search_top-item chỉ bọc phần thumbnail; caption + tác giả nằm ở thẻ CHA
        # (DivItemContainerV2). Đi lên bằng xpath thay vì bắt theo class, vì
        # TikTok băm tên class ngẫu nhiên giữa các bản build.
        card = item.locator("xpath=..")
        link = item.locator(sel("tiktok", "video_link"))
        if not link.count():
            continue
        url = link.first.get_attribute("href") or ""
        if "/video/" not in url or url in seen:
            continue
        seen.add(url)

        caption = _text_of(page, card, sel_list("tiktok", "caption"))
        author_loc = card.locator(sel("tiktok", "author"))
        out.append(
            {
                "url": url,
                "caption": caption,
                "author": author_loc.first.inner_text().strip()
                if author_loc.count()
                else None,
                "posted_at": posted_at_from_url(url),
                "match_score": round(match_score(poi, caption), 3),
            }
        )

    out.sort(key=lambda c: c["match_score"], reverse=True)
    return out[: cfg["candidate_count"]]
