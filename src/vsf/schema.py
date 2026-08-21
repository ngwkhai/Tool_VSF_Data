"""Bộ công cụ DÙNG CHUNG của tầng xuất dữ liệu.

Đây là hình thái output CHÍNH THỨC. `data.json` chỉ là bản ghi trung gian để
checkpoint; file TSV sinh ra từ đây mới là thứ đưa vào dataset.

Bộ CỘT và hàm `build_row` thật sự nằm ở `vsf.profiles.food` / `vsf.profiles.accom`
— mỗi dataset một bộ. File này giữ phần không phụ thuộc dataset (định dạng số,
tách địa chỉ, chuẩn hoá phường, chọn video, áp override) để hai profile dùng
chung thay vì mỗi bên một bản trôi lệch nhau.

CỐ Ý KHÔNG có `COLUMNS` ở đây. Một `COLUMNS` cấp module sẽ là bộ cột của FOOD,
và mọi chỗ lỡ dùng nó cho bản ghi ACCOM sẽ âm thầm cắt còn 73 cột sai tên thay
vì báo lỗi. Muốn lấy cột thì đi qua `profiles.get_profile(record.profile)`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Iterable

from .models import POIRecord

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

# Ba mức của cột price_level. NGƯỠNG thì nằm ở [category].price_levels của từng
# profile, không nằm ở đây: một bữa ăn và một đêm phòng không thể chung thang
# giá (150k/500k của FOOD đem áp cho khách sạn thì mọi POI đều thành "luxury").
PRICE_LEVEL_LABELS = ("budget", "mid-range", "luxury")

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


def price_level_for(avg: int | None, thresholds: Iterable[int]) -> str:
    """Mức giá theo ngưỡng CỦA PROFILE ([category].price_levels).

    `thresholds` là hai trần dưới dạng VNĐ: <= trần đầu là "budget", <= trần sau
    là "mid-range", còn lại "luxury". Bắt truyền tường minh để không có đường
    nào lỡ áp thang giá bữa ăn cho một đêm khách sạn.
    """
    if avg is None:
        return ""
    for ceiling, label in zip(thresholds, PRICE_LEVEL_LABELS):
        if avg <= ceiling:
            return label
    return PRICE_LEVEL_LABELS[-1]


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


def price_table_json(raw: str, normalize: Callable[[dict], dict]) -> str:
    """Khối JSON bảng giá Gemini trả về -> chuỗi JSON đã chuẩn hoá.

    Dùng chung cho THỰC ĐƠN (profile food) và BẢNG GIÁ PHÒNG (profile accom):
    hai thứ khác nhau về tên khoá nhưng giống hệt nhau về cách Gemini gói ghém
    câu trả lời — bọc trong ```json ... ``` kèm câu dẫn, nên phải cắt lấy đúng
    mảng. `normalize` là phần khác nhau: mỗi profile tự ánh xạ tên khoá của mình.

    Mỗi dòng chỉ giữ MỘT mức giá: "25 - 28" -> "25". Quy đổi số có dấu phẩy về
    dạng nghìn TRƯỚC, nếu không "1,100,000" sẽ bị đọc thành "1".

    Indent 2 để dễ đọc/sửa tay khi mở ô này lên — ô sẽ trải nhiều dòng vật lý
    trong row.tsv, nhưng vẫn là MỘT ô/MỘT bản ghi vì được bọc nháy kép theo
    RFC4180 (csv.DictWriter tự làm việc này khi field chứa newline).
    """
    raw = raw or ""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return ""
    try:
        items = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return raw[start : end + 1]

    normalized = [normalize(i) for i in items if isinstance(i, dict)]
    for item in normalized:
        item["gia"] = single_price(degroup_thousands(item["gia"]))
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def price_range(table_text: str) -> tuple[int | None, int | None]:
    """Giá thấp nhất / cao nhất trong một bảng giá đã chuẩn hoá.

    Giá có thể là khoảng ('80-90') -> lấy cận dưới cho min, cận trên cho max.
    Không phụ thuộc tên khoá phân loại, chỉ đọc "gia" — nên dùng được cho cả
    thực đơn lẫn bảng giá phòng.
    """
    if not table_text:
        return None, None
    try:
        items = json.loads(table_text)
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


def _has_keyword(text: str, keyword: str) -> bool:
    """Khớp theo RANH GIỚI TỪ, không phải chuỗi con.

    Khớp chuỗi con cho dương tính giả rất khó thấy: "pub" nằm trong
    "gastropub", "bar" nằm trong "barbecue"/"bar-b-q". Cả hai đều đẩy quán ăn
    sang nhóm "Quán Bar" trong im lặng.
    """
    return re.search(rf"\b{re.escape(_plain(keyword))}\b", _plain(text)) is not None


def classify_l1(category_raw: str, cfg: dict[str, Any]) -> tuple[str, bool]:
    """Nhãn ngành Google -> (category_l1, có_chắc_chắn_không).

    CHỈ xét nhãn ngành của Google, KHÔNG xét tên quán: "Nhà hàng - Khách sạn
    Yasaka" có chữ "khách sạn" trong tên nhưng vẫn là chỗ ăn, lấy tên vào so
    khớp là tự tạo dương tính giả.

    `cfg` là bảng [category] CỦA PROFILE. Chiều của cổng chặn do `cfg["mode"]`
    quyết định:

    - "blacklist" (FOOD): trúng một marker -> loại. Vốn từ nhãn ngành đồ ăn của
      Google là MỞ, không liệt kê hết được, nên chỉ liệt kê được cái KHÔNG phải.
    - "whitelist" (ACCOM): không trúng marker nào -> loại. Vốn từ lưu trú thì
      ĐÓNG và nhỏ; ở đây blacklist mới là cái bất khả thi.

    Fail-open có chủ ý ở CẢ HAI mode: không đọc được nhãn -> (l1_default, False).
    Nhãn rỗng là lỗi selector chứ không phải tín hiệu phân loại, và chặn nhầm
    một POI thật chỉ để lại dòng stub mà người gán nhãn khó nhận ra.
    """
    default = cfg.get("l1_default", "FOOD")
    if not _plain(category_raw):
        return default, False
    # Ranh giới từ, không phải chuỗi con: "spa" nằm trong "spaghetti" — khớp
    # chuỗi con sẽ biến quán mì Ý thành dòng stub trong im lặng.
    hit = any(_has_keyword(category_raw, m) for m in cfg.get("markers", []))
    if cfg.get("mode", "blacklist") == "whitelist":
        return (default, True) if hit else ("OTHER", True)
    return ("OTHER", True) if hit else (default, True)


def normalize_l2(value: Any, category_raw: str, name: str, cfg: dict[str, Any]) -> str:
    """Chốt category_l2 về ĐÚNG một trong các nhãn hợp lệ ở [category].l2_values.

    Ưu tiên giá trị Gemini trả về, nhưng chỉ khi nó khớp một nhãn hợp lệ — so
    khớp bỏ dấu, không phân biệt hoa/thường, và trả về CÁCH VIẾT CHUẨN trong
    config chứ không theo cách Gemini gõ (cùng cách `_plausible_ward` xử lý
    `old_wards`). Giá trị lạ không bao giờ được nhả ra cột.

    Gemini không trả hoặc trả bậy thì suy từ nhãn ngành Google + tên quán qua
    [[category.l2_hints]]; cùng đường thì lấy l2_fallback.

    `cfg` là bảng [category] CỦA PROFILE — bộ nhãn của FOOD và của ACCOM không
    có giao nhau, nên truyền nhầm profile là mọi POI rơi hết về l2_fallback.
    """
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


def _squash_sep(text: str) -> str:
    """Bỏ dấu, gộp mọi ký tự không phải chữ/số thành MỘT khoảng trắng."""
    return re.sub(r"[^a-z0-9]+", " ", _plain(text)).strip()


def normalize_vocab(value: Any, allowed: Iterable[str]) -> str:
    """Lọc câu trả lời Gemini về ĐÚNG các nhãn hợp lệ, giữ thứ tự Gemini xếp.

    Dùng cho MỌI cột có bộ giá trị đóng do người gán nhãn chốt trước —
    `matched_intents`, `tags`, `suitable_for`, `not_suitable_for`, `view_type`.

    KHÔNG dùng `as_list` được: nhãn hợp lệ có thể chứa dấu phẩy BÊN TRONG
    ("Nghỉ dưỡng, thư giãn", "Ghé nhanh, tiện đường"), tách theo dấu phẩy là vỡ
    chúng thành bốn mảnh và không mảnh nào khớp danh sách.

    Nên quét ngược lại: tìm từng nhãn hợp lệ TRONG chuỗi Gemini trả về (so khớp
    bỏ dấu, không phân biệt hoa thường), nhãn DÀI xét trước để nhãn ngắn không
    khớp trùng vào chỗ đã lấy, và xoá phần đã khớp khỏi chuỗi. Cách này miễn
    nhiễm với mọi kiểu ngăn cách Gemini dùng — phẩy, chấm phẩy, gạch đầu dòng,
    gạch chéo hay xuống dòng.

    So khớp có RANH GIỚI TỪ. Bộ giá trị của `tags`/`view_type` có những nhãn rất
    ngắn ("núi", "bbq", "gym", "biển"); khớp chuỗi con trần thì "nui" lọt vào
    giữa một từ khác và cột nhận nhãn chưa bao giờ được nhắc tới — đúng cái bẫy
    "pub" trong "gastropub" đã ghi ở schema._has_keyword.

    Không nhãn nào khớp -> chuỗi RỖNG. Giá trị Gemini tự nghĩ không bao giờ ra
    tới cột, nhưng vẫn còn nguyên trong data.json để rà lại.
    """
    allowed = list(allowed)
    if not allowed:
        return ""
    raw = " ".join(str(v) for v in value) if isinstance(value, list) else str(value or "")
    # Gộp mọi dấu câu thành khoảng trắng ở CẢ HAI phía: Gemini có thể trả
    # "Nghỉ dưỡng, thư giãn" hay "Nghỉ dưỡng thư giãn", và bản ghi cũ đã bị
    # parser tách mất dấu phẩy. Không chuẩn hoá thì hai dạng đó không khớp nhau.
    haystack = _squash_sep(raw)
    if not haystack:
        return ""

    hits: list[tuple[int, str]] = []
    for label in sorted(allowed, key=lambda s: len(_squash_sep(s)), reverse=True):
        needle = _squash_sep(label)
        if not needle:
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack)
        if m:
            hits.append((m.start(), label))
            # Thay bằng khoảng trắng chứ không cắt bỏ: giữ nguyên độ dài để vị
            # trí của các nhãn khớp sau vẫn so được với nhãn đã khớp trước.
            haystack = haystack[: m.start()] + " " * len(needle) + haystack[m.end() :]
    return ", ".join(label for _, label in sorted(hits))


# Tên cũ, giữ lại vì `matched_intents` là chỗ đầu tiên dùng hàm này và cả
# CLAUDE.md lẫn config đều trỏ tới tên đó.
normalize_intents = normalize_vocab


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


def apply_overrides(
    row: dict[str, str], record: POIRecord, columns: Iterable[str]
) -> dict[str, str]:
    """Áp phần sửa tay lên dòng vừa dựng. Gọi CUỐI CÙNG, ngay trước khi trả về.

    Đây là điều kiện để người gán nhãn dám sửa tay: sửa xong chạy lại `--only maps`
    (vá ảnh thực đơn chẳng hạn) KHÔNG được xoá mất chỗ vừa sửa. Vì `overrides` nằm
    trong data.json chứ không nằm trong row.tsv, xuất lại bao nhiêu lần cũng ra
    cùng kết quả.

    Chỉ nhận khoá thuộc `columns` của ĐÚNG profile bản ghi — khoá lạ (đổi tên
    cột, gõ sai, hoặc override còn sót từ profile khác) bị bỏ qua chứ không lặng
    lẽ đẻ thêm một cột nữa làm lệch cả file TSV.
    """
    allowed = frozenset(columns)
    overrides = getattr(record, "overrides", None) or {}
    for col, value in overrides.items():
        if col in allowed:
            row[col] = "" if value is None else str(value)
    return row


def resolved_address(maps: dict[str, Any], ward_map: dict[str, str]) -> dict[str, str]:
    """Địa chỉ + phường/tỉnh/vùng đã chuẩn hoá. Dùng chung cho mọi profile.

    Trả về {"address", "ward", "city", "region"}. Phường sau sáp nhập: Google
    trả tên CŨ nên phải tra bảng khai báo tay; nếu tên mới chưa có trong địa chỉ
    thì ghép lại, giữ nguyên số nhà + tên đường.
    """
    raw_address = maps.get("address") or ""
    location = split_address(raw_address)
    location["ward"] = merged_ward(raw_address, location["ward"], ward_map or {})
    address = clean_address(raw_address)
    if location["ward"] and location["ward"] not in address:
        street = address.split(",")[0].strip()
        address = ", ".join(p for p in [street, location["ward"], location["city"]] if p)
    return {**location, "address": address}


def modal_hours(maps: dict[str, Any]) -> tuple[str, str]:
    """Giờ mở/đóng: lấy khung phổ biến nhất trong tuần."""
    hours = (maps.get("hours") or {}).get("by_day") or {}
    opens = [d.get("open") for d in hours.values() if d.get("open")]
    closes = [d.get("close") for d in hours.values() if d.get("close")]
    return (
        max(set(opens), key=opens.count) if opens else "",
        max(set(closes), key=closes.count) if closes else "",
    )


def _photo_base(url: str) -> str:
    return url.split("=")[0]


def cover_and_gallery(maps: dict[str, Any]) -> tuple[str, list[str]]:
    """(ảnh đại diện, tối đa GALLERY_URLS_COUNT ảnh phụ). Dùng chung mọi profile.

    Chốt bất biến ở tầng xuất: raw_gallery_urls không được trùng nhau, cũng
    không được trùng raw_cover_image_url — kể cả khi data.json cũ (scrape từ
    trước khi gmaps.photos() vá lỗi so trùng theo kích thước ảnh) vẫn còn dữ
    liệu trùng lặp bên trong.

    Nguồn mặc định là bể ứng viên thật lấy từ mục "Tất cả"; chỉ lùi về
    `secondary` cho data.json CŨ chưa có bể đó. `secondary` (img.DaSXdd) thực
    chất là ảnh bìa của từng MỤC ảnh chứ không phải ảnh phụ của quán, nên nó chỉ
    là phương án chót. Người gán nhãn tick 3 ảnh ở tab "Ảnh" thì lựa chọn đó nằm
    trong `overrides` và được áp CUỐI CÙNG, đè lên mặc định này.
    """
    photos = maps.get("photos") or {}
    hero = photos.get("hero") or ""
    candidates = (maps.get("gallery_candidates") or {}).get("images") or []
    seen_bases = {_photo_base(hero)} if hero else set()
    gallery: list[str] = []
    for url in candidates or (photos.get("secondary") or []):
        base = _photo_base(url)
        if base in seen_bases:
            continue
        seen_bases.add(base)
        gallery.append(url)
    return hero, gallery[:GALLERY_URLS_COUNT]


def stub_row(record: POIRecord, l1: str, columns: Iterable[str]) -> dict[str, str]:
    """Dòng stub CHỈ có `name` + `category_l1`, mọi cột khác để trống.

    Dùng cho POI không thuộc nhóm ngành của profile (kể cả status/labeled_by/
    last_updated cũng để trống). Dataset vẫn có một dòng để biết POI này đã được
    kiểm tra và loại, thay vì im lặng biến mất.
    """
    columns = list(columns)
    stub = {col: "" for col in columns}
    stub["category_l1"] = l1
    stub["name"] = (record.google_maps or {}).get("name") or record.poi_name
    # Áp override cả ở đây: người rà lại có thể muốn sửa ngay trên dòng stub
    # (vd đổi `category_l1` sau khi xác nhận Google xếp ngành nhầm).
    return apply_overrides(stub, record, columns)


def build_row(
    record: POIRecord,
    defaults: dict[str, Any] | None = None,
    tiktok_index: int = 0,
    ward_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ánh xạ một POIRecord sang đúng bộ cột của PROFILE CỦA CHÍNH NÓ.

    Chỉ là bộ điều phối — dòng dữ liệu thật do `profiles.<name>.build_row` dựng.
    Giữ nguyên chữ ký cũ để `pipeline.export_row` và `server.api` không phải đổi.

    `defaults`/`ward_map` bỏ trống thì tự tra từ profile của bản ghi. Truyền tay
    vẫn được (test dùng), nhưng nhớ là truyền `[dataset]` của profile KHÁC thì
    `category_l1` lệch và cả dòng thành stub.
    """
    from .profiles import get_profile

    profile = get_profile(getattr(record, "profile", "") or "food")
    cfg = profile.settings()
    if defaults is None:
        defaults = cfg["dataset"]
    if ward_map is None:
        ward_map = cfg.get("ward_map", {})
    return profile.build_row(record, defaults, tiktok_index, ward_map)
