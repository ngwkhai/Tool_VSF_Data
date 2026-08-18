"""Điều phối 4 bước thu thập.

Nguyên tắc: ghi data.json sau MỖI bước. Bước sau hỏng không được làm mất kết quả
của bước trước — chạy lại với --resume là tiếp tục từ chỗ dở.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Callable

from rich.console import Console

from .browser import Session
from .config import output_dir, settings
from .models import PROFILE_FIELDS, POIRecord, parse_profile_block
from .schema import classify_l1, normalize_l2
from .paste import paste_images, upload_via_file_input
from .sites import gemini, gmaps, tiktok

# `maps` chạy TRƯỚC `gemini1`: cả cổng "không phải FOOD" lẫn cổng "lấy nhầm
# quán" đều nằm ở bước maps, đặt trước thì cả hai bắn xong mới tốn lượt Gemini
# nào. Bonus: gemini1 được đưa địa chỉ Google ĐÃ XÁC NHẬN thay vì --address gõ tay.
STEPS = ["maps", "gemini1", "old_address", "menu", "tiktok"]
console = Console()


# -- Từng bước -------------------------------------------------------------


def _field_count(parsed: dict) -> int:
    return sum(1 for f in PROFILE_FIELDS if parsed.get(f))


def _field_template(fields: list[str]) -> str:
    """'ten_truong:' mỗi dòng — dạng biểu mẫu neo Gemini vào đúng tên trường.

    Chỉ đưa DANH SÁCH tên trường trần (không dấu ':') từng khiến Gemini tự dịch
    tên trường sang tiếng Việt (`suitable_for` -> `doi_tuong_phu_hop`) dù được
    liệt kê rõ ràng ngay trong prompt — "chép lại biểu mẫu, điền vào chỗ trống"
    neo chắc hơn hẳn "tạo dòng theo tên trường sau".
    """
    return "\n".join(f"{f}:" for f in fields)


def _l2_values_clause() -> str:
    """Danh sách nhãn category_l2 hợp lệ, dựng từ config để rót vào prompt.

    Một nguồn sự thật duy nhất: prompt và bộ kiểm tra ở schema.normalize_l2 cùng
    đọc [category].l2_values, nên không còn hai bản danh sách trôi lệch nhau.
    """
    return ", ".join(f'"{v}"' for v in settings()["category"]["l2_values"])


def _merge(base: dict, extra: dict, first_answer: str) -> dict:
    """Gộp câu trả lời bổ sung vào câu đầu, không để lượt sau xoá mất lượt trước."""
    merged = {k: v for k, v in base.items() if not k.startswith("_")}
    merged.update({k: v for k, v in extra.items() if v and not k.startswith("_")})
    merged["_raw"] = base.get("_raw", "")
    merged["_raw_followup"] = extra.get("_raw", "")
    merged["_raw_first_answer"] = first_answer
    return merged


def step_gemini1(s: Session, record: POIRecord, poi: str) -> None:
    """Hỏi Gemini chat #1 để lấy hồ sơ mô tả POI.

    Thread chat dùng lâu có thể trôi khỏi schema và Gemini trả lời văn xuôi kèm
    trích dẫn web. Khi đó gửi thêm một prompt ép định dạng rồi parse lại.
    """
    cfg = settings()["gemini"]
    page = s.page("gemini_profile")
    gemini.open_chat(page, cfg["profile_chat_url"])

    # Địa chỉ giúp Gemini phân biệt quán trùng tên khi tự tìm kiếm, giống hệt lý
    # do gmaps.search_query() ghép địa chỉ vào truy vấn Maps. Ưu tiên địa chỉ
    # Google ĐÃ XÁC NHẬN ở bước `maps` (chạy trước bước này) — chính xác hơn hẳn
    # chuỗi --address người dùng gõ tay; lùi về address_hint khi chạy đơn lẻ
    # bằng `--only gemini1`.
    address = (record.google_maps or {}).get("address") or record.address_hint
    address_clause = f" (địa chỉ: {address})" if address else ""
    prompt = cfg["profile_prompt"].format(
        poi=poi,
        address_clause=address_clause,
        n_fields=len(PROFILE_FIELDS),
        l2_values=_l2_values_clause(),
    )
    answer = gemini.ask(page, prompt)
    parsed = parse_profile_block(answer)

    # Giai đoạn 1 — thread trôi khỏi schema (trả lời văn xuôi): kéo về đúng định
    # dạng bằng cách liệt kê lại cả bộ trường.
    if _field_count(parsed) < cfg["min_fields_before_reformat"]:
        record.warn(
            f"Câu trả lời đầu chỉ ra {_field_count(parsed)} trường "
            "(Gemini trả lời văn xuôi) — đang yêu cầu định dạng lại"
        )
        retry = parse_profile_block(
            gemini.ask(page, cfg["reformat_prompt"].format(fields=_field_template(PROFILE_FIELDS)))
        )
        if _field_count(retry) > _field_count(parsed):
            parsed = _merge(parsed, retry, first_answer=answer)

    # Giai đoạn 2 — đúng định dạng nhưng thiếu trường: chỉ hỏi phần còn thiếu.
    missing = [f for f in PROFILE_FIELDS if not parsed.get(f)]
    if missing:
        record.warn(
            f"Còn {_field_count(parsed)}/{len(PROFILE_FIELDS)} trường "
            f"— đang hỏi bổ sung: {', '.join(missing)}"
        )
        extra = gemini.ask(
            page,
            cfg["fill_missing_prompt"].format(
                missing=_field_template(missing), l2_values=_l2_values_clause()
            ),
        )
        parsed = _merge(parsed, parse_profile_block(extra), first_answer=answer)

    # KHÔNG suy luận các trường còn thiếu ở đây: must_try_dishes cần thực đơn,
    # mà bước `menu` chạy SAU bước này. Việc suy luận nằm ở tầng xuất (schema.py),
    # lúc đó cả 4 bước đã xong.
    still_missing = [f for f in PROFILE_FIELDS if not parsed.get(f)]
    if still_missing:
        parsed["_missing_fields"] = still_missing
    record.gemini_profile = parsed

    # Chốt category_l2: nhãn Gemini nếu hợp lệ, không thì giữ giá trị suy từ nhãn
    # ngành Google đã đặt ở bước `maps`. normalize_l2 không bao giờ nhả giá trị
    # lạ ra cột — nhãn Gemini tự nghĩ vẫn nằm nguyên trong data.json.
    maps = record.google_maps or {}
    record.category_l2 = normalize_l2(
        parsed.get("category_l2"), maps.get("category_raw", ""), maps.get("name") or poi
    )

    if still_missing:
        record.warn(f"Gemini không cung cấp: {', '.join(still_missing)} (sẽ suy ra khi xuất)")


def _reject_wrong_place(data: dict, poi: str) -> None:
    """Chặn hẳn khi Google trả về quán khác. Gọi TRƯỚC khi cào phần đắt tiền.

    KHÔNG chỉ cảnh báo: lấy nhầm quán làm sai toàn bộ dòng dữ liệu mà trước đây
    không có dấu hiệu gì rõ ràng (đã gặp: "Greek Cuisine" -> Google trả "Greek
    Kitchen", quán khác ở phố khác, name_match=0.5 lọt qua ngưỡng cũ trong im
    lặng vì so sánh `<` chứ không `<=`).
    """
    cfg = settings()["gmaps"]
    name_score = data.get("name_match")
    addr_score = data.get("address_match")
    problems = []
    if name_score is not None and name_score < cfg["name_match_threshold"]:
        problems.append(f"tên chỉ khớp {name_score:.0%}")
    if addr_score is not None and addr_score < cfg["address_match_threshold"]:
        problems.append(f"địa chỉ chỉ khớp {addr_score:.0%}")
    if problems:
        raise RuntimeError(
            f"CÓ THỂ LẤY NHẦM QUÁN: hỏi {poi!r} nhưng Google trả về {data['name']!r} "
            f"tại {data.get('address')!r} ({'; '.join(problems)}). "
            "Kiểm tra lại tên/địa chỉ, chạy lại với --address chính xác hơn nếu cần."
        )


def _reject_non_food(record: POIRecord, data: dict) -> bool:
    """Chốt category_l1/l2 từ nhãn ngành Google. True = KHÔNG phải FOOD, dừng.

    `--force-food` bỏ qua cổng này cho trường hợp nhãn Google gây hiểu nhầm
    (vd quán ăn nằm trong khách sạn bị xếp ngành "Khách sạn").
    """
    raw = data.get("category_raw", "")
    if record.force_food:
        record.category_l1 = settings()["category"].get("l1_default", "FOOD")
    else:
        l1, certain = classify_l1(raw)
        record.category_l1 = l1
        if l1 != "FOOD":
            record.warn(
                f"KHÔNG PHẢI FOOD: Google xếp địa điểm này vào ngành {raw!r} -> "
                f"category_l1={l1}. Bỏ qua các bước còn lại, row.tsv chỉ có `name`. "
                "Nếu đây là nhầm lẫn, chạy lại với --force-food."
            )
            return True
        if not certain:
            record.warn(
                "Không đọc được nhãn ngành của Google — mặc định coi là FOOD. "
                "Kiểm tra selector [gmaps].place_category bằng /poi-recon gmaps."
            )

    # Giá trị dự phòng từ nhãn Google; step_gemini1 ghi đè nếu Gemini trả nhãn hợp lệ.
    record.category_l2 = normalize_l2(None, raw, data.get("name", ""))
    return False


def step_maps(s: Session, record: POIRecord, poi: str) -> None:
    """Thu thập toàn bộ dữ liệu từ Google Maps, kể cả URL ảnh thực đơn."""
    page = s.page("gmaps")
    address_hint = record.address_hint

    # Giữ lại kết quả bước `old_address` (nếu đã chạy trước đó) — record.google_maps
    # bị GHI ĐÈ TOÀN BỘ bằng dict mới ở dưới, nếu không chạy lại `--only maps`
    # (vd để vá ảnh thực đơn) sau khi `old_address` đã chạy xong sẽ âm thầm xoá
    # mất kết quả đó (đã gặp: "chớm brew&bloom").
    preserved_old_address = {
        k: (record.google_maps or {}).get(k)
        for k in ("old_address", "old_ward", "old_ward_source")
    }

    gmaps.open_place(page, poi, address_hint=address_hint)

    data = gmaps.basic_info(page, requested=poi, address_hint=address_hint)
    for k, v in preserved_old_address.items():
        if v is not None:
            data[k] = v

    # Gán ngay khi có tên/địa chỉ: mọi thứ bên dưới có thể ném lỗi, record vẫn
    # giữ được `data` (cùng object, cập nhật thêm qua tham chiếu) thay vì mất
    # trắng vì exception chặn dòng gán ở cuối.
    record.google_maps = data

    # HAI CỔNG CHẶN, đặt ngay sau basic_info — TRƯỚC khi cào giờ/ảnh/đánh giá/
    # thực đơn. Trước đây kiểm tra "lấy nhầm quán" nằm tận cuối bước nên vẫn cào
    # trọn gói rồi mới vứt đi; giờ sai quán hoặc không phải đồ ăn là dừng ngay.
    _reject_wrong_place(data, poi)
    if _reject_non_food(record, data):
        return

    data["hours"] = gmaps.opening_hours(page)
    data["photos"] = gmaps.photos(page)
    data["reviews"] = gmaps.reviews(page)

    # Lấy ảnh thực đơn ở đây luôn để bước `menu` chỉ còn việc dán sang Gemini,
    # và để `--only menu` chạy lại được mà không cần mở lại Google Maps.
    menu = gmaps.menu_photos(page)
    data["menu_photos"] = menu

    cfg = settings()["gmaps"]
    if note := data["reviews"].get("note"):
        record.warn(f"Google Maps: {note}")
    if err := menu.get("error"):
        record.warn(f"Ảnh thực đơn: {err}")
    if data["hours"].get("incomplete"):
        record.warn("Google Maps: bảng giờ mở cửa không đủ 7 ngày")
    n_secondary = len(data["photos"].get("secondary") or [])
    if n_secondary < cfg["secondary_photo_count"]:
        record.warn(
            f"Google Maps: chỉ lấy được {n_secondary}/{cfg['secondary_photo_count']} "
            "ảnh phụ không trùng nhau"
        )


# Dấu hiệu câu xã giao/diễn giải, không phải địa chỉ.
PROSE_MARKERS = (
    "cảm ơn", "xin lỗi", "hy vọng", "thông tin", "ghi nhận", "cập nhật",
    "địa chỉ mới", "hiện tại", "sau sáp nhập", "tôi không", "lưu ý",
)


def _plain_address(text: str) -> str:
    """Rút gọn địa chỉ về dạng so sánh được: bỏ dấu, bỏ mã bưu chính, bỏ đuôi nước."""
    text = (text or "").replace("đ", "d").replace("Đ", "D").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b\d{5,6}\b|viet ?nam", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_keep_space(text: str) -> str:
    """Như _plain_address nhưng GIỮ khoảng trắng — dùng để quét cả đoạn văn xuôi
    tìm tên phường mà không khớp nhầm một token dính liền không có khoảng trắng
    (tên phường tiếng Việt luôn >= 2 âm tiết, phải có khoảng trắng thật)."""
    text = (text or "").replace("đ", "d").replace("Đ", "D").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]+", " ", text)


_WARD_LABEL = re.compile(r"^\W*(?:old_?)?(?:ward|phuong|phường|xã)\s*:\s*", re.IGNORECASE)
_WARD_PREFIX = re.compile(r"^(?:phường|xã|p\.|x\.)\s+", re.IGNORECASE)


# Gemini chèn tên nguồn trích dẫn thành dòng riêng ("Laodong.vn", "Báo Khánh Hoà")
# — trông y hệt một câu trả lời ngắn nên rất dễ bị nhặt nhầm.
_DOMAIN = re.compile(r"\.(vn|com|net|org|info|gov|edu)\b", re.IGNORECASE)


def _plausible_ward(line: str, new_ward: str, known: dict[str, str]) -> str | None:
    """Kiểm tra một dòng có phải tên phường/xã hợp lệ không.

    Nếu có danh sách phường cũ thì đối chiếu thẳng — đây là bộ lọc mạnh nhất.
    Lọc theo hình dạng chuỗi không đủ: tiêu đề nguồn trích dẫn của Gemini cũng
    ngắn, có khoảng trắng và không chứa tên miền.
    """
    if not line or len(line) > 40 or "," in line:
        return None
    if _DOMAIN.search(line) or "http" in line.lower():
        return None
    if any(word in line.lower() for word in PROSE_MARKERS):
        return None

    name = _WARD_PREFIX.sub("", line).strip()
    # Tên phường/xã tiếng Việt luôn có từ 2 âm tiết trở lên -> phải có khoảng trắng.
    if not name or " " not in name:
        return None
    if _plain_address(name) == _plain_address(new_ward):
        return None

    if known:
        # Trả về đúng cách viết chuẩn trong danh sách, không theo cách Gemini gõ.
        return known.get(_plain_address(name))
    return name


def _extract_old_ward_json(answer: str) -> str | None:
    """Rút giá trị `old_ward` từ object JSON mà prompt ép Gemini trả về.

    Trả None nếu KHÔNG tìm thấy object JSON nào trong câu trả lời (Gemini phớt
    lờ hoàn toàn định dạng ép buộc) — lúc đó gọi ở trên sẽ lùi về phân tích dòng
    văn bản cũ. Nếu object JSON có tồn tại nhưng khoá `old_ward` không phải
    chuỗi (vd Gemini trả cả mảng danh sách phường) thì trả "" — có JSON nhưng
    KHÔNG có câu trả lời hợp lệ, khác với "không có JSON" nên KHÔNG được lùi về
    phân tích dòng (dòng JSON dạng mảng dễ bị nhặt nhầm từng phần tử).
    """
    match = re.search(r"\{[^{}]*\}", answer, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return ""
    for key in ("old_ward", "old_address_ward", "phuong_cu", "ward"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def extract_old_ward(answer: str, new_ward: str, old_wards: list[str] | None = None) -> str | None:
    """Rút tên phường/xã CŨ từ câu trả lời của Gemini.

    Prompt hiện ép Gemini trả về ĐÚNG MỘT object JSON (`{"old_ward": "..."}`) —
    ưu tiên parse JSON trước vì chắc chắn hơn hẳn phân tích dòng văn bản (không
    lẫn với tiêu đề nguồn trích dẫn Gemini hay chèn). CHỈ lùi về phân tích dòng
    cũ khi câu trả lời không chứa object JSON nào — nếu đã có JSON nhưng giá trị
    không hợp lệ, coi đó là câu trả lời rõ ràng (rỗng/sai), đừng đoán tiếp bằng
    cách quét văn bản thô của chính khối JSON đó.
    """
    known = {_plain_address(w): w for w in (old_wards or [])}

    json_value = _extract_old_ward_json(answer)
    if json_value is not None:
        return _plausible_ward(json_value, new_ward, known) if json_value else None

    labelled: list[str] = []
    plain: list[str] = []
    for raw in answer.splitlines():
        line = raw.strip().strip(" *`\"'.")
        # Luôn bóc nhãn trước khi kiểm tra, kể cả ở lượt quét dự phòng — nếu không,
        # "old_ward: Tây Nha Trang" sẽ khác chuỗi "Tây Nha Trang" và lọt qua phép
        # so sánh với phường mới.
        if _WARD_LABEL.match(line):
            labelled.append(_WARD_LABEL.sub("", line).strip(" *`\"'."))
        else:
            plain.append(line)

    for line in labelled:
        if name := _plausible_ward(line, new_ward, known):
            return name

    # Gemini đôi khi phớt lờ yêu cầu và liệt kê NGUYÊN danh sách toàn bộ
    # phường/xã cũ thay vì trả lời đúng khu vực được hỏi (đã kiểm chứng: 2 địa
    # chỉ cách xa nhau nhận được y hệt cùng một danh sách). Mọi dòng trong danh
    # sách đó đều "hợp lệ" theo whitelist -> không thể lọc bằng hình dạng chuỗi.
    # Chỉ còn cách đếm: >= 3 dòng khớp whitelist trong phần KHÔNG có nhãn nghĩa
    # là đang liệt kê, không phải một câu trả lời cụ thể -> bỏ, đừng đoán bừa
    # dòng đầu tiên (luôn ra "Lộc Thọ" vì Gemini liệt kê nó đầu danh sách).
    matches = [name for line in plain if (name := _plausible_ward(line, new_ward, known))]
    if len(set(matches)) >= 3:
        return None
    if len(set(matches)) == 1:
        return matches[0]

    # Không có dòng ngắn nào khớp (thường vì Gemini trả lời bằng văn xuôi thay
    # vì đúng mẫu "old_ward: X") -> quét nguyên văn bản tìm tên phường/xã đã
    # biết xuất hiện ở đâu đó trong câu (đã gặp: "...thuộc địa bàn phường Xương
    # Huân, thành phố Nha Trang..." — đúng tên phường nhưng nằm giữa câu dài có
    # dấu phẩy nên bộ lọc theo dòng bỏ sót). CHỈ chấp nhận khi đúng một tên
    # phường/xã xuất hiện — nhiều tên trở lên nghĩa là câu trả lời còn lưỡng lự
    # giữa hai khu vực (ví dụ giáp ranh), không nên đoán bừa cái nào.
    plain_answer = _normalize_keep_space(answer)
    found = {
        name
        for ward in (old_wards or [])
        if (name := ward) and f" {_normalize_keep_space(ward).strip()} " in f" {plain_answer} "
    }
    found.discard(new_ward)
    if len(found) == 1:
        return next(iter(found))
    return None


def ward_in_address(address: str, old_wards: list[str]) -> str | None:
    """Tìm tên phường CŨ nằm sẵn trong địa chỉ Google.

    Chắc chắn hơn hẳn việc hỏi Gemini — Google nhiều khi vẫn giữ tên phường cũ
    trong chuỗi địa chỉ dù đã đổi tên đơn vị hành chính cấp trên.
    """
    parts = [p.strip() for p in (address or "").split(",")]
    lookup = {_plain_address(w): w for w in old_wards}
    for part in parts:
        if hit := lookup.get(_plain_address(part)):
            return hit
    return None


def compose_old_address(address: str, old_ward: str, city: str) -> str:
    """Ghép địa chỉ cũ: giữ số nhà + đường, thay phường mới bằng phường cũ.

    "Đ. Hoàng Cầm/17 KĐT, Vĩnh Điềm Trung, Tây Nha Trang, Khánh Hoà"
      + "Vĩnh Hiệp"  ->
    "Đ. Hoàng Cầm/17 KĐT, Vĩnh Hiệp, TP. Nha Trang, Khánh Hoà"
    """
    parts = [p.strip() for p in address.split(",") if p.strip()]
    parts = [p for p in parts if p.lower() not in {"việt nam", "vietnam"}]
    parts = [re.sub(r"\s*\d{5,6}\s*$", "", p).strip() for p in parts]
    # Bỏ phần đuôi hành chính (phường mới + tỉnh), giữ lại số nhà/đường.
    street = parts[0] if parts else address
    return f"{street}, {old_ward}, TP. Nha Trang, {city}"


def step_old_address(s: Session, record: POIRecord, poi: str) -> None:
    """Hỏi Gemini địa chỉ TRƯỚC đợt sáp nhập phường/xã 1/7/2025.

    Chạy sau `maps` vì cần địa chỉ hiện tại làm đầu vào. Google chỉ có tên đơn vị
    hành chính mới, không có cách nào suy ngược ra tên cũ.
    """
    cfg = settings()["gemini"]
    address = (record.google_maps or {}).get("address")
    if not address:
        record.warn("Bỏ qua bước địa chỉ cũ: chưa có địa chỉ từ Google Maps")
        return

    from .schema import split_address

    location = split_address(address)
    city = location["city"] or "Khánh Hoà"

    old_wards = settings().get("nha_trang", {}).get("old_wards", [])

    # Google nhiều khi vẫn giữ tên phường CŨ ngay trong địa chỉ. Đọc thẳng từ đó
    # chắc chắn hơn hỏi Gemini — chỉ hỏi khi địa chỉ không chứa phường cũ nào.
    old_ward = ward_in_address(address, old_wards)
    source = "địa chỉ Google"

    if not old_ward:
        page = s.page("gemini_profile")
        gemini.open_chat(page, cfg["profile_chat_url"])
        prompt = cfg["old_address_prompt"].format(poi=poi, address=address, city="Nha Trang")
        answer = gemini.ask(page, prompt)
        old_ward = extract_old_ward(answer, new_ward=location["ward"], old_wards=old_wards)
        source = "Gemini"

    old = compose_old_address(address, old_ward, city) if old_ward else None

    if old:
        record.google_maps["old_ward"] = old_ward
        record.google_maps["old_address"] = old
        record.google_maps["old_ward_source"] = source
        if source == "Gemini":
            record.warn(
                f"old_address dùng phường {old_ward!r} do Gemini suy đoán — "
                "nên kiểm tra lại bằng mắt, Gemini hay đoán nhầm phường."
            )
    else:
        # Xoá giá trị của lần chạy trước — để lại dữ liệu rác còn tệ hơn để trống.
        record.google_maps.pop("old_address", None)
        record.google_maps.pop("old_ward", None)
        if source == "Gemini":
            record.warn(
                "old_address để trống: Gemini liệt kê nguyên danh sách phường/xã "
                "cũ thay vì trả lời riêng cho khu vực này — không đoán bừa dòng "
                "đầu tiên, cần điền tay nếu cần."
            )
        record.warn(
            "Không lấy được tên phường trước sáp nhập từ Gemini "
            f"(trả lời: {answer[:120]!r})"
        )


def _looks_like_menu_json(answer: str) -> bool:
    """Câu trả lời có mang một mảng JSON hợp lệ không (thay vì văn xuôi)."""
    start, end = answer.find("["), answer.rfind("]")
    if start < 0 or end <= start:
        return False
    try:
        import json

        return isinstance(json.loads(answer[start : end + 1]), list)
    except json.JSONDecodeError:
        return False


def step_menu(s: Session, record: POIRecord, poi: str) -> None:
    """Dán ảnh thực đơn sang Gemini chat #2 và lấy phần trích xuất."""
    cfg = settings()["gemini"]
    urls = (record.google_maps.get("menu_photos") or {}).get("images") or []
    if not urls:
        record.warn("Bỏ qua bước thực đơn: không có ảnh thực đơn nào từ Google Maps")
        record.menu = {"skipped": True, "reason": "không có ảnh thực đơn"}
        return

    page = s.page("gemini_menu")
    gemini.open_chat(page, cfg["menu_chat_url"])

    outcome = paste_images(page, urls)
    if not outcome.get("pasted"):
        record.warn("Dán ảnh thất bại, chuyển sang phương án input[type=file]")
        outcome = upload_via_file_input(page, urls)
    if not outcome.get("pasted"):
        raise RuntimeError(f"Không đưa được ảnh thực đơn vào Gemini: {outcome}")

    before = gemini.response_count(page)
    gemini.type_prompt(page, cfg["menu_prompt"])
    gemini.send(page)
    answer = gemini.wait_for_response(page, before)

    # Thread trôi khỏi định dạng JSON (Gemini trả lời văn xuôi) -> ép lại một
    # lần. Không làm thì schema.menu_json() không đọc được gì và cả cột `menu`
    # lẫn `price_min/max`/`must_try_dishes` suy từ nó đều rỗng dù dữ liệu có sẵn.
    if not _looks_like_menu_json(answer):
        record.warn("Thực đơn trả lời văn xuôi (không phải JSON) — đang yêu cầu định dạng lại")
        reformatted = gemini.ask(page, cfg["menu_reformat_prompt"])
        if _looks_like_menu_json(reformatted):
            answer = reformatted
        else:
            record.warn("Định dạng lại vẫn không ra JSON — giữ nguyên câu trả lời gốc trong _raw")

    record.menu = {
        "images_sent": urls,
        "paste_result": outcome,
        "extracted": parse_profile_block(answer),
    }


def step_tiktok(s: Session, record: POIRecord, poi: str) -> None:
    page = s.page("tiktok")
    candidates = tiktok.search(page, poi)
    record.tiktok = candidates
    if not candidates:
        record.warn("TikTok: không tìm được video nào")


HANDLERS: dict[str, Callable[[Session, POIRecord, str], None]] = {
    "gemini1": step_gemini1,
    "maps": step_maps,
    "old_address": step_old_address,
    "menu": step_menu,
    "tiktok": step_tiktok,
}


# -- Điều phối -------------------------------------------------------------


def _skip_reason(record: POIRecord, step: str) -> str | None:
    """Lý do bỏ qua `step`, hoặc None nếu cứ chạy. Chỉ xét khi chạy cả chuỗi."""
    if step == "maps":
        return None

    # `maps` giờ chạy ĐẦU TIÊN nên mọi bước sau đều phụ thuộc nó: gemini1 lấy
    # địa chỉ đã xác nhận, old_address lấy địa chỉ hiện tại, menu lấy ảnh thực
    # đơn, và cả ba cần biết đây đúng là quán được hỏi. Trước khi đảo thứ tự,
    # gemini1 chạy trước nên `maps` hỏng chỉ mất phần dữ liệu Google; giờ chạy
    # tiếp là gửi Gemini một POI chưa xác minh với địa chỉ rỗng (đã gặp: "Greek
    # Cuisine" bị chặn vì Google trả "Greek Kitchen", nhưng 3 lượt Gemini vẫn
    # được đốt sạch trên dữ liệu rỗng rồi ghi "ok").
    if record.steps.get("maps") != "ok":
        return "bước maps chưa xong"

    if record.category_l1 and record.category_l1 != "FOOD":
        return "không phải FOOD"

    return None


def run(
    poi: str,
    only: str | None = None,
    resume: bool = False,
    index: int | None = None,
    address: str | None = None,
    force_food: bool = False,
) -> POIRecord:
    out = output_dir()
    record = POIRecord.load_or_new(out, poi, index=index)
    if address:
        record.address_hint = address
    record.force_food = force_food
    if force_food and record.category_l1 and record.category_l1 != "FOOD":
        # Xoá kết luận non-FOOD của lần chạy trước, nếu không cổng dưới đây chặn
        # ngay từ bước `maps` và --force-food thành vô nghĩa.
        record.category_l1 = ""
    wanted = [only] if only else STEPS

    with Session() as s:
        for step in wanted:
            if resume and record.steps.get(step) == "ok":
                console.print(f"[dim]· {step}: bỏ qua (đã ok)[/]")
                continue

            # `--only <step>` là lệnh chạy ĐÚNG bước đó, kể cả khi phụ thuộc chưa
            # đủ — dùng để vá lại một bước lẻ. Không áp cổng chặn lên nó.
            if not only and (reason := _skip_reason(record, step)):
                record.steps[step] = "skipped"
                console.print(f"[dim]· {step}: bỏ qua ({reason})[/]")
                continue

            console.print(f"[bold cyan]▸ {step}[/] …")
            record.begin_step(step)
            try:
                HANDLERS[step](s, record, poi)
                record.steps[step] = "ok"
                console.print(f"  [green]✓ {step}[/]")
            except Exception as exc:
                record.steps[step] = "failed"
                record.warn(f"{step} lỗi: {type(exc).__name__}: {exc}")
                console.print(f"  [red]✗ {step}[/]: {exc}")
            finally:
                # Ghi ngay cả khi bước vừa rồi hỏng -> không mất công đã làm.
                path = record.save(out)

    console.print(f"\nĐã ghi [bold]{path}[/]")
    console.print(f"Đã ghi [bold]{export_row(record)}[/]")
    return record


def export_row(record: POIRecord, tiktok_index: int = 0):
    """Xuất row.tsv đúng 73 cột — đây mới là output chính thức để nạp dataset."""
    import csv

    from .schema import COLUMNS, build_row

    out = output_dir()
    row = build_row(
        record,
        settings().get("dataset", {}),
        tiktok_index=tiktok_index,
        ward_map=settings().get("ward_map", {}),
    )
    path = out / record.slug / "row.tsv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerow(row)
    return path
