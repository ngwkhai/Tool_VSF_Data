"""Test profile ACCOM — POI lưu trú, 72 cột.

Đối xứng với `test_schema.py` (profile FOOD). Giá trị mong đợi lấy từ dòng dữ
liệu mẫu do người dùng cung cấp (POI "Lucky Sun Hotel Nha Trang Beach").
"""

from __future__ import annotations

import json

from vsf.config import profile_settings
from vsf.models import POIRecord
from vsf.profiles import get_profile
from vsf.profiles.accom import (
    COLUMNS,
    PROFILE_FIELDS,
    STEPS,
    room_price_json,
    star_rating_from_label,
)
from vsf.profiles.food import COLUMNS as FOOD_COLUMNS
from vsf.schema import build_row, classify_l1, normalize_l2, price_level_for

CAT = profile_settings("accom")["category"]
DEFAULTS = profile_settings("accom")["dataset"]


# -- Bộ cột ----------------------------------------------------------------


def test_column_count_and_order_match_dataset():
    assert len(COLUMNS) == 72
    assert COLUMNS[0] == "poi_id"
    assert COLUMNS[-1] == "raw_gallery_urls"
    # Vài mốc giữa để phát hiện nếu ai đó sắp xếp lại cột.
    assert COLUMNS[6] == "star_rating"
    assert COLUMNS[16] == "room_price"
    assert COLUMNS[COLUMNS.index("lat") + 1] == "long"


def test_food_only_columns_are_gone():
    """11 cột món ăn không được lẫn sang dataset lưu trú."""
    for col in (
        "cuisine_type", "must_try_dishes", "menu", "price_per_person_avg",
        "seating_capacity", "dietary_options", "reservation_required",
        "dress_code", "alcohol_served",
    ):
        assert col not in COLUMNS, col


def test_unused_image_columns_are_dropped_not_kept_blank():
    """`cover_image_url`/`gallery_urls` vốn LUÔN trống ở FOOD -> bỏ hẳn ở ACCOM.

    Ảnh vẫn đi vào `raw_*` như cũ.
    """
    assert "cover_image_url" not in COLUMNS
    assert "gallery_urls" not in COLUMNS
    assert "raw_cover_image_url" in COLUMNS
    assert "raw_gallery_urls" in COLUMNS


def test_column_diff_against_food_is_exactly_what_we_intended():
    assert [c for c in FOOD_COLUMNS if c not in COLUMNS] == [
        "cuisine_type", "must_try_dishes", "menu", "price_per_person_avg",
        "seating_capacity", "dietary_options", "reservation_required",
        "dress_code", "alcohol_served", "cover_image_url", "gallery_urls",
    ]
    assert [c for c in COLUMNS if c not in FOOD_COLUMNS] == [
        "star_rating", "room_types", "total_rooms", "check_in_time",
        "check_out_time", "key_amenities", "breakfast_included", "pet_friendly",
        "brand_chain", "room_price",
    ]


def test_steps_swap_menu_for_rooms():
    """Khách sạn không có mục "Thực đơn" trên Google Maps -> không có bước menu."""
    assert STEPS == ["maps", "gemini1", "old_address", "rooms", "tiktok", "facebook"]
    assert "menu" not in STEPS


def test_every_gemini_field_has_a_home_in_the_dataset():
    """Hỏi Gemini một trường rồi không có cột nào nhận là hỏi thừa."""
    for field in PROFILE_FIELDS:
        assert field in COLUMNS, field


# -- Hạng sao --------------------------------------------------------------


def test_star_rating_read_from_the_google_label():
    # Nhãn khách sạn có dấu chấm giữa ở đầu (span.mgr77e), xem gmaps.clean_category.
    assert star_rating_from_label("Khách sạn 4 sao") == "4 sao"
    assert star_rating_from_label("·Khách sạn 3 sao") == "3 sao"
    assert star_rating_from_label("Khách sạn 5 sao sang trọng") == "5 sao"


def test_star_rating_blank_when_the_place_has_no_class():
    """Homestay/villa không xếp hạng sao — để trống chứ không đoán."""
    assert star_rating_from_label("Homestay") == ""
    assert star_rating_from_label("Nhà nghỉ") == ""
    assert star_rating_from_label("") == ""


# -- Cổng phân loại: danh sách TRẮNG ---------------------------------------


def test_classify_l1_accepts_every_lodging_label():
    for raw in (
        "Khách sạn", "Khách sạn 4 sao", "Resort", "Khu nghỉ dưỡng",
        "Homestay", "Hostel", "Villa", "Nhà nghỉ", "Căn hộ dịch vụ",
    ):
        assert classify_l1(raw, CAT) == ("ACCOM", True), raw


def test_classify_l1_rejects_labels_outside_the_whitelist():
    """Chiều NGƯỢC với profile food: không trúng từ nào -> loại."""
    for raw in ("Quán cà phê", "Nhà hàng", "Quán ăn", "Bảo tàng", "Bãi biển"):
        assert classify_l1(raw, CAT) == ("OTHER", True), raw


def test_classify_l1_fails_open_when_label_missing():
    """Nhãn rỗng là lỗi selector, KHÔNG phải tín hiệu phân loại — như food."""
    assert classify_l1("", CAT) == ("ACCOM", False)
    assert classify_l1("   ", CAT) == ("ACCOM", False)


def test_classify_l1_matches_on_word_boundaries():
    """Cùng bài học với "spa" trong "spaghetti" ở profile food."""
    # "villa" là marker, nhưng không được khớp bên trong một từ dài hơn.
    assert classify_l1("Cầu Villager", CAT) == ("OTHER", True)


# -- category_l2 -----------------------------------------------------------


def test_normalize_l2_returns_canonical_spelling():
    assert normalize_l2("khách sạn", "", "", CAT) == "Khách sạn"
    assert normalize_l2("RESORT", "", "", CAT) == "Resort"
    assert normalize_l2("homestay", "", "", CAT) == "Homestay"


def test_normalize_l2_never_emits_a_food_label():
    """Nhãn của profile kia không bao giờ được lọt ra cột."""
    assert normalize_l2("Quán cà phê", "", "", CAT) in CAT["l2_values"]


def test_normalize_l2_prefers_the_more_specific_label():
    """"Khách sạn & Resort ABC" là resort — nhãn cụ thể thắng nhãn tổng quát."""
    assert normalize_l2(None, "Khách sạn & Resort", "", CAT) == "Resort"


def test_normalize_l2_infers_from_google_label_then_name():
    assert normalize_l2(None, "Homestay", "", CAT) == "Homestay"
    assert normalize_l2(None, "", "Villa Biển Xanh", CAT) == "Villa"
    # Nhãn Google xét TRƯỚC tên, cùng lý do với profile food.
    assert normalize_l2(None, "Nhà nghỉ", "Resort Paradise", CAT) == "Nhà nghỉ"


def test_normalize_l2_falls_back_to_hotel():
    assert normalize_l2(None, "", "Lucky Sun Nha Trang", CAT) == "Khách sạn"


# -- Bảng giá phòng --------------------------------------------------------


def _rooms_raw() -> str:
    return """Đây là bảng giá:
```json
[
  {"loai_phong": "Superior", "ten": "Phòng Superior Giường Đôi", "gia": "821"},
  {"loai_phong": "Deluxe", "ten": "Phòng Deluxe Hướng Biển", "gia": "990"},
  {"loai_phong": "Suite", "ten": "Phòng Suite Hướng Biển", "gia": "1750"}
]
```"""


def test_room_price_strips_gemini_preamble_and_fence():
    record = POIRecord(poi_name="X", profile="accom")
    record.rooms = {"extracted": {"_raw": _rooms_raw()}}
    parsed = json.loads(room_price_json(record))
    assert [r["loai_phong"] for r in parsed] == ["Superior", "Deluxe", "Suite"]
    assert [r["gia"] for r in parsed] == ["821", "990", "1750"]


def test_room_price_collapses_a_range_to_its_lower_bound():
    record = POIRecord(poi_name="X", profile="accom")
    record.rooms = {"extracted": {"_raw": '[{"loai_phong":"A","ten":"B","gia":"900 - 1200"}]'}}
    assert json.loads(room_price_json(record))[0]["gia"] == "900"


def test_room_price_degroups_comma_formatted_prices():
    """Gemini trả "1,030,000" thay vì "1030" -> quy đổi, không đọc thành "1"."""
    record = POIRecord(poi_name="X", profile="accom")
    record.rooms = {"extracted": {"_raw": '[{"loai_phong":"A","ten":"B","gia":"1,030,000"}]'}}
    assert json.loads(room_price_json(record))[0]["gia"] == "1030"


def test_room_price_maps_geminis_alternate_keys():
    record = POIRecord(poi_name="X", profile="accom")
    record.rooms = {
        "extracted": {"_raw": '[{"room_type":"Deluxe","name":"Deluxe King","price":1030000}]'}
    }
    item = json.loads(room_price_json(record))[0]
    assert item == {"loai_phong": "Deluxe", "ten": "Deluxe King", "gia": "1030"}


# -- Mức giá ---------------------------------------------------------------


def test_price_level_uses_per_night_thresholds_not_per_meal():
    """Thang giá bữa ăn (150k/500k) áp cho một đêm thì mọi khách sạn là luxury."""
    levels = CAT["price_levels"]
    assert price_level_for(500_000, levels) == "budget"
    assert price_level_for(1_500_000, levels) == "mid-range"
    assert price_level_for(3_000_000, levels) == "luxury"


# -- Dựng nguyên một dòng --------------------------------------------------


def _sample_record() -> POIRecord:
    record = POIRecord(poi_name="Lucky Sun Hotel Nha Trang Beach", profile="accom")
    record.gemini_profile = {
        # "gần biển" KHÔNG có trong tags_values -> phải bị lọc bỏ.
        "tags": ["gần biển", "khách sạn", "sát biển", "cặp đôi"],
        "star_rating": "3 sao",  # sẽ bị nhãn Google (4 sao) ghi đè
        "room_types": ["Superior", "Deluxe", "Suite"],
        "total_rooms": "80 phòng",
        "check_in_time": "14:00",
        "check_out_time": "11:30",
        "key_amenities": ["hồ bơi trong nhà", "phòng gym", "Wi-Fi"],
        "breakfast_included": "có",
        "pet_friendly": "không",
        "view_type": ["biển", "thành phố"],
        "brand_chain": "Lucky Sun Hotel",
        "booking_required": "có",
        "estimated_duration": "2-5 đêm",
        "suitable_for": "cặp đôi; gia đình có trẻ em; khách quốc tế",
        "not_suitable_for": "khách mang theo thú cưng; khách tìm phòng siêu rẻ",
        "description_short": "Khách sạn 4 sao gần Trần Phú.",
        "weather_dependency": "Thấp",
    }
    record.rooms = {"extracted": {"_raw": _rooms_raw()}}
    record.google_maps = {
        "name": "Lucky Sun Hotel Nha Trang Beach",
        "category_raw": "Khách sạn 4 sao",
        "lat": 12.2258,
        "long": 109.2000,
        "place_id": "ChIJYeOaSmdhcDERIUrnIkft-LE",
        "address": "100/8B Trần Phú, Lộc Thọ, Nha Trang, Khánh Hòa, Việt Nam",
        "phone": "0792808888",
        "rating": 4.4,
        "review_count": 855,
        "hours": {"by_day": {
            "Thứ Hai": {"open": "0:00", "close": "23:59"},
            "Thứ Ba": {"open": "0:00", "close": "23:59"},
        }},
        "photos": {"hero": "https://lh3.googleusercontent.com/a=w1080-h1080-p-k-no"},
        "gallery_candidates": {"images": [
            "https://lh3.googleusercontent.com/a=w1080-h1080-p-k-no",
            "https://lh3.googleusercontent.com/b=w1080-h1080-p-k-no",
            "https://lh3.googleusercontent.com/c=w1080-h1080-p-k-no",
            "https://lh3.googleusercontent.com/d=w1080-h1080-p-k-no",
        ]},
        "reviews": {
            "positive": [{"text": "Phòng sạch, view biển đẹp."}],
            "negative": [{"text": "Đồ ăn sáng chưa được nhiều món."}],
        },
    }
    record.category_l1 = "ACCOM"
    return record


def test_build_row_produces_every_column_exactly_once():
    row = build_row(_sample_record())
    assert list(row) == COLUMNS
    assert len(row) == 72


def test_build_row_fills_the_lodging_columns():
    row = build_row(_sample_record())
    assert row["category_l1"] == "ACCOM"
    assert row["category_l2"] == "Khách sạn"
    assert row["room_types"] == "Superior, Deluxe, Suite"
    assert row["total_rooms"] == "80"
    assert row["check_in_time"] == "14:00"
    assert row["check_out_time"] == "11:30"
    assert row["breakfast_included"] == "TRUE"
    assert row["pet_friendly"] == "FALSE"
    assert row["booking_required"] == "TRUE"
    assert row["view_type"] == "biển, thành phố"
    assert row["brand_chain"] == "Lucky Sun Hotel"
    assert row["key_amenities"] == "hồ bơi trong nhà, phòng gym, Wi-Fi"


def test_build_row_prefers_the_google_star_rating_over_geminis():
    """Nhãn Google lấy từ hồ sơ cơ sở lưu trú; Gemini chỉ là suy đoán."""
    record = _sample_record()
    assert record.gemini_profile["star_rating"] == "3 sao"
    assert build_row(record)["star_rating"] == "4 sao"


def test_build_row_falls_back_to_gemini_when_google_has_no_star():
    record = _sample_record()
    record.google_maps["category_raw"] = "Homestay"
    assert build_row(record)["star_rating"] == "3 sao"


def test_price_min_max_come_from_the_room_price_table():
    """Đúng cách profile food suy price_min/max từ thực đơn."""
    row = build_row(_sample_record())
    assert row["price_min"] == "821,000"
    assert row["price_max"] == "1,750,000"
    # Mức giá xét theo phòng RẺ NHẤT — khách gặp mức đó trước.
    assert row["price_level"] == "mid-range"


def test_build_row_keeps_hotel_hours_separate_from_checkin_times():
    row = build_row(_sample_record())
    assert (row["open_time"], row["close_time"]) == ("0:00", "23:59")
    assert (row["check_in_time"], row["check_out_time"]) == ("14:00", "11:30")


def test_build_row_puts_images_in_raw_columns_only():
    row = build_row(_sample_record())
    assert row["raw_cover_image_url"].endswith("a=w1080-h1080-p-k-no")
    # Ảnh #1 của mục "Tất cả" CHÍNH LÀ ảnh đại diện -> bị loại khỏi ảnh phụ.
    assert row["raw_gallery_urls"].count(",") == 2
    assert "a=w1080" not in row["raw_gallery_urls"]


def test_build_row_uses_shared_address_and_comment_rules():
    row = build_row(_sample_record())
    assert row["city"] == "Khánh Hoà"
    assert row["region"] == "Nam Trung Bộ"
    assert row["dest"] == "thanh_pho_nha_trang"
    assert row["phone"] == '="0792808888"'
    assert row["positive_comments"] == "Phòng sạch, view biển đẹp."
    assert row["negative_comments"] == "Đồ ăn sáng chưa được nhiều món."


def test_confidence_level_always_comes_from_defaults():
    record = _sample_record()
    record.gemini_profile["confidence_level"] = "thấp"
    assert build_row(record)["confidence_level"] == DEFAULTS["confidence_level"]


def test_build_row_stubs_everything_but_name_for_a_non_lodging_poi():
    record = _sample_record()
    record.category_l1 = "OTHER"
    row = build_row(record)
    assert list(row) == COLUMNS
    assert row["category_l1"] == "OTHER"
    assert row["name"] == "Lucky Sun Hotel Nha Trang Beach"
    assert all(v == "" for k, v in row.items() if k not in ("category_l1", "name"))


def test_build_row_survives_missing_steps():
    """Chỉ chạy `maps` xong đã phải xuất được dòng, không ném lỗi."""
    bare = POIRecord(poi_name="Khách sạn Chưa Cào", profile="accom")
    row = build_row(bare)
    assert list(row) == COLUMNS
    assert row["name"] == "Khách sạn Chưa Cào"


def test_overrides_apply_last_and_reject_food_columns():
    record = _sample_record()
    record.overrides = {"price_min": "500,000", "menu": "phải bị bỏ qua"}
    row = build_row(record)
    assert row["price_min"] == "500,000"
    assert "menu" not in row


# -- Hai profile sống chung ------------------------------------------------


def test_a_legacy_record_without_a_profile_key_stays_food():
    """141 data.json cũ không có khoá `profile` -> vẫn xuất đúng 73 cột FOOD."""
    record = POIRecord(poi_name="Quán Cũ")
    assert record.profile == "food"
    assert list(build_row(record)) == FOOD_COLUMNS


def test_each_profile_builds_its_own_column_set():
    food = POIRecord(poi_name="A")
    accom = POIRecord(poi_name="B", profile="accom")
    assert len(build_row(food)) == 73
    assert len(build_row(accom)) == 72


def test_unknown_profile_name_fails_loudly():
    try:
        get_profile("khach_san")
    except KeyError as exc:
        assert "food" in str(exc) and "accom" in str(exc)
    else:
        raise AssertionError("phải báo lỗi thay vì im lặng rơi về food")


# -- matched_intents --------------------------------------------------------

INTENTS = CAT["matched_intents_values"]


def test_intents_whitelist_has_the_eighteen_values():
    assert len(INTENTS) == 18
    assert "Nghỉ dưỡng, thư giãn" in INTENTS
    assert "Đi cùng thú cưng" in INTENTS


def test_intents_keeps_labels_that_contain_a_comma():
    """Hai nhãn có dấu phẩy BÊN TRONG — tách theo dấu phẩy là vỡ chúng."""
    from vsf.schema import normalize_intents

    got = normalize_intents("Nghỉ dưỡng, thư giãn; Ghé nhanh, tiện đường", INTENTS)
    assert got == "Nghỉ dưỡng, thư giãn, Ghé nhanh, tiện đường"


def test_intents_survive_a_parser_that_already_split_on_commas():
    """Bản ghi cũ đã bị parser tách mất dấu phẩy -> vẫn phải ghép lại được."""
    from vsf.schema import normalize_intents

    assert normalize_intents(["Nghỉ dưỡng", "thư giãn"], INTENTS) == "Nghỉ dưỡng, thư giãn"


def test_intents_reject_search_queries():
    """Lỗi thật đã gặp: Gemini trả câu tìm kiếm thay vì nhãn ý định."""
    from vsf.schema import normalize_intents

    assert normalize_intents(
        "Đặt khách sạn giá rẻ Nha Trang, tìm khách sạn phố Tây Nha Trang", INTENTS
    ) == ""


def test_intents_match_without_diacritics_and_keep_config_spelling():
    from vsf.schema import normalize_intents

    assert normalize_intents("trang mat, cong tac", INTENTS) == "Trăng mật, Công tác"


def test_a_longer_intent_is_not_eaten_by_a_shorter_one():
    from vsf.schema import normalize_intents

    got = normalize_intents("Nghỉ dưỡng tại chỗ không di chuyển xa", INTENTS)
    assert got == "Nghỉ dưỡng tại chỗ không di chuyển xa"


def test_matched_intents_is_not_split_by_the_parser():
    """`matched_intents` phải ở NGOÀI LIST_FIELDS, xem lý do ở accom.py."""
    from vsf.profiles.accom import LIST_FIELDS

    assert "matched_intents" not in LIST_FIELDS


def test_build_row_filters_matched_intents():
    record = _sample_record()
    record.gemini_profile["matched_intents"] = "Công tác; Đặt phòng giá rẻ; Trăng mật"
    assert build_row(record)["matched_intents"] == "Công tác, Trăng mật"


def test_prompt_states_the_sentence_counts_and_the_intent_list():
    prompt = profile_settings("accom")["gemini"]["profile_prompt"]
    assert "description_short: ĐÚNG 2 CÂU" in prompt
    assert "description_long: ĐÚNG 5 CÂU" in prompt
    assert "{matched_intents_values}" in prompt


# -- Bộ giá trị đóng của tags / suitable_for / not_suitable_for / view_type ---
#
# Bốn cột này cùng cơ chế với matched_intents: người gán nhãn chốt trước danh
# sách được phép chọn (bảng ACCOM), config là nguồn sự thật cho CẢ prompt Gemini
# lẫn bộ lọc ở tầng xuất.

VOCAB_COLUMNS = {
    "tags": 22,
    "suitable_for": 16,
    "not_suitable_for": 10,
    "view_type": 6,
}


def test_every_vocab_column_declares_its_whitelist():
    for col, size in VOCAB_COLUMNS.items():
        values = CAT[f"{col}_values"]
        assert len(values) == size, col
        # Chép nguyên văn từ bảng gốc: không cắt dấu cách hai đầu, không rỗng.
        assert all(v == v.strip() and v for v in values), col


def test_vocab_whitelists_hold_the_values_from_the_sheet():
    assert "cao cấp / 5 sao/ sang trọng" in CAT["tags_values"]
    assert "khách đi một mình / tự túc" in CAT["suitable_for_values"]
    assert (
        "khách đòi hỏi resort có bãi biển riêng khép kín"
        in CAT["not_suitable_for_values"]
    )
    assert "attraction_view" in CAT["view_type_values"]


def test_vocab_columns_drop_labels_gemini_invented():
    """Nhãn tự nghĩ không bao giờ ra tới cột, nhưng vẫn còn trong data.json."""
    from vsf.schema import normalize_vocab

    got = normalize_vocab("sát biển; sang chảnh; bbq", CAT["tags_values"])
    assert got == "sát biển, bbq"


def test_vocab_matching_survives_a_slash_written_any_way():
    from vsf.schema import normalize_vocab

    for written in ("spa / trị liệu", "spa/trị liệu", "spa - tri lieu"):
        assert normalize_vocab(written, CAT["tags_values"]) == "spa / trị liệu"


def test_a_nested_suitable_for_label_is_not_eaten_by_a_shorter_one():
    """"gia đình" nằm TRONG "gia đình có trẻ em" và "đại gia đình"."""
    from vsf.schema import normalize_vocab

    values = CAT["suitable_for_values"]
    assert normalize_vocab("gia đình có trẻ em", values) == "gia đình có trẻ em"
    assert normalize_vocab("đại gia đình", values) == "đại gia đình"
    got = normalize_vocab("gia đình; gia đình có trẻ em", values)
    assert got == "gia đình, gia đình có trẻ em"


def test_short_vocab_labels_need_a_word_boundary():
    """"núi"/"bbq" rất ngắn — khớp chuỗi con trần thì lọt vào giữa từ khác."""
    from vsf.schema import normalize_vocab

    assert normalize_vocab("bbqx nuim", CAT["view_type_values"]) == ""
    assert normalize_vocab("núi", CAT["view_type_values"]) == "núi"


def test_build_row_filters_all_four_vocab_columns():
    row = build_row(_sample_record())
    assert row["tags"] == "khách sạn, sát biển, cặp đôi"
    assert row["suitable_for"] == "cặp đôi, gia đình có trẻ em, khách quốc tế"
    assert (
        row["not_suitable_for"]
        == "khách mang theo thú cưng, khách tìm phòng siêu rẻ"
    )
    assert row["view_type"] == "biển, thành phố"


def test_prompt_offers_the_allowed_values_for_every_vocab_column():
    for prompt_key in ("profile_prompt", "fill_missing_prompt"):
        prompt = profile_settings("accom")["gemini"][prompt_key]
        for col in VOCAB_COLUMNS:
            assert f"{{{col}_values}}" in prompt, (prompt_key, col)


def test_pipeline_feeds_every_declared_vocab_into_the_prompt():
    """Khai thêm `<cột>_values` trong config là prompt có ô đó ngay."""
    from vsf.pipeline import _vocab_clauses

    clauses = _vocab_clauses(CAT)
    for col in VOCAB_COLUMNS:
        assert f'"{CAT[f"{col}_values"][0]}"' in clauses[f"{col}_values"]
    # food chỉ khai l2_values -> không dư ô nào khiến str.format vỡ.
    food_cat = profile_settings("food")["category"]
    assert set(_vocab_clauses(food_cat)) == {"l2_values"}
    profile_settings("food")["gemini"]["profile_prompt"].format(
        poi="X", address_clause="", n_fields=26, **_vocab_clauses(food_cat)
    )
