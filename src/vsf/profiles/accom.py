"""Profile ACCOM — POI lưu trú, 72 cột.

Cấu hình đi kèm: `config/profile_accom.toml`.
Phần dùng chung với profile đồ ăn nằm ở `vsf.schema`.

So với FOOD: bỏ 11 cột món ăn (`cuisine_type`, `must_try_dishes`, `menu`,
`price_per_person_avg`, `seating_capacity`, `dietary_options`,
`reservation_required`, `dress_code`, `alcohol_served`, và hai cột ảnh
`cover_image_url`/`gallery_urls` vốn luôn để trống), thêm 10 cột phòng ốc ở
đúng chỗ khối cũ. `view_type` có ở cả hai.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .. import schema
from ..models import POIRecord

# Thứ tự cột PHẢI khớp tuyệt đối với dataset. Đừng sắp xếp lại.
COLUMNS = [
    "poi_id", "category_l1", "name", "name_en", "category_l2", "tags",
    "star_rating", "room_types", "total_rooms", "check_in_time", "check_out_time",
    "key_amenities", "breakfast_included", "pet_friendly", "view_type",
    "brand_chain", "room_price", "lat", "long", "old_address", "address",
    "ward", "city", "region", "place_id", "distance_from_reference_km",
    "reference_point", "open_time", "close_time", "phone", "contact",
    "operating_note", "price_min", "price_max", "price_level", "booking_required",
    "booking_source", "rating_score", "review_count", "rating_source",
    "positive_comments", "negative_comments",
    "description_short", "description_long", "best_time_to_visit",
    "estimated_duration", "suitable_for", "not_suitable_for", "insider_tips",
    "source_url", "video_posted_date", "verified_date", "confidence_level",
    "info_expiry_note", "nearby_poi_ids", "complementary_poi_ids",
    "alternative_poi_ids", "weather_dependency", "crowd_level_note",
    "matched_intents", "search_keywords", "nearby_hotel_ids", "status",
    "labeled_by", "review_status", "reviewer_note", "last_updated", "by_pass",
    "dest", "raw_url", "raw_cover_image_url", "raw_gallery_urls",
]

# `menu` -> `rooms`: khách sạn không có tab "Thực đơn" trên Google Maps để chụp
# ảnh, nên bước này không dán ảnh mà để Gemini #2 tra bảng giá phòng trên web.
STEPS = ["maps", "gemini1", "old_address", "rooms", "tiktok", "facebook"]

# 28 trường hỏi Gemini #1 trong MỘT lượt. Thứ tự phải khớp biểu mẫu trong
# [gemini] profile_prompt của config/profile_accom.toml.
PROFILE_FIELDS = [
    "name_en",
    "category_l2",
    "tags",
    "star_rating",
    "room_types",
    "total_rooms",
    "check_in_time",
    "check_out_time",
    "key_amenities",
    "breakfast_included",
    "pet_friendly",
    "view_type",
    "brand_chain",
    "booking_required",
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

# `matched_intents`, `suitable_for`, `not_suitable_for` CỐ Ý không nằm ở đây:
# nhãn hợp lệ của chúng có dấu phẩy BÊN TRONG ("Nghỉ dưỡng, thư giãn", "Ghé
# nhanh, tiện đường"), để parser tách theo dấu phẩy là vỡ chúng ngay trước khi
# schema.normalize_vocab kịp nhìn thấy. Giữ nguyên chuỗi thô, bộ lọc tự quét
# nhãn ra khỏi nó.
#
# `tags` và `view_type` thì ở LẠI đây dù cũng qua normalize_vocab: nhãn của
# chúng không có dấu phẩy bên trong nên tách được an toàn, và data.json giữ dạng
# danh sách thì dễ rà bằng mắt hơn. normalize_vocab ghép lại trước khi quét nên
# nằm trong hay ngoài đều ra cùng một kết quả.
LIST_FIELDS = frozenset(
    {
        "tags",
        "search_keywords",
        "room_types",
        "key_amenities",
        "view_type",
    }
)

# Cùng hiện tượng "mẫu danh thiếp" như profile FOOD: Gemini tự kích hoạt template
# tra địa điểm và trả tên khoá của riêng nó. Khoá trùng dữ liệu Google Maps
# (name/address/phone/rating) cố ý bỏ vào `extra` thay vì ánh xạ.
FIELD_ALIASES = {
    "amenities": "key_amenities",
    "facilities": "key_amenities",
    "hotel_class": "star_rating",
    "stars": "star_rating",
    "rooms": "total_rooms",
    "number_of_rooms": "total_rooms",
    "check_in": "check_in_time",
    "check_out": "check_out_time",
    "chain": "brand_chain",
    "brand": "brand_chain",
    "ambiance": "description_short",
}

# Khoá thay thế cho bảng giá phòng — cùng lý do với _MENU_*_ALIASES ở profile
# FOOD: Gemini có template nội bộ riêng, ánh xạ lại rẻ hơn sửa prompt mãi.
_ROOM_NAME_ALIASES = ("ten", "name", "ten_phong", "room", "room_name")
_ROOM_TYPE_ALIASES = ("loai_phong", "room_type", "loai", "hang_phong", "category", "type")

_STAR = re.compile(r"(\d)\s*sao\b", re.IGNORECASE)


def star_rating_from_label(category_raw: str) -> str:
    """'·Khách sạn 4 sao' -> '4 sao'. Không có hạng sao thì chuỗi rỗng.

    Nhãn ngành Google là nguồn ĐÁNG TIN NHẤT cho hạng sao — nó lấy từ hồ sơ cơ
    sở lưu trú chứ không phải suy đoán, nên xét trước câu trả lời của Gemini.
    Lưu ý khách sạn KHÔNG có `button.DkEaL` như quán ăn: nhãn là text thường
    `span.mgr77e` kèm dấu chấm giữa ở đầu (xem gmaps.clean_category).
    """
    m = _STAR.search(category_raw or "")
    return f"{m.group(1)} sao" if m else ""


def _normalize_room_item(item: dict) -> dict:
    ten = next((item[k] for k in _ROOM_NAME_ALIASES if item.get(k)), "")
    loai = next((item[k] for k in _ROOM_TYPE_ALIASES if item.get(k)), "")

    gia = item.get("gia")
    if not gia:
        price = item.get("price")
        if isinstance(price, (int, float)):
            # Gemini thỉnh thoảng trả "price" là SỐ nguyên đầy đủ VNĐ (1030000)
            # thay vì chuỗi theo đơn vị nghìn — quy đổi để khớp quy ước dataset
            # (schema.menu_prices() luôn nhân 1000 khi đọc lại).
            gia = str(round(price / 1000))
        elif price:
            gia = price
        else:
            gia = ""

    return {"loai_phong": loai, "ten": ten, "gia": gia}


def room_price_json(record: POIRecord) -> str:
    """Khối JSON bảng giá phòng Gemini trả về, chuẩn hoá lại cho gọn."""
    raw = ((record.rooms or {}).get("extracted") or {}).get("_raw") or ""
    return schema.price_table_json(raw, _normalize_room_item)


def build_row(
    record: POIRecord,
    defaults: dict[str, Any],
    tiktok_index: int = 0,
    ward_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ánh xạ một POIRecord sang đúng 72 cột của dataset ACCOM."""
    from ..config import profile_settings

    maps = record.google_maps or {}
    category_cfg = profile_settings("accom")["category"]

    # POI không thuộc nhóm lưu trú -> dòng stub, y hệt cách profile FOOD loại
    # một khách sạn.
    l1 = getattr(record, "category_l1", "") or defaults.get("category_l1", "ACCOM")
    if l1 != category_cfg.get("l1_default", "ACCOM"):
        return schema.stub_row(record, l1, COLUMNS)

    profile = dict(record.gemini_profile or {})

    reviews = maps.get("reviews") or {}
    picked = schema.pick_video(record, tiktok_index)
    location = schema.resolved_address(maps, ward_map or {})
    address = location["address"]
    open_time, close_time = schema.modal_hours(maps)
    hero, gallery = schema.cover_and_gallery(maps)

    room_table = room_price_json(record)
    # price_min/price_max suy từ BẢNG GIÁ PHÒNG, đúng cách profile FOOD suy từ
    # thực đơn. Đây là con số kiểm chứng được, khác với một khoảng giá do Gemini
    # tự ước lượng; người gán nhãn muốn khác thì sửa qua override.
    price_min, price_max = schema.price_range(room_table)
    # Mức giá xét theo giá phòng RẺ NHẤT — đó là mức khách thực sự gặp khi tìm
    # phòng, còn giá trung bình bị mấy hạng suite kéo lệch lên.
    price_level = schema.price_level_for(price_min, category_cfg.get("price_levels", []))
    name = maps.get("name") or record.poi_name

    row = {
        "poi_id": "",
        "category_l1": l1,
        "name": name,
        "name_en": schema.english_name(profile.get("name_en"), name),
        "category_l2": getattr(record, "category_l2", "")
        or schema.normalize_l2(
            profile.get("category_l2"), maps.get("category_raw", ""), name, category_cfg
        ),
        # 5 cột dưới đây có BỘ GIÁ TRỊ ĐÓNG do người gán nhãn chốt (bảng ACCOM,
        # xem [category].*_values). Lọc bằng normalize_vocab chứ không join_list:
        # nhãn hợp lệ chứa dấu phẩy hoặc gạch chéo bên trong ("Nghỉ dưỡng, thư
        # giãn", "spa / trị liệu"), tách theo dấu phẩy là vỡ chúng — và nhãn
        # Gemini tự nghĩ ra thì không bao giờ được ra tới cột.
        "tags": schema.normalize_vocab(
            profile.get("tags"), category_cfg.get("tags_values", [])
        ),
        # Nhãn Google trước, Gemini là dự phòng.
        "star_rating": star_rating_from_label(maps.get("category_raw", ""))
        or (profile.get("star_rating") or ""),
        "room_types": schema.join_list(profile.get("room_types")),
        "total_rooms": schema.first_number(profile.get("total_rooms")),
        "check_in_time": profile.get("check_in_time") or "",
        "check_out_time": profile.get("check_out_time") or "",
        "key_amenities": schema.join_list(profile.get("key_amenities")),
        "breakfast_included": schema.boolean(profile.get("breakfast_included")),
        "pet_friendly": schema.boolean(profile.get("pet_friendly")),
        "view_type": schema.normalize_vocab(
            profile.get("view_type"), category_cfg.get("view_type_values", [])
        ),
        "brand_chain": profile.get("brand_chain") or "",
        "room_price": room_table,
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
        # Giờ mở/đóng của toà nhà (lễ tân), KHÔNG phải giờ nhận/trả phòng — hai
        # thứ đó là check_in_time/check_out_time, cột riêng.
        "open_time": open_time,
        "close_time": close_time,
        # Excel hiểu ="..." là công thức trả về chuỗi văn bản thuần — ép cột
        # thành text nên không mất số 0 đầu.
        "phone": f'="{maps["phone"]}"' if maps.get("phone") else "",
        "contact": "",
        "operating_note": profile.get("operating_note") or "",
        "price_min": schema.money(price_min),
        "price_max": schema.money(price_max),
        "price_level": price_level,
        "booking_required": schema.boolean(profile.get("booking_required")),
        "booking_source": defaults.get("booking_source", "internal"),
        "rating_score": str(maps.get("rating") or ""),
        "review_count": str(maps.get("review_count") or ""),
        "rating_source": defaults.get("rating_source", "Google Maps"),
        "positive_comments": schema.quoted_comments(reviews.get("positive") or []),
        "negative_comments": schema.quoted_comments(reviews.get("negative") or []),
        "description_short": profile.get("description_short") or "",
        "description_long": profile.get("description_long") or "",
        "best_time_to_visit": profile.get("best_time_to_visit") or "",
        "estimated_duration": profile.get("estimated_duration") or "",
        "suitable_for": schema.normalize_vocab(
            profile.get("suitable_for"), category_cfg.get("suitable_for_values", [])
        ),
        "not_suitable_for": schema.normalize_vocab(
            profile.get("not_suitable_for"),
            category_cfg.get("not_suitable_for_values", []),
        ),
        "insider_tips": profile.get("insider_tips") or "",
        "source_url": "",
        "video_posted_date": (picked.get("posted_at") or "")[:10],
        "verified_date": "",
        # Luôn lấy giá trị mặc định trong settings, KHÔNG dùng mức Gemini tự chấm.
        "confidence_level": defaults.get("confidence_level", ""),
        "info_expiry_note": profile.get("info_expiry_note")
        or defaults.get("info_expiry_note", ""),
        "nearby_poi_ids": "",
        "complementary_poi_ids": "",
        "alternative_poi_ids": "",
        "weather_dependency": profile.get("weather_dependency") or "",
        "crowd_level_note": profile.get("crowd_level_note") or "",
        "matched_intents": schema.normalize_vocab(
            profile.get("matched_intents"),
            category_cfg.get("matched_intents_values", []),
        ),
        "search_keywords": schema.join_list(profile.get("search_keywords")),
        "nearby_hotel_ids": "",
        "status": defaults.get("status", "active"),
        "labeled_by": defaults.get("labeled_by", ""),
        "review_status": defaults.get("review_status", "draft"),
        "reviewer_note": "",
        "last_updated": date.today().isoformat(),
        "by_pass": "FALSE",
        "dest": schema.slug_dest(location["city"], address),
        "raw_url": picked.get("url") or "",
        "raw_cover_image_url": hero,
        "raw_gallery_urls": ", ".join(gallery),
    }
    return schema.apply_overrides(
        {col: row.get(col, "") for col in COLUMNS}, record, COLUMNS
    )
