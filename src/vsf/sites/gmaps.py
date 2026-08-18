"""Thu thập dữ liệu POI từ Google Maps.

QUY TẮC: Google Maps chỉ phản ứng với CLICK THẬT. Mọi thao tác dùng
locator.click() của Playwright (trusted event qua CDP), tuyệt đối không dùng
element.click() trong page.evaluate() — đã kiểm chứng là không ăn.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page

from ..config import sel, sel_list, settings
from ..waits import human_delay, wait_stable, wait_until

# Thứ tự trong menu sắp xếp (data-index), xác minh 2026-08-11.
SORT_RELEVANT, SORT_NEWEST, SORT_HIGHEST, SORT_LOWEST = 0, 1, 2, 3

# Tên mục ảnh cần lấy. CHỈ mục thực đơn — "Thực phẩm và đồ uống" là ảnh món ăn
# do khách chụp, không phải bảng giá, dán sang Gemini chỉ sinh ra menu bịa.
# Quán không có mục này thì cột `menu` để trống, đó là kết quả đúng.
MENU_CATEGORY_PREFERENCE = ["Thực đơn", "Menu"]

_DAY_HOURS = re.compile(r"^(.+?),(.+?),\s*Sao chép", re.S)

# "Mở cửa cả ngày" / "Mở cửa 24 giờ" / "Open 24 hours" -> quy ước 0:00–23:59.
_ALL_DAY = re.compile(r"cả ngày|24\s*giờ|24\s*hours|24/7", re.IGNORECASE)
ALL_DAY_OPEN, ALL_DAY_CLOSE = "0:00", "23:59"


def current_url(page: Page) -> str:
    """URL thật của trang.

    KHÔNG dùng `page.url`: Google Maps đổi URL bằng history.replaceState và
    Playwright không cập nhật thuộc tính đó -> nó kẹt ở URL /maps/search/ ban
    đầu, khiến ta mất sạch lat/long/place_id vốn nằm trong URL trang địa điểm.
    """
    try:
        return page.evaluate("location.href")
    except Exception:
        return page.url


def _first_present(page: Page, candidates: list[str]):
    """Trả về locator đầu tiên trong danh sách ứng viên mà có phần tử."""
    for css in candidates:
        loc = page.locator(css)
        if loc.count():
            return loc
    return None


def _click_retrying(locator, tries: int = 3, timeout: int = 10_000, wait_ms: int = 1500) -> None:
    """Click bền hơn locator.first.click() thường.

    Một overlay nhỏ (tooltip/toast) của Google Maps đôi khi che tạm thời và
    chặn sự kiện con trỏ (đã gặp: "div.UsUSKc.fontBodySmall.RfCwec" đè lên nút
    mở gallery ảnh) -> thử lại vài lần thay vì bỏ cuộc ngay ở lần đầu.

    Nếu vẫn bị chặn sau ngần ấy lần đợi, đây thường KHÔNG phải toast thoáng qua
    mà là banner "Hiển thị kết quả cho X. Tìm kiếm thay cho Y" (Google diễn giải
    lại truy vấn có ký tự đặc biệt như "&" trong tên quán) — banner này đè lên
    ĐÚNG PHẦN TRÊN của khối ảnh đại diện, chỗ Playwright mặc định nhắm vào
    (chính giữa phần tử). `force=True` KHÔNG giúp được gì ở đây: force vẫn bắn
    sự kiện vào cùng toạ độ giữa đó, chỉ bỏ qua bước kiểm tra che khuất, nên vẫn
    trúng banner chứ không trúng nút (đã kiểm chứng bằng elementFromPoint — góc
    dưới-phải mới thật sự là <img>, phần trên là banner). Phải nhắm CHỦ ĐỘNG
    lệch xuống góc dưới-phải, nơi banner không phủ tới, vẫn là click chuột thật
    qua CDP tại toạ độ đó (Locator.click với `position`).
    """
    last_exc: Exception | None = None
    for _ in range(tries):
        try:
            locator.first.click(timeout=timeout)
            return
        except Exception as exc:
            last_exc = exc
            locator.page.wait_for_timeout(wait_ms)
    box = locator.first.bounding_box()
    if box:
        offset = {"x": box["width"] * 0.85, "y": box["height"] * 0.85}
        try:
            locator.first.click(timeout=timeout, position=offset)
            return
        except Exception as exc:
            last_exc = exc
        try:
            locator.first.click(timeout=timeout, position=offset, force=True)
            return
        except Exception as exc:
            last_exc = exc
    raise last_exc


def upgrade_image_url(url: str, size: int) -> str:
    """Đổi hậu tố kích thước googleusercontent sang độ phân giải cao.

    Dùng dạng `=w{size}-h{size}-p-k-no` cho khớp định dạng dataset đang dùng.
    URL không phải googleusercontent (vd thumbnail Street View) giữ nguyên.
    """
    if "googleusercontent.com" not in url:
        return url
    base = url.split("=")[0]
    return f"{base}=w{size}-h{size}-p-k-no"


# Toạ độ và place_id nằm sẵn trong URL trang địa điểm — khỏi phải bới DOM.
_LATLNG = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
_PLACE_ID = re.compile(r"!19s(ChIJ[\w-]+)")
_LATLNG_AT = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")


# Nhiều URL KHÔNG có !19s, chỉ có cặp FID hex !1s0x<a>:0x<b>. place_id dạng
# ChIJ... chính là base64url của protobuf chứa cặp số đó.
_FID = re.compile(r"!1s(0x[0-9a-f]+):(0x[0-9a-f]+)")

# Dataset ghi toạ độ với 4 chữ số thập phân.
COORD_PRECISION = 4


def place_id_from_fid(hex_a: str, hex_b: str) -> str:
    """0x317067143e2e58f5:0x1a7c88a576fbe210 -> ChIJ9VguPhRncDEREOL7dqWIfBo.

    Cấu trúc protobuf: 0a 12 09 <a little-endian> 11 <b little-endian>,
    rồi base64url và bỏ dấu '=' đệm. (Đã đối chiếu với place_id thật.)
    """
    payload = (
        b"\x0a\x12\x09"
        + int(hex_a, 16).to_bytes(8, "little")
        + b"\x11"
        + int(hex_b, 16).to_bytes(8, "little")
    )
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def location_from_url(url: str) -> dict[str, Any]:
    """Rút lat/long/place_id từ URL trang địa điểm."""
    out: dict[str, Any] = {}
    # Ưu tiên !3d/!4d (toạ độ CỦA ĐỊA ĐIỂM); @lat,lng chỉ là tâm khung nhìn.
    if m := _LATLNG.search(url):
        lat, lng = float(m.group(1)), float(m.group(2))
    elif m := _LATLNG_AT.search(url):
        lat, lng = float(m.group(1)), float(m.group(2))
    else:
        lat = lng = None
    if lat is not None:
        out["lat"] = round(lat, COORD_PRECISION)
        out["long"] = round(lng, COORD_PRECISION)

    if m := _PLACE_ID.search(url):
        out["place_id"] = m.group(1)
    elif m := _FID.search(url):
        out["place_id"] = place_id_from_fid(m.group(1), m.group(2))
    return out


def _normalize(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    # Google hay trả dấu nháy đơn cong (’) trong khi tên POI người dùng gõ
    # thường là nháy thẳng (') -> quy về chung một dạng để không lệch match.
    for quote in ("’", "‘", "`", "´"):
        text = text.replace(quote, "'")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def search_query(poi: str, region: str, address_hint: str = "") -> str:
    """Neo truy vấn vào địa chỉ/vùng cần gán nhãn để Google không trả nhầm quán
    trùng tên ở nơi khác.

    Có địa chỉ mẫu -> ưu tiên ghép phần ĐƯỜNG (đoạn trước dấu phẩy đầu tiên):
    Google tự phân biệt được nhiều quán trùng tên chính xác hơn hẳn so với chỉ
    ghép tên vùng ("Greek Cuisine" mà không kèm đường ra "Greek Kitchen" ở phố
    khác — kèm số nhà + tên đường thì đúng ngay).
    """
    query = poi
    if address_hint:
        street = address_hint.split(",")[0].strip()
        if street and _normalize(street) not in _normalize(query):
            query = f"{query} {street}"
    if region and _normalize(region) not in _normalize(query):
        query = f"{query} {region}"
    return query


def name_match(poi: str, found: str) -> float:
    """Tỉ lệ từ trong tên POI xuất hiện ở tên Google trả về (đã bỏ dấu)."""
    words = [w for w in _normalize(poi).split() if len(w) > 1]
    if not words:
        return 1.0
    hay = _normalize(found)
    return sum(1 for w in words if w in hay) / len(words)


def address_match(hint: str, found: str) -> float:
    """Tỉ lệ từ trong phần ĐƯỜNG của địa chỉ mẫu khớp với địa chỉ Google tìm được.

    Chỉ so trên đoạn trước dấu phẩy đầu tiên (số nhà + tên đường) — phần đuôi
    (phường/tỉnh) đổi tên liên tục sau sáp nhập và không đáng tin để đối chiếu.
    Không có địa chỉ mẫu thì coi như khớp (không có gì để kiểm tra).
    """
    if not hint:
        return 1.0
    street = hint.split(",")[0]
    words = [w for w in _normalize(street).split() if len(w) > 1]
    if not words:
        return 1.0
    hay = _normalize(found)
    return sum(1 for w in words if w in hay) / len(words)


# -- Mở trang địa điểm -----------------------------------------------------


def open_place(page: Page, poi: str, address_hint: str = "") -> str:
    """Tìm POI rồi mở trang chi tiết. Trả về URL trang địa điểm.

    Đi qua href của kết quả đầu thay vì click vào nó: điều hướng trực tiếp ổn
    định hơn hẳn so với click vào danh sách kết quả của SPA.
    """
    cfg = settings()["gmaps"]
    query = search_query(poi, cfg.get("search_region", ""), address_hint)
    url = cfg["search_url"].format(query=quote(query, safe=""))
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)

    title_css = sel("gmaps", "place_title")
    link_css = sel("gmaps", "result_link")

    # Truy vấn cụ thể được Google chuyển thẳng sang trang địa điểm, nhưng việc đó
    # xảy ra SAU domcontentloaded. Kiểm tra page.url ngay lúc này sẽ thấy vẫn là
    # /maps/search/ rồi ngồi đợi danh sách kết quả không bao giờ tới.
    # Vì vậy: chờ một trong hai trạng thái xuất hiện rồi mới quyết định.
    wait_until(
        lambda: page.locator(title_css).count() or page.locator(link_css).count(),
        timeout=45.0,
        what="Google Maps hiện trang địa điểm hoặc danh sách kết quả",
    )

    if page.locator(title_css).count() == 0:
        href = page.locator(link_css).first.get_attribute("href")
        if not href:
            raise RuntimeError(f"Không lấy được link kết quả cho POI {poi!r}")
        page.goto(href, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_selector(title_css, timeout=45_000)

    # URL là nguồn lấy lat/long/place_id, nhưng SPA cập nhật nó SAU khi tiêu đề
    # hiện ra. Không chờ thì page.url vẫn là URL tìm kiếm và ta mất cả ba trường.
    try:
        wait_until(
            lambda: "/maps/place/" in current_url(page),
            timeout=20.0,
            what="URL chuyển sang dạng trang địa điểm",
        )
    except TimeoutError:
        pass  # vẫn lấy được các trường khác từ DOM

    human_delay()
    return current_url(page)


# -- Thông tin cơ bản ------------------------------------------------------


# Ký tự vùng dùng riêng = glyph icon Material của Google. Chuỗi nào chứa nó là
# đã bắt nhầm một nút biểu tượng, không phải nhãn ngành.
_PRIVATE_USE = re.compile(r"[-]")


def clean_category(text: str) -> str:
    """Làm sạch nhãn ngành. Trả "" nếu chuỗi bắt được rõ ràng không phải nhãn.

    Bố cục khách sạn nhét dấu chấm giữa vào đầu ("·Khách sạn 3 sao"); các nút
    biểu tượng thì mang glyph icon và text nhiều dòng ("\nKhách sạn gần
    đây" — chip gợi ý, KHÔNG phải ngành nghề của chính địa điểm này). Thà để
    trống còn hơn nhả nhãn sai: nhãn sai lái thẳng cổng phân loại đi lạc.
    """
    label = (text or "").strip().lstrip("·").strip()
    if not label or "\n" in label or _PRIVATE_USE.search(label):
        return ""
    return label


def basic_info(page: Page, requested: str = "", address_hint: str = "") -> dict[str, Any]:
    url = current_url(page)
    info: dict[str, Any] = {"place_url": url}
    info.update(location_from_url(url))
    info["name"] = page.locator(sel("gmaps", "place_title")).first.inner_text().strip()

    # Nhãn ngành nghề Google ("Nhà hàng hải sản", "Khách sạn 3 sao") — nguồn
    # quyết định category_l1/category_l2. Đọc hụt thì để trống, KHÔNG raise:
    # schema.classify_l1 fail-open thành FOOD nên luồng cũ vẫn chạy nguyên vẹn.
    if cat := _first_present(page, sel_list("gmaps", "place_category")):
        if label := clean_category(cat.first.inner_text()):
            info["category_raw"] = label

    if requested:
        # Lấy nhầm quán làm SAI TOÀN BỘ dòng dữ liệu mà không có dấu hiệu gì.
        # Ghi lại điểm khớp tên để pipeline cảnh báo/chặn.
        info["name_match"] = round(name_match(requested, info["name"]), 3)

    rating = page.locator(sel("gmaps", "rating_block"))
    if rating.count():
        text = rating.first.inner_text().replace("\n", " ").strip()
        info["rating_raw"] = text
        if m := re.search(r"(\d+[.,]\d+)", text):
            info["rating"] = float(m.group(1).replace(",", "."))
        if m := re.search(r"\(([\d.,]+)\)", text):
            info["review_count"] = int(re.sub(r"[.,]", "", m.group(1)))

    addr = page.locator(sel("gmaps", "address"))
    if addr.count():
        label = addr.first.get_attribute("aria-label") or ""
        info["address"] = label.split(":", 1)[-1].strip() or None

    if address_hint:
        info["address_match"] = round(address_match(address_hint, info.get("address") or ""), 3)

    phone = page.locator(sel("gmaps", "phone"))
    if phone.count():
        # data-item-id có dạng "phone:tel:0918253515" -> lấy phần sau cùng.
        item_id = phone.first.get_attribute("data-item-id") or ""
        info["phone"] = item_id.split("tel:", 1)[-1] or None

    return info


def parse_day_hours(hours: str) -> dict[str, Any]:
    """Chuỗi giờ của MỘT ngày -> {hours, open, close}.

    Ca gãy lấy giờ mở của ca đầu và giờ đóng của ca cuối: dataset chỉ có một cặp
    open/close, cắt bớt ca sau sẽ báo quán đóng cửa sớm hơn thực tế.
    """
    entry: dict[str, Any] = {"hours": hours}
    times = re.findall(r"\d{1,2}:\d{2}", hours)
    if len(times) >= 2:
        entry["open"], entry["close"] = times[0], times[-1]
    elif _ALL_DAY.search(hours):
        entry["open"], entry["close"] = ALL_DAY_OPEN, ALL_DAY_CLOSE
        entry["all_day"] = True
    return entry


def opening_hours(page: Page) -> dict[str, Any]:
    """Bảng giờ mở/đóng cửa 7 ngày.

    Mỗi ngày là 1 nút với aria-label "Thứ Ba,10:00 đến 14:00, Sao chép giờ mở cửa".
    Bảng có thể đang thu gọn -> click hàng giờ để bung (chỉ khi chưa đủ 7 nút,
    vì click lúc đang mở sẽ đóng lại).

    Ba dạng nội dung phải xử lý khác nhau:
      "10:00 đến 14:00"                    -> mở 10:00, đóng 14:00
      "11:00 đến 14:00, 17:00 đến 21:00"   -> mở 11:00, đóng 21:00 (ca gãy)
      "Mở cửa cả ngày"                     -> mở 0:00, đóng 23:59
      "Đóng cửa"                           -> không có giờ, để trống
    """
    day_css = sel("gmaps", "hours_day_button")

    if page.locator(day_css).count() < 7:
        toggle = page.locator(sel("gmaps", "hours_toggle"))
        if toggle.count():
            try:
                toggle.first.click(timeout=8000)
                page.wait_for_timeout(1200)
            except Exception:
                pass

    days = page.locator(day_css)
    result: dict[str, Any] = {"by_day": {}, "raw": []}
    for i in range(days.count()):
        label = days.nth(i).get_attribute("aria-label") or ""
        result["raw"].append(label)
        if m := _DAY_HOURS.match(label.strip()):
            day, hours = m.group(1).strip(), m.group(2).strip()
            result["by_day"][day] = parse_day_hours(hours)

    if len(result["by_day"]) < 7:
        result["incomplete"] = True
    return result


# -- Ảnh -------------------------------------------------------------------


def photos(page: Page) -> dict[str, Any]:
    """Ảnh đại diện + N ảnh phụ. Chỉ trả URL, không tải file."""
    cfg = settings()["gmaps"]
    size = cfg["image_size"]

    hero_loc = _first_present(page, sel_list("gmaps", "hero_image"))
    hero_raw = hero_loc.first.get_attribute("src") if hero_loc else None
    hero_base = hero_raw.split("=")[0] if hero_raw else None

    tiles = page.locator(sel("gmaps", "secondary_image"))
    candidates: list[str] = []
    # So trùng theo phần trước dấu "=" (bỏ tham số kích thước), không so nguyên
    # chuỗi src: cùng một ảnh có thể xuất hiện ở 2 ô với kích thước nạp khác nhau
    # (ảnh chưa kịp nạp độ phân giải đầy đủ) -> so nguyên chuỗi lọt qua trùng lặp
    # (đã gặp: 2 ô secondary trả về y hệt nhau sau khi upgrade_image_url).
    seen_bases: set[str] = {hero_base} if hero_base else set()
    for i in range(tiles.count()):
        src = tiles.nth(i).get_attribute("src") or ""
        # Bỏ ảnh Street View (googleapis.com/v1/thumbnail).
        if "googleusercontent.com" not in src:
            continue
        base = src.split("=")[0]
        if base in seen_bases:
            continue
        seen_bases.add(base)
        candidates.append(src)

    return {
        "hero": upgrade_image_url(hero_raw, size) if hero_raw else None,
        "secondary": [
            upgrade_image_url(u, size)
            for u in candidates[: cfg["secondary_photo_count"]]
        ],
    }


def menu_photos(page: Page) -> dict[str, Any]:
    """Ảnh trong mục thực đơn của gallery.

    Nhiều quán nhỏ không có mục "Thực đơn" -> lùi dần theo
    MENU_CATEGORY_PREFERENCE và ghi lại đã dùng mục nào.
    """
    cfg = settings()["gmaps"]
    out: dict[str, Any] = {"images": [], "category_used": None, "categories_seen": []}

    # Nút mở gallery chỉ có ở tab Tổng quan. Nếu vừa đi lấy review thì ta đang ở
    # tab khác -> phải quay lại trước.
    overview = page.locator(sel("gmaps", "tab_overview"))
    if overview.count():
        try:
            overview.first.click(timeout=8000)
            page.wait_for_timeout(2500)
        except Exception:
            pass

    button = _first_present(page, sel_list("gmaps", "photos_button"))
    if button is None:
        out["error"] = "Không tìm thấy nút mở gallery ảnh"
        return out
    _click_retrying(button)
    page.wait_for_timeout(3000)

    chips = _first_present(page, sel_list("gmaps", "photo_category"))
    if chips is None:
        out["error"] = "Gallery mở nhưng không thấy mục phân loại ảnh"
        return out

    # Nhãn mục nằm ở aria-label HOẶC innerText tuỳ bố cục: quán nhỏ hiện chữ,
    # nhà hàng lớn dùng nút biểu tượng chỉ có aria-label. Đọc thiếu một trong hai
    # sẽ kết luận nhầm là "không có mục Thực đơn". Ngoài ra nhãn còn render lười,
    # nên phải chờ chúng hiện ra.
    def read_labels() -> list[str]:
        out_labels = []
        for i in range(chips.count()):
            chip = chips.nth(i)
            label = (chip.get_attribute("aria-label") or "").strip()
            out_labels.append(label or chip.inner_text().strip())
        return out_labels

    try:
        wait_until(
            lambda: any(read_labels()),
            timeout=15.0,
            what="nhãn các mục ảnh hiện ra",
        )
    except TimeoutError:
        pass
    labels = wait_stable(read_labels, stable_seconds=1.5, timeout=20.0, what="danh sách mục ảnh")
    out["categories_seen"] = labels

    target = None
    for wanted in MENU_CATEGORY_PREFERENCE:
        for idx, label in enumerate(labels):
            if wanted.lower() in label.lower():
                target, out["category_used"] = idx, label
                break
        if target is not None:
            break

    if target is None:
        out["error"] = (
            "Không có mục thực đơn. Các mục hiện có: " + ", ".join(labels)
        )
        return out

    chips.nth(target).click()
    page.wait_for_timeout(2500)

    out["images"] = _collect_gallery_images(page, cfg["max_menu_images"], cfg["image_size"])
    return out


# Ảnh trong gallery KHÔNG phải <img src> mà là CSS background-image trên
# div[role='img'] bên trong mỗi a[data-photo-index], và nạp lười theo cuộn.
_GALLERY_URLS_JS = """
(tileCss) => [...document.querySelectorAll(tileCss)].map(a => {
    const box = a.querySelector("div[role='img']") || a;
    const m = getComputedStyle(box).backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
    return m ? m[1] : null;
}).filter(u => u && u.includes('googleusercontent'))
"""


def _collect_gallery_images(page: Page, limit: int, size: int) -> list[str]:
    """Cuộn gallery và gom URL ảnh tới khi đủ `limit` hoặc không còn ảnh mới."""
    tile_css = sel("gmaps", "gallery_tile")
    seen: list[str] = []
    stagnant = 0

    while len(seen) < limit and stagnant < 3:
        before = len(seen)
        for url in page.evaluate(_GALLERY_URLS_JS, tile_css):
            upgraded = upgrade_image_url(url, size)
            if upgraded not in seen:
                seen.append(upgraded)
            if len(seen) >= limit:
                break

        stagnant = stagnant + 1 if len(seen) == before else 0
        # Cuộn trong lưới ảnh để kích hoạt nạp lười.
        tiles = page.locator(tile_css)
        if tiles.count():
            try:
                tiles.nth(tiles.count() - 1).scroll_into_view_if_needed(timeout=4000)
            except Exception:
                page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1400)

    return seen[:limit]


# -- Bài đánh giá ----------------------------------------------------------


def _open_reviews_tab(page: Page) -> None:
    tab = page.locator(sel("gmaps", "tab_reviews"))
    if tab.count() == 0:
        # ĐỪNG đoán bừa theo vị trí (nth(1)): một số quán không có tab "Bài
        # đánh giá" riêng mà có tab KHÁC nằm đúng vị trí đó (đã gặp: "wRRRap!"
        # có Tổng quan/Thực đơn/Giới thiệu, không có Bài đánh giá -> nth(1) bấm
        # nhầm sang "Thực đơn", điều hướng sang layout khác để lại overlay chặn
        # click, hỏng lây cả bước lấy ảnh thực đơn ngay sau đó vì không click
        # lại được tab Tổng quan). Chỉ chọn tab có nhãn chứa "đánh giá"; không
        # có thì bỏ cuộc ngay, đừng đụng vào tab nào khác.
        tab = None
        all_tabs = page.locator(sel("gmaps", "tab"))
        for i in range(all_tabs.count()):
            label = all_tabs.nth(i).get_attribute("aria-label") or ""
            if "đánh giá" in label.lower():
                tab = all_tabs.nth(i)
                break
        if tab is None:
            raise RuntimeError("Không tìm thấy tab 'Bài đánh giá'")
    tab.first.click()
    page.wait_for_selector(sel("gmaps", "review_card"), timeout=30_000)
    human_delay()


def _set_sort(page: Page, index: int) -> None:
    page.locator(sel("gmaps", "sort_button")).first.click()
    page.wait_for_selector(sel("gmaps", "sort_option"), timeout=15_000)
    page.locator(sel("gmaps", "sort_option")).nth(index).click()
    page.wait_for_timeout(3000)


def _expand_all(page: Page) -> None:
    """Bung các bài đánh giá bị cắt bằng nút 'Xem thêm'.

    Click xong thì nút biến mất khỏi DOM (không phải ẩn/disable) — locator co
    lại ngay lập tức. Trước đây duyệt bằng index cố định (`nth(i)`) trên
    locator sống nên mỗi lần click làm dịch chỉ số phần tử còn lại, bỏ sót
    gần một nửa số nút và để lại review cắt cụt "…".

    Duyệt bằng `idx` thay vì luôn `.first`: click thành công thì nút đó biến
    mất nên các nút sau tự dịch xuống — giữ nguyên `idx` để bắt đúng nút kế
    tiếp. Click lỗi (thường do chưa cuộn vào khung nhìn) thì tăng `idx` để
    thử nút khác thay vì bỏ cuộc luôn — nút đầu kẹt không được để chặn các
    nút còn lại phía sau.
    """
    more = page.locator(sel("gmaps", "review_more_button"))
    idx = 0
    for _ in range(40):
        if idx >= more.count():
            break
        btn = more.nth(idx)
        try:
            btn.scroll_into_view_if_needed(timeout=2000)
            btn.click(timeout=2500)
            page.wait_for_timeout(300)
        except Exception:
            idx += 1  # nút này kẹt, thử nút kế tiếp
    page.wait_for_timeout(600)


def _scroll_reviews(page: Page, rounds: int = 4) -> None:
    pane = page.locator(sel("gmaps", "scroll_pane"))
    if not pane.count():
        return
    box = pane.first.bounding_box()
    if not box:
        return
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(rounds):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1200)


def _parse_reviews(page: Page) -> list[dict[str, Any]]:
    cards = page.locator(sel("gmaps", "review_card"))
    out: list[dict[str, Any]] = []
    for i in range(cards.count()):
        card = cards.nth(i)
        review: dict[str, Any] = {}

        author = card.locator(sel("gmaps", "review_author"))
        review["author"] = author.first.inner_text().strip() if author.count() else None

        stars = card.locator(sel("gmaps", "review_stars"))
        if stars.count():
            label = stars.first.get_attribute("aria-label") or ""
            if m := re.search(r"(\d+)", label):
                review["stars"] = int(m.group(1))

        date = card.locator(sel("gmaps", "review_date"))
        review["date"] = date.first.inner_text().strip() if date.count() else None

        text = card.locator(sel("gmaps", "review_text"))
        review["text"] = text.first.inner_text().strip() if text.count() else ""

        if review.get("stars") is not None:
            out.append(review)
    return out


def _is_truncated(text: str) -> bool:
    """Bài không có nút 'Xem thêm' nhưng Google vẫn tự cắt cụt, kết bằng '…'.

    Đã gặp ở review cũ (4-6 năm): không hề có `review_more_button` trong DOM,
    nên `_expand_all` không có gì để bấm — Google chỉ gửi sẵn bản rút gọn.
    Không có cách nào lấy được phần còn thiếu qua tab đánh giá này.
    """
    return text.rstrip().endswith("…")


def _collect_bucket(page: Page, sort_index: int, keep) -> list[dict[str, Any]]:
    """Lấy các bài đúng khoảng sao, ưu tiên bài CÓ nội dung ĐẦY ĐỦ.

    Bài chỉ chấm sao không viết gì thì vô dụng cho việc gán nhãn, nên đẩy xuống
    cuối — vẫn giữ lại để lấp đủ quota nếu quán quá ít bài. Bài bị Google tự
    cắt cụt (không có nút bung) cũng đẩy xuống dưới bài đầy đủ vì cùng lý do,
    nhưng vẫn ưu tiên hơn bài trống hẳn.
    """
    _set_sort(page, sort_index)
    _scroll_reviews(page)
    _expand_all(page)
    matching = [r for r in _parse_reviews(page) if keep(r["stars"])]
    full_text = [r for r in matching if r["text"].strip() and not _is_truncated(r["text"])]
    truncated = [r for r in matching if r["text"].strip() and _is_truncated(r["text"])]
    without_text = [r for r in matching if not r["text"].strip()]
    return full_text + truncated + without_text


def reviews(page: Page) -> dict[str, Any]:
    """5 bài tích cực (4–5★) và 5 bài tiêu cực (1–2★).

    Quán ít bài chê có thể không đủ 5 — trả về số có được kèm cảnh báo, không fail.
    """
    cfg = settings()["gmaps"]
    n = cfg["reviews_per_bucket"]

    try:
        _open_reviews_tab(page)
    except Exception:
        # Một số quán không có tab "Bài đánh giá" riêng (review nằm lồng trong
        # Tổng quan) -> nth(1) đoán nhầm sang tab khác rồi chờ review_card mãi
        # không thấy. Đừng để mất trắng address/hours/photos đã lấy được vì
        # phần đánh giá không mở được.
        return {"positive": [], "negative": [], "note": "không mở được tab đánh giá"}

    positive = _collect_bucket(
        page, SORT_HIGHEST, lambda s: s >= cfg["positive_min_stars"]
    )[:n]
    negative = _collect_bucket(
        page, SORT_LOWEST, lambda s: s <= cfg["negative_max_stars"]
    )[:n]

    result: dict[str, Any] = {"positive": positive, "negative": negative}
    notes = []
    if len(positive) < n:
        notes.append(f"chỉ tìm được {len(positive)}/{n} bài tích cực")
    if len(negative) < n:
        notes.append(f"chỉ tìm được {len(negative)}/{n} bài tiêu cực")
    if notes:
        result["note"] = "; ".join(notes)
    return result
