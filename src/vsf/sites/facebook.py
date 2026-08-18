"""Tra Facebook để XÁC MINH danh tính quán, và lấy Reels của Trang đã xác minh.

Vì sao có bước này: TikTok bắt ta SUY ĐOÁN video nào đúng quán qua tên và caption.
Facebook thì trả thẳng thực thể Trang kèm **địa chỉ đường** — đối chiếu với địa chỉ
Google Maps là ra ngay, không phải đoán. Cùng truy vấn "mosa coffee Nha Trang":

    mo:sa coffee - Nha Trang   | 17/1 Lê Thánh Tôn, Nha Trang   -> khớp
    Xưởng Thời Trang Nam - Mosa| Cầu Giấy, Hà Nội               -> loại
    Kiều Trang Mosaic          | Sơn La Province                -> loại

Đúng bài toán trùng tên khác tỉnh / khác chi nhánh mà TikTok không tự giải được.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page

from ..config import sel, settings
from ..waits import wait_until
from .gmaps import _normalize, address_match

# Plus code Google ("65VV+G77") đứng ở vị trí số nhà nhưng KHÔNG phải địa chỉ đường.
_PLUS_CODE = re.compile(r"^[0-9A-Z]{4}\+")

# Mỗi kết quả là một [role="article"]; các dòng innerText theo thứ tự
# [tên, dòng meta gộp, mô tả, nút Theo dõi]. Dòng meta ngăn bằng dấu chấm giữa:
# "Sản phẩm/Dịch vụ · 1 đánh giá · $ · 17/1 Lê Thánh Tôn, ... · Đang mở cửa · 238 người theo dõi"
_PAGES_JS = """
(sel) => {
  const out = [];
  for (const art of document.querySelectorAll(sel)) {
    const lines = art.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
    if (!lines.length) continue;
    const link = [...art.querySelectorAll('a')]
      .map(a => a.getAttribute('href') || '')
      .find(h => h.includes('profile.php') || /^\\/[A-Za-z0-9._-]+\\/?($|\\?)/.test(h));
    out.push({name: lines[0], meta: lines[1] || '', about: lines[2] || '', href: link || ''});
  }
  return out;
}
"""

# Video trên trang của CHÍNH Trang đó. Hai dạng link cùng tồn tại:
# "/<pageId>/videos/<videoId>" và "https://www.facebook.com/reel/<videoId>/".
_PAGE_VIDEOS_JS = """
() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a')) {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\\/reel\\/(\\d+)/) || href.match(/\\/videos\\/(\\d+)/);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    const isReel = href.includes('/reel/');
    out.push({
      id: m[1],
      is_reel: isReel,
      caption: (a.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 2).join(' '),
    });
  }
  return out;
}
"""


def page_ref(href: str) -> str:
    """Định danh Trang để dựng URL tab video: id số, hoặc slug tuỳ chỉnh."""
    m = re.search(r"profile\.php\?id=(\d+)", href or "")
    if m:
        return m.group(1)
    m = re.match(r"^(?:https://www\.facebook\.com)?/([A-Za-z0-9.\-]+)/?(?:\?|$)", href or "")
    if m and m.group(1) not in {"profile.php", "reel", "watch"}:
        return m.group(1)
    return ""


def logged_in(page: Page) -> bool:
    """Chưa đăng nhập thì Facebook trả thẳng form đăng nhập thay vì kết quả."""
    return not page.locator(sel("facebook", "login_form")).count()


def _address_from_meta(meta: str) -> str:
    """Rút phần địa chỉ khỏi dòng meta ngăn bằng dấu chấm giữa.

    Địa chỉ là đoạn có số nhà hoặc có tên tỉnh/thành — các đoạn khác là nhãn ngành,
    số đánh giá, mức giá, giờ mở cửa, số người theo dõi.
    """
    region = settings()["gmaps"].get("search_region", "")
    for part in (p.strip() for p in meta.split("·")):
        if not part:
            continue
        normalized = _normalize(part)
        has_number = any(c.isdigit() for c in part.split(",")[0])
        # "1 đánh giá" / "238 người theo dõi" cũng có số -> loại bằng từ khoá.
        if any(k in normalized for k in ("danh gia", "nguoi theo doi", "mo cua", "km")):
            continue
        if has_number or (region and _normalize(region) in normalized):
            return part
    return ""


def search_pages(page: Page, poi: str) -> list[dict[str, Any]]:
    """Tra Trang theo tên POI. Trả [] nếu chưa đăng nhập (không raise)."""
    cfg = settings()["facebook"]
    region = settings()["gmaps"].get("search_region", "")
    query = poi if not region or _normalize(region) in _normalize(poi) else f"{poi} {region}"

    page.goto(cfg["search_pages_url"].format(query=quote(query)), wait_until="domcontentloaded")
    if not logged_in(page):
        return []
    try:
        page.wait_for_selector(sel("facebook", "article"), timeout=cfg["search_timeout_ms"])
    except Exception:
        return []

    rows: list[dict[str, Any]] = page.evaluate(_PAGES_JS, sel("facebook", "article"))
    for row in rows:
        row["address"] = _address_from_meta(row.get("meta", ""))
    return rows


def street_segment(google_address: str) -> str:
    """Đoạn SỐ NHÀ + TÊN ĐƯỜNG trong địa chỉ Google, bỏ qua Plus code đứng đầu.

    Google hay đặt Plus code làm đoạn đầu ("65VV+G77, 19 Đ. Lê Thánh Tôn, ..."),
    mà `gmaps.address_match` lại mặc định coi đoạn trước dấu phẩy đầu tiên là tên
    đường. Không lọc thì nó đem "65VV+G77" đi so với địa chỉ Facebook và luôn trả
    0 — Trang ĐÚNG bị loại trong im lặng (đã gặp nguyên văn với "mosa coffee":
    Facebook trả đúng "mo:sa coffee - Nha Trang | 17/1 Lê Thánh Tôn" mà vẫn không
    xác minh được).
    """
    for part in (p.strip() for p in google_address.split(",")):
        if part and not _PLUS_CODE.match(part):
            return part
    return ""


def verify_page(
    poi: str, google_address: str, pages: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Chọn Trang có địa chỉ khớp địa chỉ Google Maps.

    Đối chiếu ĐỊA CHỈ chứ không phải tên: tên trùng nhau là chuyện thường (ba kết
    quả đầu của "mosa coffee" đều chứa "Mosa"), địa chỉ mới tách được.
    Tái dùng `gmaps.address_match` để dùng đúng một quy tắc so khớp với bước maps.
    """
    street = street_segment(google_address)
    if not street:
        return None
    threshold = settings()["facebook"]["address_match_threshold"]

    best, best_score = None, 0.0
    for candidate in pages:
        address = candidate.get("address") or ""
        if not address:
            continue
        # address_match so trên phần ĐƯỜNG của tham số đầu -> truyền địa chỉ Google
        # làm mẫu, địa chỉ Facebook làm chuỗi cần đối chiếu.
        score = address_match(street, address)
        if score > best_score:
            best, best_score = candidate, score

    if best is None or best_score < threshold:
        return None
    return {**best, "address_match": round(best_score, 3)}


def page_reels(page: Page, verified: dict[str, Any]) -> list[dict[str, Any]]:
    """Video đăng bởi CHÍNH Trang đã xác minh.

    Cố ý KHÔNG dùng `search/videos?q=<tên quán>`: tìm theo từ khoá trả về video
    của bất kỳ ai nhắc tới cái tên đó, nên việc xác minh Trang chẳng bảo đảm gì
    cho video — đúng cái tiền đề "Trang đúng ⇒ video đúng quán" bị phá vỡ (đã gặp:
    Trang "mo:sa coffee" xác minh xong nhưng tìm từ khoá trả về Reel của "Góc Của
    Mây" và một quảng cáo hè, cả hai đều không phải của quán).

    Lấy từ tab video của chính Trang thì quan hệ sở hữu là chắc chắn.
    """
    ref = page_ref(verified.get("href", ""))
    if not ref:
        return []
    cfg = settings()["facebook"]

    page.goto(cfg["page_videos_url"].format(ref=ref), wait_until="domcontentloaded")
    if not logged_in(page):
        return []
    try:
        wait_until(
            lambda: bool(page.evaluate(_PAGE_VIDEOS_JS)),
            timeout=cfg["search_timeout_ms"] / 1000,
            what="video của Trang Facebook",
        )
    except TimeoutError:
        return []

    videos: list[dict[str, Any]] = page.evaluate(_PAGE_VIDEOS_JS)
    for video in videos:
        video["url"] = (
            f"https://www.facebook.com/reel/{video['id']}"
            if video["is_reel"]
            else f"https://www.facebook.com/{ref}/videos/{video['id']}"
        )
        video["page"] = verified.get("name", "")
    return videos[: cfg["candidate_count"]]
