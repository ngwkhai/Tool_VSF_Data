from pathlib import Path

from vsf.models import PROFILE_FIELDS, parse_profile_block, slugify

# Text thật lấy từ chính chat Gemini #1 của người dùng (recon 2026-08-11).
REAL = (Path(__file__).parent / "fixtures" / "gemini_profile_real.txt").read_text(
    encoding="utf-8"
)

# Khối text thật do Gemini chat #1 trả về (mẫu người dùng cung cấp).
SAMPLE = """tags: bánh canh chả cá, lòng cá, bình dân, ăn xế, ăn vặt, ẩm thực vỉa hè, nha trang
cuisine_type: Ẩm thực đường phố, Đặc sản Nha Trang
price_per_person_avg: 35.000 VNĐ
dietary_options: Chứa thành phần cá biển và nội tạng cá, không phù hợp cho người ăn chay hoặc bị dị ứng hải sản
dress_code: casual
view_type: Hướng phố
operating_note: Quán chủ yếu bán vào tầm trưa đến chiều tối, thường rất nhanh hết lòng cá và trứng cá nếu đến muộn
description_short: Bánh Canh Trần Văn Ơn là tọa độ ẩm thực vỉa hè nức tiếng tại Nha Trang.
description_long: Nằm bình dị trên đường Trần Văn Ơn, quán bánh canh này từ lâu đã trở thành
điểm đến "ruột" của vô số học sinh, sinh viên và người dân địa phương tại Nha Trang.
best_time_to_visit: Buổi chiều từ 14:30 đến 17:00
estimated_duration: 30 - 45 phút
suitable_for: Học sinh, sinh viên, người dân địa phương
not_suitable_for: Người ăn chay, người bị dị ứng hải sản
insider_tips: Lòng cá và trứng cá ở quán rất thơm và nhanh hết
weather_dependency: Mức độ ảnh hưởng cao, chỗ ngồi vỉa hè
crowd_level_note: Quán cực kỳ đông vào giờ tan tầm buổi chiều (16:00 - 17:30)
matched_intents: Ăn xế Nha Trang, ăn bánh canh chả cá ngon rẻ
search_keywords: bánh canh trần văn ơn nha trang, bánh canh lòng cá trần văn ơn
"""


def test_parses_every_expected_field():
    result = parse_profile_block(SAMPLE)
    assert result["price_per_person_avg"] == "35.000 VNĐ"
    assert result["dress_code"] == "casual"


def test_list_fields_split_on_comma():
    result = parse_profile_block(SAMPLE)
    assert result["tags"][0] == "bánh canh chả cá"
    assert "nha trang" in result["tags"]
    assert len(result["cuisine_type"]) == 2


def test_multiline_value_is_joined():
    result = parse_profile_block(SAMPLE)
    assert result["description_long"].startswith("Nằm bình dị")
    assert result["description_long"].endswith("tại Nha Trang.")


def test_raw_is_always_kept():
    assert parse_profile_block(SAMPLE)["_raw"] == SAMPLE


def test_unknown_fields_go_to_extra_not_lost():
    result = parse_profile_block(SAMPLE + "weather_note: mưa thì bất tiện\n")
    assert result["extra"]["weather_note"] == "mưa thì bất tiện"


def test_missing_fields_are_reported_not_silently_dropped():
    result = parse_profile_block("tags: a, b\ndress_code: casual\n")
    assert "description_long" in result["_missing_fields"]


# -- Gemini's fixed grounding-tool template (không đổi được bằng prompt) ----


def test_field_aliases_map_geminis_fixed_business_card_keys():
    # Xác nhận bằng thực nghiệm 2026-08-14: khi tính năng grounding/tìm kiếm
    # địa điểm của Gemini kích hoạt, nó LUÔN trả về đúng bộ khoá cố định này
    # (name/address/phone/rating/opening_hours/famous_dishes/price_range/...)
    # bất kể prompt yêu cầu dùng PROFILE_FIELDS rõ ràng đến đâu — không phải
    # lỗi định dạng ngẫu nhiên mà là template nội bộ không đổi được.
    raw = (
        "famous_dishes: Bún chả, Phở bò\n"
        "price_range: Bình dân (30.000 – 70.000 VNĐ)\n"
        "reservation: Có hỗ trợ đặt bàn\n"
        "ambiance: Thoáng mát, sạch sẽ\n"
        "service_style: Thân thiện, nhanh chóng\n"
    )
    result = parse_profile_block(raw)
    assert result["must_try_dishes"] == ["Bún chả", "Phở bò"]
    assert result["price_per_person_avg"] == "Bình dân (30.000 – 70.000 VNĐ)"
    assert result["reservation_required"] == "Có hỗ trợ đặt bàn"
    assert result["description_short"] == "Thoáng mát, sạch sẽ"
    assert result["operating_note"] == "Thân thiện, nhanh chóng"
    assert "_missing_fields" not in result or "must_try_dishes" not in result["_missing_fields"]


def test_field_aliases_leave_unmappable_keys_in_extra():
    # name/address/phone/rating/opening_hours trùng dữ liệu Google Maps đã có;
    # payment_methods/parking/social_media/... không có trường tương ứng trong
    # schema — cả hai loại phải rơi vào `extra`, không bị âm thầm mất.
    raw = "name: Quán Mẫu\npayment_methods: Tiền mặt\n"
    result = parse_profile_block(raw)
    assert result["extra"] == {"name": "Quán Mẫu", "payment_methods": "Tiền mặt"}


def test_canonical_key_wins_over_alias_when_both_present():
    raw = "must_try_dishes: Món thật\nfamous_dishes: Món giả từ alias\n"
    result = parse_profile_block(raw)
    assert result["must_try_dishes"] == ["Món thật"]


# -- Trên dữ liệu thật từ Gemini ------------------------------------------


# Các trường thread Gemini #1 vốn đã trả về (bản ghi thật ngày 2026-08-11).
LEGACY_FIELDS = [
    "tags", "cuisine_type", "price_per_person_avg", "dietary_options",
    "dress_code", "view_type", "operating_note", "description_short",
    "description_long", "best_time_to_visit", "estimated_duration",
    "suitable_for", "not_suitable_for", "insider_tips", "weather_dependency",
    "crowd_level_note", "matched_intents", "search_keywords",
]

# Các trường schema dataset cần thêm, chưa có trong bản ghi cũ.
SCHEMA_ONLY_FIELDS = [
    "name_en", "category_l2", "must_try_dishes", "seating_capacity",
    "reservation_required", "alcohol_served", "confidence_level",
    "info_expiry_note",
]


def test_profile_fields_cover_both_legacy_and_schema_needs():
    assert set(PROFILE_FIELDS) == set(LEGACY_FIELDS) | set(SCHEMA_ONLY_FIELDS)


def test_real_response_yields_every_legacy_field():
    result = parse_profile_block(REAL)
    assert all(result.get(f) for f in LEGACY_FIELDS)
    assert result.get("extra") is None, "có trường lạ chưa khai báo: %s" % result.get("extra")


def test_real_response_reports_schema_fields_as_missing():
    # Bản ghi cũ chưa có các trường schema mới -> phải báo thiếu để pipeline biết
    # mà gửi prompt định dạng lại, chứ không im lặng bỏ qua.
    missing = parse_profile_block(REAL)["_missing_fields"]
    assert set(missing) == set(SCHEMA_ONLY_FIELDS)


def test_real_response_weather_dependency_not_swallowed_by_insider_tips():
    # Trường này từng bị dính vào insider_tips khi copy tay -> phải tách đúng.
    result = parse_profile_block(REAL)
    assert result["weather_dependency"].startswith("Mức độ ảnh hưởng cao")
    assert "Mức độ ảnh hưởng" not in result["insider_tips"]
    assert result["insider_tips"].endswith("cay nồng.")


def test_real_response_long_description_kept_whole():
    result = parse_profile_block(REAL)
    assert len(result["description_long"]) > 500
    assert result["description_long"].endswith("tấp nập người ra vào.")


def test_real_response_list_fields():
    result = parse_profile_block(REAL)
    assert len(result["tags"]) == 7
    assert len(result["search_keywords"]) == 5
    assert result["search_keywords"][-1] == "ăn vặt chiều nha trang"


def test_slugify_strips_vietnamese_diacritics():
    assert slugify("Bánh Canh Trần Văn Ơn") == "banh-canh-tran-van-on"
    assert slugify("Quán Đủ Đầy") == "quan-du-day"
