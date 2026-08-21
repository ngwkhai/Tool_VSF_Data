"""Profile FOOD — POI đồ ăn, 73 cột.

Cấu hình đi kèm: `config/profile_food.toml`.
Phần dùng chung với profile lưu trú nằm ở `vsf.schema`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .. import schema
from ..models import POIRecord

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

STEPS = ["maps", "gemini1", "old_address", "menu", "tiktok", "facebook"]

# 26 trường hỏi Gemini #1 trong MỘT lượt. Thứ tự phải khớp biểu mẫu trong
# [gemini] profile_prompt của config/profile_food.toml.
PROFILE_FIELDS = [
    "name_en",
    "category_l2",
    "tags",
    "cuisine_type",
    "must_try_dishes",
    "price_per_person_avg",
    "seating_capacity",
    "dietary_options",
    "reservation_required",
    "dress_code",
    "alcohol_served",
    "view_type",
    "operating_note",
    "description_short",
    "description_long",
    "best_time_to_visit",
    "estimated_duration",
    "suitable_for",
    "not_suitable_for",
    "insider_tips",
    "weather_dependency",
    "crowd_level_note",
    "matched_intents",
    "search_keywords",
    "confidence_level",
    "info_expiry_note",
]

LIST_FIELDS = frozenset(
    {"tags", "matched_intents", "search_keywords", "cuisine_type", "must_try_dishes"}
)

# Gemini có một mẫu "danh thiếp" cố định tự kích hoạt khi tra địa điểm, ghi đè
# lên biểu mẫu được yêu cầu. Ánh xạ lại thay vì tiếp tục sửa câu chữ prompt;
# khoá trùng dữ liệu Google Maps (name/address/phone/rating) cố ý bỏ vào `extra`.
FIELD_ALIASES = {
    "famous_dishes": "must_try_dishes",
    "price_range": "price_per_person_avg",
    "reservation": "reservation_required",
    "ambiance": "description_short",
    "service_style": "operating_note",
}

# Gemini có một mẫu trích xuất thực đơn CỐ ĐỊNH tự kích hoạt cho tác vụ dạng
# này — đã kiểm chứng lặp lại Y HỆT (name/description/price/category, "price"
# là SỐ nguyên đầy đủ VNĐ) dù prompt yêu cầu rõ ràng đúng 3 khoá
# loai_thuc_pham/ten/gia (xem FIELD_ALIASES ở trên — cùng hiện tượng với hồ sơ
# POI). Không phải lỗi ngẫu nhiên mà là template nội bộ không đổi được bằng
# prompt, nên ánh xạ lại thay vì tiếp tục sửa câu chữ prompt.
_MENU_NAME_ALIASES = ("ten", "name", "mon", "ten_mon", "item", "item_name")
_MENU_CATEGORY_ALIASES = ("loai_thuc_pham", "category", "loai", "nhom", "section")

# Mục thực đơn hay chứa món đặc trưng của quán, theo thứ tự ưu tiên.
SIGNATURE_MENU_SECTIONS = ["đặc biệt", "đặc sản", "món tủ", "signature", "best seller"]

# Dấu hiệu quán có bán đồ uống có cồn.
ALCOHOL_HINTS = ["bia", "rượu", "beer", "wine", "cocktail", "nhậu", "lẩu"]


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
    """Khối JSON thực đơn Gemini trả về, chuẩn hoá lại cho gọn."""
    raw = ((record.menu or {}).get("extracted") or {}).get("_raw") or ""
    return schema.price_table_json(raw, _normalize_menu_item)


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
    ranked = sorted(
        items, key=lambda i: schema.parse_menu_price(i.get("gia")) or 0, reverse=True
    )
    return [i["ten"] for i in ranked[:limit]]


def derive_missing(profile: dict[str, Any], record: POIRecord) -> dict[str, Any]:
    """Suy các trường còn thiếu từ dữ liệu đã có, thay vì để trống."""
    out: dict[str, Any] = {}
    menu_text = menu_json(record)

    # KHÔNG suy name_en ở đây: chỉ nhận tên tiếng Anh thật, lọc ở english_name.
    # category_l2 cũng không suy ở đây mà ở normalize_l2 — nó cần nhãn ngành
    # Google (`category_raw`), thứ mà derive_missing không nhận vào.

    if dishes := signature_dishes(menu_text):
        out["must_try_dishes"] = dishes

    # Có bia/rượu/lẩu trong thực đơn hoặc tag "quán nhậu" -> có phục vụ đồ uống có cồn.
    haystack = (menu_text + " " + schema.join_list(profile.get("tags"))).lower()
    if any(hint in haystack for hint in ALCOHOL_HINTS):
        out["alcohol_served"] = "có"

    # Quán bình dân gần như không cần đặt bàn.
    avg = schema.parse_amount(profile.get("price_per_person_avg"))
    if avg is not None:
        out["reservation_required"] = "không" if avg <= 150_000 else "có"

    return out


def build_row(
    record: POIRecord,
    defaults: dict[str, Any],
    tiktok_index: int = 0,
    ward_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ánh xạ một POIRecord sang đúng 73 cột của dataset FOOD."""
    from ..config import profile_settings

    maps = record.google_maps or {}
    category_cfg = profile_settings("food")["category"]

    # POI không thuộc nhóm đồ ăn -> dòng stub. Đọc `record.category_l1` trước,
    # lùi về defaults cho data.json cũ chưa có khoá này, để không POI cũ nào
    # bỗng dưng thành stub.
    l1 = getattr(record, "category_l1", "") or defaults.get("category_l1", "FOOD")
    if l1 != category_cfg.get("l1_default", "FOOD"):
        return schema.stub_row(record, l1, COLUMNS)

    # Suy các trường Gemini không cho. Làm ở đây (không phải lúc chạy bước
    # gemini1) vì must_try_dishes cần thực đơn — chỉ có sau khi bước `menu` xong.
    profile = dict(record.gemini_profile or {})
    for key, value in derive_missing(profile, record).items():
        if not profile.get(key):
            profile[key] = value

    reviews = maps.get("reviews") or {}
    picked = schema.pick_video(record, tiktok_index)
    location = schema.resolved_address(maps, ward_map or {})
    address = location["address"]
    open_time, close_time = schema.modal_hours(maps)
    hero, gallery = schema.cover_and_gallery(maps)

    menu_text = menu_json(record)
    price_min, price_max = schema.price_range(menu_text)
    avg = schema.parse_amount(profile.get("price_per_person_avg"))
    name = maps.get("name") or record.poi_name

    row = {
        "poi_id": "",
        "category_l1": l1,
        "name": name,
        "name_en": schema.english_name(profile.get("name_en"), name),
        # Bước `maps`/`gemini1` đã chốt sẵn vào record; chạy lại normalize_l2 ở
        # đây để `vsf export` trên data.json CŨ (chưa có khoá này) vẫn ra nhãn
        # đúng chuẩn thay vì cột rỗng.
        "category_l2": getattr(record, "category_l2", "")
        or schema.normalize_l2(
            profile.get("category_l2"), maps.get("category_raw", ""), name, category_cfg
        ),
        "tags": schema.join_list(profile.get("tags")),
        "cuisine_type": schema.join_list(profile.get("cuisine_type")),
        "must_try_dishes": schema.join_list(profile.get("must_try_dishes")),
        "menu": menu_text,
        "price_per_person_avg": schema.money(avg),
        # Để trống — Gemini chỉ đoán được số chỗ ngồi, không tra được.
        "seating_capacity": "",
        "dietary_options": profile.get("dietary_options") or "",
        "reservation_required": schema.boolean(profile.get("reservation_required")),
        "dress_code": (profile.get("dress_code") or "").capitalize(),
        "alcohol_served": schema.boolean(profile.get("alcohol_served")),
        "view_type": profile.get("view_type") or "",
        "lat": str(maps.get("lat") or ""),
        "long": str(maps.get("long") or ""),
        # Địa chỉ trước sáp nhập 1/7/2025 — do bước old_address chốt.
        "old_address": schema.clean_address(maps.get("old_address")),
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
        "price_min": schema.money(price_min),
        "price_max": schema.money(price_max),
        "price_level": schema.price_level_for(avg, category_cfg.get("price_levels", [])),
        "booking_required": schema.boolean(profile.get("reservation_required")),
        "booking_source": defaults.get("booking_source", "internal"),
        "rating_score": str(maps.get("rating") or ""),
        "review_count": str(maps.get("review_count") or ""),
        "rating_source": defaults.get("rating_source", "Google Maps"),
        "cover_image_url": "",
        "gallery_urls": "",
        "positive_comments": schema.quoted_comments(reviews.get("positive") or []),
        "negative_comments": schema.quoted_comments(reviews.get("negative") or []),
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
        "info_expiry_note": profile.get("info_expiry_note")
        or defaults.get("info_expiry_note", ""),
        "nearby_poi_ids": "",
        "complementary_poi_ids": "",
        "alternative_poi_ids": "",
        "weather_dependency": profile.get("weather_dependency") or "",
        "crowd_level_note": profile.get("crowd_level_note") or "",
        "matched_intents": schema.join_list(profile.get("matched_intents")),
        "search_keywords": schema.join_list(profile.get("search_keywords")),
        "nearby_hotel_ids": "",
        "status": defaults.get("status", "active"),
        "labeled_by": defaults.get("labeled_by", ""),
        "review_status": defaults.get("review_status", "draft"),
        "reviewer_note": "",
        "last_updated": date.today().isoformat(),
        "by_pass": "FALSE",
        "dest": schema.slug_dest(location["city"], address),
        # raw_* giữ nguyên dữ liệu thô; cover_image_url/gallery_urls để trống cho
        # khâu xử lý ảnh phía sau điền vào, đúng như dòng mẫu.
        "raw_url": picked.get("url") or "",
        "raw_cover_image_url": hero,
        "raw_gallery_urls": ", ".join(gallery),
    }
    return schema.apply_overrides(
        {col: row.get(col, "") for col in COLUMNS}, record, COLUMNS
    )
