"""Ánh xạ dữ liệu đã thu thập sang đúng schema 73 cột của dataset.

Đây là hình thái output CHÍNH THỨC. `data.json` chỉ là bản ghi trung gian để
checkpoint; file TSV sinh ra từ đây mới là thứ đưa vào dataset.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Any

from .models import POIRecord

# Thứ tự cột PHẢI khớp tuyệt đối với dataset. Đừng sắp xếp lại.
COLUMNS = [
    "poi_id", "category_l1", "name", "name_en", "category_l2", "tags",
    "cuisine_type", "must_try_dishes", "menu", "price_per_person_avg",
    "seating_capacity", "dietary_options", "reservation_required", "dress_code",
    "alcohol_served", "view_type", "lat", "long", "old_address", "address",
    "ward", "city", "region", "place_id", "distance_from_reference_km",
    "reference_point", "open_time", "close_time", "phone", "contact",
    "operating_note", "price_min", "price_max", "price_level", "booking_required",
    "booking_source", "rating_score", "review_count", "rating_source",
    "cover_image_url", "gallery_urls", "positive_comments", "negative_comments",
    "description_short", "description_long", "best_time_to_visit",
    "estimated_duration", "suitable_for", "not_suitable_for", "insider_tips",
    "source_url", "video_posted_date", "verified_date", "confidence_level",
    "info_expiry_note", "nearby_poi_ids", "complementary_poi_ids",
    "alternative_poi_ids", "weather_dependency", "crowd_level_note",
    "matched_intents", "search_keywords", "nearby_hotel_ids", "status",
    "labeled_by", "review_status", "reviewer_note", "last_updated", "by_pass",
    "dest", "raw_url", "raw_cover_image_url", "raw_gallery_urls",
]

# Tra cứu O(1) cho apply_overrides — chặn khoá lạ trước khi nó đẻ ra cột thứ 74.
_COLUMN_SET = frozenset(COLUMNS)

# Số URL trong cột raw_gallery_urls. Đây là quy ước của DATASET (đúng 3 ảnh phụ),
# không phải tham số cào — nên nó nằm ở tầng xuất chứ không ở [gmaps] settings,
# và giao diện tick chọn ảnh cũng chặn đúng con số này.
GALLERY_URLS_COUNT = 3

# Tỉnh/thành -> vùng. Chỉ cần cho các tỉnh đang gán nhãn; thiếu thì để trống
# chứ không đoán bừa.
REGION_BY_CITY = {
    "khánh hòa": "Nam Trung Bộ",
    "khánh hoà": "Nam Trung Bộ",
    "phú yên": "Nam Trung Bộ",
    "ninh thuận": "Nam Trung Bộ",
    "bình thuận": "Nam Trung Bộ",
    "bình định": "Nam Trung Bộ",
    "quảng ngãi": "Nam Trung Bộ",
    "quảng nam": "Nam Trung Bộ",
    "đà nẵng": "Nam Trung Bộ",
    "thừa thiên huế": "Bắc Trung Bộ",
    "huế": "Bắc Trung Bộ",
    "quảng trị": "Bắc Trung Bộ",
    "quảng bình": "Bắc Trung Bộ",
    "hà tĩnh": "Bắc Trung Bộ",
    "nghệ an": "Bắc Trung Bộ",
    "thanh hóa": "Bắc Trung Bộ",
    "hà nội": "Đồng bằng sông Hồng",
    "hải phòng": "Đồng bằng sông Hồng",
    "quảng ninh": "Đồng bằng sông Hồng",
    "hồ chí minh": "Đông Nam Bộ",
    "bà rịa - vũng tàu": "Đông Nam Bộ",
    "đồng nai": "Đông Nam Bộ",
    "lâm đồng": "Tây Nguyên",
    "đắk lắk": "Tây Nguyên",
    "gia lai": "Tây Nguyên",
    "kon tum": "Tây Nguyên",
    "cần thơ": "Đồng bằng sông Cửu Long",
    "kiên giang": "Đồng bằng sông Cửu Long",
}

# Ngưỡng phân loại mức giá theo chi phí trung bình mỗi người (VNĐ).
PRICE_LEVELS = [(150_000, "budget"), (500_000, "mid-range"), (float("inf"), "luxury")]

_NUMBER = re.compile(r"[\d][\d.,]*")


# -- Tiện ích định dạng ----------------------------------------------------


# Gemini không nhất quán: có lúc ngăn bằng phẩy, có lúc xuống dòng, chấm phẩy
# hoặc gạch đầu dòng. Tách hết rồi ghép lại bằng ", " cho đúng quy ước dataset.
_LIST_SEPARATORS = re.compile(r"[,;\n•]+|(?:^|\n)\s*[-*]\s+")


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        parts = _LIST_SEPARATORS.split(str(value))
    return [p.strip(" .-–—\t") for p in parts if p and p.strip(" .-–—\t")]


def join_list(value: Any) -> str:
    return ", ".join(as_list(value))


def parse_amount(text: Any) -> int | None:
    """'35.000 VNĐ' -> 35000, '100,000' -> 100000, '150' (nghìn) -> 150000."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = _NUMBER.search(str(text))
    if not m:
        return None
    raw = m.group(0).rstrip(".,")
    digits = re.sub(r"[.,]", "", raw)
    if not digits.isdigit():
        return None
    amount = int(digits)
    # "35 nghìn" / "35k" -> 35.000. Số đã đủ lớn thì giữ nguyên.
    return amount * 1000 if amount < 1000 else amount


def menu_prices(text: Any) -> list[int]:
    """Mọi mức giá trong một ô giá. '120 - 155' -> [120000, 155000].

    Phải tách từng số một: gộp hết chữ số lại thì '120 - 155' thành 120.155.000đ.
    """
    if text is None:
        return []
    return [int(n) * 1000 for n in re.findall(r"\d+", str(text))]


def parse_menu_price(text: Any) -> int | None:
    """Giá đại diện của một món — cận TRÊN nếu là khoảng giá.

    Giá thực đơn luôn tính theo nghìn: '150' = 150.000, '1700' = 1.700.000.
    Không dùng chung parse_amount: ngưỡng "số nhỏ thì nhân 1000" ở đó sẽ khiến
    món 1700 (1,7 triệu) bị coi là rẻ hơn món 40 (40.000).
    """
    prices = menu_prices(text)
    return max(prices) if prices else None


def first_number(text: Any) -> str:
    """'80 - 100 thực khách' -> '80'. Dataset chỉ ghi con số trần."""
    if text is None:
        return ""
    m = re.search(r"\d+", str(text))
    return m.group(0) if m else ""


def money(amount: int | None) -> str:
    return f"{amount:,}" if amount is not None else ""


def boolean(value: Any) -> str:
    """Chuẩn hoá về TRUE/FALSE như dataset đang dùng."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    text = str(value).strip().lower()
    if text in {"true", "yes", "có", "co", "cần", "can", "bắt buộc", "1"}:
        return "TRUE"
    if text in {"false", "no", "không", "khong", "0", "không cần", "khong can"}:
        return "FALSE"
    return "TRUE" if text.startswith("có") else "FALSE"


def quoted_comments(reviews: list[dict[str, Any]], limit: int = 5) -> str:
    """Ghép bình luận theo dạng dataset: mỗi bình luận là một đoạn văn riêng.

    Ngăn cách giữa các bình luận bằng MỘT dòng mới, không bọc nháy kép
    (csv.DictWriter tự quote cả field nếu nó chứa newline, theo RFC4180).
    XUỐNG DÒNG BÊN TRONG một bình luận (review gốc nhiều đoạn) bị gộp lại
    thành khoảng trắng — chỉ ranh giới GIỮA hai bình luận mới được xuống dòng,
    để không hiểu nhầm 1 review nhiều đoạn thành nhiều review riêng biệt. Cắt
    trần ở `limit` ngay tại tầng xuất: bài không có nội dung bị bỏ qua, nên
    nếu chỉ dựa vào hạn mức lúc thu thập thì số câu thực sự ra file lại không
    kiểm soát được. Ít hơn `limit` là bình thường — quán ít bài chê thì thôi.
    """
    parts = []
    for review in reviews:
        text = " ".join((review.get("text") or "").split())
        if text:
            parts.append(text)
        if len(parts) >= limit:
            break
    return "\n".join(parts)


def slug_dest(city: str | None, address: str | None) -> str:
    """'Nha Trang' -> 'thanh_pho_nha_trang'."""
    source = ""
    for candidate in (address or "", city or ""):
        if "nha trang" in candidate.lower():
            source = "Nha Trang"
            break
    if not source:
        source = (city or "").strip()
    if not source:
        return ""
    text = source.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return f"thanh_pho_{text}" if text else ""


# Dataset viết dấu theo kiểu "oà" chứ không phải "òa". Chuẩn hoá để cùng một
# tỉnh không sinh ra hai biến thể chuỗi khác nhau trong dataset.
CITY_SPELLING = {
    "khánh hòa": "Khánh Hoà",
    "thanh hóa": "Thanh Hoá",
    "hòa bình": "Hoà Bình",
}


def clean_address(address: str | None) -> str:
    """Bỏ đuôi ', Việt Nam' và mã bưu chính cho khớp cách ghi của dataset."""
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    parts = [p for p in parts if p.lower() not in {"việt nam", "vietnam"}]
    parts = [re.sub(r"\s*\d{5,6}\s*$", "", p).strip() for p in parts]
    parts = [normalize_city(p) for p in parts]
    return ", ".join(p for p in parts if p)


def normalize_city(city: str) -> str:
    return CITY_SPELLING.get(city.strip().lower(), city.strip())


def _plain(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def merged_ward(address: str, google_ward: str, ward_map: dict[str, str]) -> str:
    """Tên phường SAU sáp nhập 2025.

    Google Maps vẫn trả tên phường cũ (hoặc bỏ trống). Không có cách nào suy ra
    tên mới từ dữ liệu Google, nên tra bảng khai báo tay trong settings.toml —
    khớp theo tên phường cũ trước, không được thì theo tên đường.
    """
    if not ward_map:
        return google_ward

    lookup = {_plain(k): v for k, v in ward_map.items()}
    if hit := lookup.get(_plain(google_ward)):
        return hit
    haystack = _plain(address)
    for key, value in lookup.items():
        if key and key in haystack:
            return value
    return google_ward


def split_address(address: str | None) -> dict[str, str]:
    """Tách 'X, Ward, City, Việt Nam' thành ward / city / region.

    Bỏ phần đuôi 'Việt Nam' và mã bưu chính; hai đoạn cuối còn lại là
    phường/khu vực và tỉnh/thành.
    """
    out = {"ward": "", "city": "", "region": ""}
    if not address:
        return out

    parts = [p.strip() for p in address.split(",") if p.strip()]
    parts = [p for p in parts if p.lower() not in {"việt nam", "vietnam"}]
    if not parts:
        return out

    # Mã bưu chính hay dính vào tên tỉnh: "Khánh Hòa 650000".
    city = normalize_city(re.sub(r"\s*\d{5,6}\s*$", "", parts[-1]))
    out["city"] = city
    if len(parts) >= 2:
        out["ward"] = parts[-2]
    out["region"] = REGION_BY_CITY.get(city.lower(), "")
    return out


def price_level_for(avg: int | None) -> str:
    if avg is None:
        return ""
    for ceiling, label in PRICE_LEVELS:
        if avg <= ceiling:
            return label
    return ""


def single_price(gia: Any) -> str:
    """Gộp giá về MỘT số: '25 - 28' -> '25'.

    Lấy cận dưới (giá khởi điểm) vì đó là mức giá thực khách gặp đầu tiên và là
    cách ghi thông dụng của thực đơn.
    """
    numbers = re.findall(r"\d+", str(gia or ""))
    return numbers[0] if numbers else str(gia or "")


# Gemini thỉnh thoảng phớt lờ chỉ dẫn "số trần theo nghìn" và trả giá đầy đủ
# VNĐ có dấu phẩy ngăn nghìn ("129,000" thay vì "129"). Không quy đổi trước thì
# regex tách số sẽ đọc "129,000" thành HAI số [129, 0] và làm hỏng price_min.
_COMMA_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")


def degroup_thousands(text: Any) -> str:
    """'129,000' -> '129'; '1,100,000' -> '1100'. Số không có dấu phẩy giữ nguyên."""
    return _COMMA_GROUPED.sub(
        lambda m: str(int(m.group(0).replace(",", "")) // 1000), str(text or "")
    )


# Gemini có một mẫu trích xuất thực đơn CỐ ĐỊNH tự kích hoạt cho tác vụ dạng
# này — đã kiểm chứng lặp lại Y HỆT (name/description/price/category, "price"
# là SỐ nguyên đầy đủ VNĐ) dù prompt yêu cầu rõ ràng đúng 3 khoá
# loai_thuc_pham/ten/gia (xem FIELD_ALIASES trong models.py — cùng hiện tượng
# với hồ sơ POI). Không phải lỗi ngẫu nhiên mà là template nội bộ không đổi
# được bằng prompt, nên ánh xạ lại thay vì tiếp tục sửa câu chữ prompt.
_MENU_NAME_ALIASES = ("ten", "name", "mon", "ten_mon", "item", "item_name")
_MENU_CATEGORY_ALIASES = ("loai_thuc_pham", "category", "loai", "nhom", "section")


def _normalize_menu_item(item: dict) -> dict:
    ten = next((item[k] for k in _MENU_NAME_ALIASES if item.get(k)), "")
    loai = next((item[k] for k in _MENU_CATEGORY_ALIASES if item.get(k)), "")

    gia = item.get("gia")
    if not gia:
        price = item.get("price")
        if isinstance(price, (int, float)):
            # Mẫu thay thế của Gemini ghi "price" là SỐ nguyên đầy đủ VNĐ
            # (165000), không phải chuỗi theo đơn vị nghìn như "gia" — quy đổi
            # để khớp quy ước dataset (menu_prices() luôn nhân 1000 khi đọc lại).
            gia = str(round(price / 1000))
        elif price:
            gia = price
        else:
            gia = ""

    return {"loai_thuc_pham": loai, "ten": ten, "gia": gia}


def menu_json(record: POIRecord) -> str:
    """Lấy khối JSON thực đơn Gemini trả về, chuẩn hoá lại cho gọn.

    Gemini hay bọc JSON trong ```json ... ``` kèm câu dẫn — cắt lấy đúng mảng.
    """
    raw = ((record.menu or {}).get("extracted") or {}).get("_raw") or ""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return ""
    try:
        items = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return raw[start : end + 1]

    normalized = [_normalize_menu_item(i) for i in items if isinstance(i, dict)]
    # Mỗi món chỉ giữ MỘT mức giá: "25 - 28" -> "25". Quy đổi số có dấu phẩy về
    # dạng nghìn trước, nếu không "1,100,000" sẽ bị đọc thành "1".
    for item in normalized:
        item["gia"] = single_price(degroup_thousands(item["gia"]))
    # Indent 2 để dễ đọc/sửa tay khi mở ô này lên — ô sẽ trải nhiều dòng vật lý
    # trong row.tsv, nhưng vẫn là MỘT ô/MỘT bản ghi vì được bọc nháy kép theo
    # RFC4180 (csv.DictWriter tự làm việc này khi field chứa newline).
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def menu_price_range(menu_text: str) -> tuple[int | None, int | None]:
    """Giá thấp nhất / cao nhất trong thực đơn.

    Giá có thể là khoảng ('80-90') -> lấy cận dưới cho min, cận trên cho max.
    """
    if not menu_text:
        return None, None
    try:
        items = json.loads(menu_text)
    except json.JSONDecodeError:
        return None, None

    lows, highs = [], []
    for item in items:
        if not isinstance(item, dict):
            continue
        numbers = menu_prices(item.get("gia"))
        if numbers:
            lows.append(min(numbers))
            highs.append(max(numbers))
    return (min(lows) if lows else None, max(highs) if highs else None)


# -- Suy luận các trường Gemini không cho -----------------------------------

# Mục thực đơn hay chứa món đặc trưng của quán, theo thứ tự ưu tiên.
SIGNATURE_MENU_SECTIONS = ["đặc biệt", "đặc sản", "món tủ", "signature", "best seller"]

# Dấu hiệu quán có bán đồ uống có cồn.
ALCOHOL_HINTS = ["bia", "rượu", "beer", "wine", "cocktail", "nhậu", "lẩu"]


def name_without_diacritics(name: str) -> str:
    text = name.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


# Gemini hay trả "không có", "N/A" thay vì bỏ trống.
_NO_VALUE = {"", "khong co", "khong", "khong ro", "n/a", "na", "none", "null", "-", "--"}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _plain(text))


def english_name(candidate: Any, vietnamese_name: str) -> str:
    """Tên tiếng Anh THẬT của quán, không có thì trả chuỗi rỗng.

    "Cà Phê Hoa Mộc Lan" -> "Ca phe Hoa Moc Lan" chỉ là bỏ dấu, KHÔNG phải tên
    tiếng Anh; dataset cần để trống chứ không nhận bản phiên âm đó. Chỉ giữ lại
    khi chuỗi không dấu và khác hẳn tên quán.
    """
    text = str(candidate or "").strip().strip('"').strip()
    if _plain(text) in _NO_VALUE:
        return ""
    # Còn dấu tiếng Việt -> vẫn là tên tiếng Việt.
    if text != name_without_diacritics(text):
        return ""
    if _squash(text) == _squash(vietnamese_name):
        return ""
    return text


def signature_dishes(menu_text: str, limit: int = 4) -> list[str]:
    """Món nên thử: ưu tiên mục 'Đặc biệt', không có thì lấy các món đắt nhất."""
    if not menu_text:
        return []
    try:
        items = [i for i in json.loads(menu_text) if isinstance(i, dict) and i.get("ten")]
    except json.JSONDecodeError:
        return []

    for section in SIGNATURE_MENU_SECTIONS:
        picked = [i["ten"] for i in items if section in str(i.get("loai_thuc_pham", "")).lower()]
        if picked:
            return picked[:limit]

    # Không có mục đặc biệt: món đắt nhất thường là món chủ lực.
    ranked = sorted(items, key=lambda i: parse_menu_price(i.get("gia")) or 0, reverse=True)
    return [i["ten"] for i in ranked[:limit]]


def _category_cfg() -> dict[str, Any]:
    from .config import settings

    return settings().get("category", {})


def _has_keyword(text: str, keyword: str) -> bool:
    """Khớp theo RANH GIỚI TỪ, không phải chuỗi con.

    Khớp chuỗi con cho dương tính giả rất khó thấy: "pub" nằm trong
    "gastropub", "bar" nằm trong "barbecue"/"bar-b-q". Cả hai đều đẩy quán ăn
    sang nhóm "Quán Bar" trong im lặng.
    """
    return re.search(rf"\b{re.escape(_plain(keyword))}\b", _plain(text)) is not None


def classify_l1(category_raw: str) -> tuple[str, bool]:
    """Nhãn ngành Google -> (category_l1, có_chắc_chắn_không).

    CHỈ xét nhãn ngành của Google, KHÔNG xét tên quán: "Nhà hàng - Khách sạn
    Yasaka" có chữ "khách sạn" trong tên nhưng vẫn là chỗ ăn, lấy tên vào so
    khớp là tự tạo dương tính giả.

    Fail-open có chủ ý: không đọc được nhãn -> ("FOOD", False). Chặn nhầm một
    quán thật chỉ để lại dòng stub mà người gán nhãn khó nhận ra; ngược lại một
    khách sạn lọt qua sẽ lộ ngay (không menu, dữ liệu vô nghĩa).
    """
    cfg = _category_cfg()
    food = cfg.get("l1_default", "FOOD")
    if not _plain(category_raw):
        return food, False
    for marker in cfg.get("non_food_markers", []):
        # Ranh giới từ, không phải chuỗi con: "spa" nằm trong "spaghetti" —
        # khớp chuỗi con sẽ biến quán mì Ý thành dòng stub trong im lặng.
        if _has_keyword(category_raw, marker):
            return "OTHER", True
    return food, True


def normalize_l2(value: Any, category_raw: str = "", name: str = "") -> str:
    """Chốt category_l2 về ĐÚNG một trong các nhãn hợp lệ ở [category].l2_values.

    Ưu tiên giá trị Gemini trả về, nhưng chỉ khi nó khớp một nhãn hợp lệ — so
    khớp bỏ dấu, không phân biệt hoa/thường, và trả về CÁCH VIẾT CHUẨN trong
    config chứ không theo cách Gemini gõ (cùng cách `_plausible_ward` xử lý
    `old_wards`). Giá trị lạ không bao giờ được nhả ra cột.

    Gemini không trả hoặc trả bậy thì suy từ nhãn ngành Google + tên quán qua
    [[category.l2_hints]]; cùng đường thì lấy l2_fallback.
    """
    cfg = _category_cfg()
    canonical = {_plain(v): v for v in cfg.get("l2_values", [])}

    # Thử cả chuỗi trước, rồi từng phần nếu Gemini trả kiểu "Quán ăn, Nhà hàng".
    for candidate in [value, *as_list(value)]:
        if isinstance(candidate, str) and (hit := canonical.get(_plain(candidate))):
            return hit

    # Nhãn ngành Google xét RIÊNG và xét TRƯỚC tên quán. Gộp chung hai nguồn vào
    # một chuỗi thì thứ tự khai báo hint quyết định thay vì độ tin cậy của nguồn:
    # "ZAVOD restaurant & gastropub" từng ra "Quán Bar" vì hint bar đứng trước
    # hint nhà hàng, dù nhãn Google mới là thứ đáng tin.
    hints = cfg.get("l2_hints", [])
    for source in (category_raw, name):
        for hint in hints:
            if any(_has_keyword(source, k) for k in hint.get("keywords", [])):
                return hint["value"]

    return cfg.get("l2_fallback", "")


def derive_missing(profile: dict[str, Any], record: POIRecord) -> dict[str, Any]:
    """Suy các trường còn thiếu từ dữ liệu đã có, thay vì để trống."""
    out: dict[str, Any] = {}
    name = (record.google_maps or {}).get("name") or record.poi_name
    menu_text = menu_json(record)

    # KHÔNG suy name_en ở đây: chỉ nhận tên tiếng Anh thật, lọc ở english_name.
    # category_l2 cũng không suy ở đây mà ở normalize_l2 — nó cần nhãn ngành
    # Google (`category_raw`), thứ mà derive_missing không nhận vào.

    if dishes := signature_dishes(menu_text):
        out["must_try_dishes"] = dishes

    # Có bia/rượu/lẩu trong thực đơn hoặc tag "quán nhậu" -> có phục vụ đồ uống có cồn.
    haystack = (menu_text + " " + join_list(profile.get("tags"))).lower()
    if any(hint in haystack for hint in ALCOHOL_HINTS):
        out["alcohol_served"] = "có"

    # Quán bình dân gần như không cần đặt bàn.
    avg = parse_amount(profile.get("price_per_person_avg"))
    if avg is not None:
        out["reservation_required"] = "không" if avg <= 150_000 else "có"

    return out


# -- Dựng dòng dữ liệu -----------------------------------------------------


def pick_video(record: POIRecord, tiktok_index: int = 0) -> dict[str, Any]:
    """Chọn video sẽ ghi vào `raw_url`, hoặc {} nếu không có gì đáng tin.

    Ba mức, theo đúng thứ tự:

    1. Ứng viên TikTok đạt ngưỡng tin cậy — nguồn chính.
    2. Người dùng chỉ định tay (`--tiktok N`) — luôn tôn trọng, kể cả dưới ngưỡng:
       họ đã tự nhìn danh sách rồi.
    3. Reel của Trang Facebook ĐÃ XÁC MINH ĐỊA CHỈ — dự phòng. Trang khớp địa chỉ
       Google thì video của nó đúng quán theo định nghĩa, nên còn đáng tin hơn một
       ứng viên TikTok điểm thấp.

    Không mức nào đạt thì trả {} và cột để TRỐNG. Ghi bừa ứng viên tốt nhất là
    cách cũ, và đo trên 119 POI thì hơn một phần ba số dòng không có cơ sở nào
    để tin — dữ liệu sai lặng lẽ còn tệ hơn ô trống.
    """
    from .config import settings

    candidates = record.tiktok or []
    if not (0 <= tiktok_index < len(candidates)):
        candidates = []

    if candidates:
        picked = candidates[tiktok_index]
        # Chọn tay thì bỏ qua ngưỡng; data.json cũ chưa có `score` cũng vậy.
        if tiktok_index != 0 or "score" not in picked:
            return picked
        if picked.get("score", 0.0) >= settings()["tiktok"]["confidence_threshold"]:
            return picked

    fb = getattr(record, "facebook", None) or {}
    if fb.get("verified"):
        reels = fb.get("reels") or []
        if reels:
            return {"url": reels[0].get("url", ""), "posted_at": None}
    return {}


def apply_overrides(row: dict[str, str], record: POIRecord) -> dict[str, str]:
    """Áp phần sửa tay lên dòng vừa dựng. Gọi CUỐI CÙNG, ngay trước khi trả về.

    Đây là điều kiện để người gán nhãn dám sửa tay: sửa xong chạy lại `--only maps`
    (vá ảnh thực đơn chẳng hạn) KHÔNG được xoá mất chỗ vừa sửa. Vì `overrides` nằm
    trong data.json chứ không nằm trong row.tsv, xuất lại bao nhiêu lần cũng ra
    cùng kết quả.

    Chỉ nhận khoá thuộc COLUMNS — khoá lạ (đổi tên cột, gõ sai) bị bỏ qua chứ
    không lặng lẽ đẻ thêm cột thứ 74 làm lệch cả file TSV.
    """
    overrides = getattr(record, "overrides", None) or {}
    for col, value in overrides.items():
        if col in _COLUMN_SET:
            row[col] = "" if value is None else str(value)
    return row


def build_row(
    record: POIRecord,
    defaults: dict[str, Any],
    tiktok_index: int = 0,
    ward_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ánh xạ một POIRecord sang đúng 73 cột của dataset."""
    maps_raw = record.google_maps or {}

    # POI không thuộc nhóm đồ ăn: dòng stub CHỈ có `name` + `category_l1`, mọi
    # cột khác để trống (kể cả status/labeled_by/last_updated). Dataset vẫn có
    # một dòng để biết POI này đã được kiểm tra và loại, thay vì im lặng biến
    # mất. Đọc `record.category_l1` trước, lùi về defaults cho data.json cũ
    # chưa có khoá này -> không POI cũ nào bỗng dưng thành stub.
    l1 = getattr(record, "category_l1", "") or defaults.get("category_l1", "FOOD")
    if l1 != "FOOD":
        stub = {col: "" for col in COLUMNS}
        stub["category_l1"] = l1
        stub["name"] = maps_raw.get("name") or record.poi_name
        # Áp override cả ở đây: người rà lại có thể muốn sửa ngay trên dòng stub
        # (vd đổi `category_l1` sau khi xác nhận Google xếp ngành nhầm).
        return apply_overrides(stub, record)

    # Suy các trường Gemini không cho. Làm ở đây (không phải lúc chạy bước
    # gemini1) vì must_try_dishes cần thực đơn — chỉ có sau khi bước `menu` xong.
    profile = dict(record.gemini_profile or {})
    for key, value in derive_missing(profile, record).items():
        if not profile.get(key):
            profile[key] = value

    maps = maps_raw
    photos = maps.get("photos") or {}
    reviews = maps.get("reviews") or {}
    hours = (maps.get("hours") or {}).get("by_day") or {}

    ward_map = ward_map or {}
    picked = pick_video(record, tiktok_index)

    raw_address = maps.get("address") or ""
    location = split_address(raw_address)
    # Phường sau sáp nhập: Google trả tên cũ -> tra bảng khai báo tay.
    location["ward"] = merged_ward(raw_address, location["ward"], ward_map)
    address = clean_address(raw_address)
    if location["ward"] and location["ward"] not in address:
        # Ghép lại địa chỉ với tên phường mới, giữ nguyên số nhà + tên đường.
        street = address.split(",")[0].strip()
        address = ", ".join(p for p in [street, location["ward"], location["city"]] if p)

    # Giờ mở/đóng: lấy khung phổ biến nhất trong tuần.
    opens = [d.get("open") for d in hours.values() if d.get("open")]
    closes = [d.get("close") for d in hours.values() if d.get("close")]
    open_time = max(set(opens), key=opens.count) if opens else ""
    close_time = max(set(closes), key=closes.count) if closes else ""

    menu_text = menu_json(record)
    price_min, price_max = menu_price_range(menu_text)
    avg = parse_amount(profile.get("price_per_person_avg"))

    hero = photos.get("hero") or ""
    # Chốt bất biến ở tầng xuất: raw_gallery_urls không được trùng nhau, cũng
    # không được trùng raw_cover_image_url — kể cả khi data.json cũ (scrape từ
    # trước khi gmaps.photos() vá lỗi so trùng theo kích thước ảnh) vẫn còn dữ
    # liệu trùng lặp bên trong.
    def _photo_base(url: str) -> str:
        return url.split("=")[0]

    # Nguồn ảnh gallery mặc định là bể ứng viên thật lấy từ mục "Tất cả"; chỉ lùi
    # về `secondary` cho data.json CŨ chưa có bể đó. `secondary` (img.DaSXdd)
    # thực chất là ảnh bìa của từng MỤC ảnh chứ không phải ảnh phụ của quán, nên
    # nó chỉ là phương án chót. Người gán nhãn tick 3 ảnh ở tab "Ảnh" thì lựa
    # chọn đó nằm trong `overrides` và được áp CUỐI CÙNG, đè lên mặc định này.
    candidates = (maps.get("gallery_candidates") or {}).get("images") or []
    seen_bases = {_photo_base(hero)} if hero else set()
    gallery: list[str] = []
    for url in candidates or (photos.get("secondary") or []):
        base = _photo_base(url)
        if base in seen_bases:
            continue
        seen_bases.add(base)
        gallery.append(url)
    gallery = gallery[:GALLERY_URLS_COUNT]

    row = {
        "poi_id": "",
        "category_l1": l1,
        "name": maps.get("name") or record.poi_name,
        "name_en": english_name(profile.get("name_en"), maps.get("name") or record.poi_name),
        # Bước `maps`/`gemini1` đã chốt sẵn vào record; chạy lại normalize_l2 ở
        # đây để `vsf export` trên data.json CŨ (chưa có khoá này) vẫn ra nhãn
        # đúng chuẩn thay vì cột rỗng.
        "category_l2": getattr(record, "category_l2", "")
        or normalize_l2(
            profile.get("category_l2"),
            maps.get("category_raw", ""),
            maps.get("name") or record.poi_name,
        ),
        "tags": join_list(profile.get("tags")),
        "cuisine_type": join_list(profile.get("cuisine_type")),
        "must_try_dishes": join_list(profile.get("must_try_dishes")),
        "menu": menu_text,
        "price_per_person_avg": money(avg),
        # Để trống — Gemini chỉ đoán được số chỗ ngồi, không tra được.
        "seating_capacity": "",
        "dietary_options": profile.get("dietary_options") or "",
        "reservation_required": boolean(profile.get("reservation_required")),
        "dress_code": (profile.get("dress_code") or "").capitalize(),
        "alcohol_served": boolean(profile.get("alcohol_served")),
        "view_type": profile.get("view_type") or "",
        "lat": str(maps.get("lat") or ""),
        "long": str(maps.get("long") or ""),
        # Địa chỉ Google trả về nguyên trạng — không mất gì khi đổi tên phường.
        # Địa chỉ trước sáp nhập 1/7/2025 — do Gemini trả lời ở bước old_address.
        "old_address": clean_address(maps.get("old_address")),
        "address": address,
        "ward": location["ward"],
        "city": location["city"],
        "region": location["region"],
        "place_id": maps.get("place_id") or "",
        "distance_from_reference_km": "",
        "reference_point": "",
        "open_time": open_time,
        "close_time": close_time,
        # Excel hiểu ="..." là công thức trả về chuỗi văn bản thuần — ép cột
        # thành text nên không mất số 0 đầu, và không giống dấu nháy đơn, cách
        # này không phụ thuộc mở file hay dán trực tiếp vào Excel.
        "phone": f'="{maps["phone"]}"' if maps.get("phone") else "",
        "contact": "",
        "operating_note": profile.get("operating_note") or "",
        "price_min": money(price_min),
        "price_max": money(price_max),
        "price_level": price_level_for(avg),
        "booking_required": boolean(profile.get("reservation_required")),
        "booking_source": defaults.get("booking_source", "internal"),
        "rating_score": str(maps.get("rating") or ""),
        "review_count": str(maps.get("review_count") or ""),
        "rating_source": defaults.get("rating_source", "Google Maps"),
        "cover_image_url": "",
        "gallery_urls": "",
        "positive_comments": quoted_comments(reviews.get("positive") or []),
        "negative_comments": quoted_comments(reviews.get("negative") or []),
        "description_short": profile.get("description_short") or "",
        "description_long": profile.get("description_long") or "",
        "best_time_to_visit": profile.get("best_time_to_visit") or "",
        "estimated_duration": profile.get("estimated_duration") or "",
        "suitable_for": profile.get("suitable_for") or "",
        "not_suitable_for": profile.get("not_suitable_for") or "",
        "insider_tips": profile.get("insider_tips") or "",
        "source_url": "",
        "video_posted_date": (picked.get("posted_at") or "")[:10],
        "verified_date": "",
        # Luôn lấy giá trị mặc định trong settings, KHÔNG dùng mức Gemini tự chấm:
        # nó chấm theo độ chắc chắn của chính nó, không phải độ tin cậy của dòng
        # dữ liệu. Người gán nhãn hạ xuống khi rà lại.
        "confidence_level": defaults.get("confidence_level", ""),
        "info_expiry_note": profile.get("info_expiry_note") or defaults.get("info_expiry_note", ""),
        "nearby_poi_ids": "",
        "complementary_poi_ids": "",
        "alternative_poi_ids": "",
        "weather_dependency": profile.get("weather_dependency") or "",
        "crowd_level_note": profile.get("crowd_level_note") or "",
        "matched_intents": join_list(profile.get("matched_intents")),
        "search_keywords": join_list(profile.get("search_keywords")),
        "nearby_hotel_ids": "",
        "status": defaults.get("status", "active"),
        "labeled_by": defaults.get("labeled_by", ""),
        "review_status": defaults.get("review_status", "draft"),
        "reviewer_note": "",
        "last_updated": date.today().isoformat(),
        "by_pass": "FALSE",
        "dest": slug_dest(location["city"], address),
        # raw_* giữ nguyên dữ liệu thô; cover_image_url/gallery_urls để trống cho
        # khâu xử lý ảnh phía sau điền vào, đúng như dòng mẫu.
        "raw_url": picked.get("url") or "",
        "raw_cover_image_url": hero,
        "raw_gallery_urls": ", ".join(gallery),
    }
    return apply_overrides({col: row.get(col, "") for col in COLUMNS}, record)
