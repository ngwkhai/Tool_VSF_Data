"""Test tầng ánh xạ sang schema 73 cột.

Giá trị mong đợi lấy từ dòng dữ liệu ĐÚNG do người dùng cung cấp
(POI "Nha Trang Quán Xí Mộng").
"""

import json

from vsf.config import profile_settings
from vsf.profiles.food import COLUMNS
from vsf.schema import (
    boolean,
    build_row,
    classify_l1 as _classify_l1,
    money,
    normalize_l2 as _normalize_l2,
    parse_amount,
    price_level_for as _price_level_for,
    price_range as menu_price_range,
    quoted_comments,
    slug_dest,
    split_address,
)
from vsf.models import POIRecord

# Bộ phân loại và thang giá giờ là CỦA PROFILE, không còn hằng số cấp module.
# Bọc lại để phần thân test bên dưới vẫn đọc như cũ.
CAT = profile_settings("food")["category"]


def classify_l1(raw):
    return _classify_l1(raw, CAT)


def normalize_l2(value, category_raw="", name=""):
    return _normalize_l2(value, category_raw, name, CAT)


def price_level_for(avg):
    return _price_level_for(avg, CAT["price_levels"])


def test_column_count_and_order_match_dataset():
    assert len(COLUMNS) == 73
    assert COLUMNS[0] == "poi_id"
    assert COLUMNS[-1] == "raw_gallery_urls"
    # Vài mốc giữa để phát hiện nếu ai đó sắp xếp lại cột.
    assert COLUMNS[8] == "menu"
    assert COLUMNS[COLUMNS.index("lat") + 1] == "long"


# -- Tiền ------------------------------------------------------------------


def test_parse_amount_handles_dataset_formats():
    assert parse_amount("35.000 VNĐ") == 35000
    assert parse_amount("100,000") == 100000
    # Giá menu Google ghi theo nghìn: "150" nghĩa là 150.000đ.
    assert parse_amount("150") == 150000
    assert parse_amount(None) is None


def test_money_uses_comma_thousands_like_dataset():
    assert money(100000) == "100,000"
    assert money(40000) == "40,000"
    assert money(None) == ""


def test_price_level_thresholds():
    assert price_level_for(100000) == "budget"
    assert price_level_for(300000) == "mid-range"
    assert price_level_for(900000) == "luxury"


def test_menu_price_range_matches_sample_row():
    # Trích từ menu thật của Quán Xí Mộng: dòng mẫu ghi 40,000 - 160,000.
    menu = json.dumps([
        {"loai_thuc_pham": "Đặc biệt", "ten": "Cá nhúng giấm", "gia": "160"},
        {"loai_thuc_pham": "Khai vị", "ten": "Rau muống xào tỏi", "gia": "40"},
        {"loai_thuc_pham": "Cơm chiên", "ten": "Cơm chiên hải sản", "gia": "80-90"},
    ])
    low, high = menu_price_range(menu)
    assert money(low) == "40,000"
    assert money(high) == "160,000"


def test_menu_price_range_reads_both_ends_of_a_range():
    menu = json.dumps([{"ten": "Tôm nướng", "gia": "130-150"}])
    low, high = menu_price_range(menu)
    assert (low, high) == (130000, 150000)


# -- Địa chỉ ---------------------------------------------------------------


def test_split_address_matches_sample_row():
    parts = split_address("56X4+R5M, Nam Nha Trang, Khánh Hòa, Việt Nam")
    assert parts["ward"] == "Nam Nha Trang"
    # Dataset viết "Khánh Hoà" (oà), Google trả "Khánh Hòa" (òa) -> chuẩn hoá.
    assert parts["city"] == "Khánh Hoà"
    assert parts["region"] == "Nam Trung Bộ"


def test_split_address_strips_postal_code():
    parts = split_address("65XV+R7V, Xuong Huan, Nha Trang, Khánh Hòa 650000, Việt Nam")
    assert parts["city"] == "Khánh Hoà"
    assert parts["region"] == "Nam Trung Bộ"


def test_dest_slug_matches_sample_row():
    assert slug_dest("Khánh Hòa", "56X4+R5M, Nam Nha Trang, Khánh Hòa") == "thanh_pho_nha_trang"


# -- Bool và bình luận -----------------------------------------------------


def test_boolean_normalises_to_dataset_form():
    assert boolean("có") == "TRUE"
    assert boolean("Không") == "FALSE"
    assert boolean(True) == "TRUE"
    assert boolean(None) == ""


def test_quoted_comments_joins_each_as_separate_paragraph():
    out = quoted_comments([{"text": "Món ngon"}, {"text": "Giá rẻ"}])
    assert out == "Món ngon\nGiá rẻ"


def test_quoted_comments_skips_empty_reviews():
    # Bài chỉ chấm sao không viết gì thì không được tạo ra đoạn rỗng.
    assert quoted_comments([{"text": ""}, {"text": "Ngon"}]) == "Ngon"


def test_quoted_comments_collapses_newlines_within_one_review():
    # Xuống dòng BÊN TRONG 1 review (nhiều đoạn) -> khoảng trắng, không phải
    # ranh giới giữa 2 review. Chỉ ranh giới GIỮA các review mới xuống dòng.
    out = quoted_comments(
        [{"text": "Đoạn 1\n\nĐoạn 2"}, {"text": "Review khác"}]
    )
    assert out == "Đoạn 1 Đoạn 2\nReview khác"


# -- Dựng nguyên một dòng --------------------------------------------------


def _sample_record() -> POIRecord:
    record = POIRecord(poi_name="Nha Trang Quán Xí Mộng")
    record.gemini_profile = {
        "tags": ["hải sản nhím", "cà ri cá", "ăn tối"],
        "cuisine_type": ["Việt Nam", "Hải sản bình dân"],
        "must_try_dishes": ["Cá nhúng giấm", "Cá nóc nhím um cari"],
        "price_per_person_avg": "100.000 VNĐ",
        "seating_capacity": "60",
        "reservation_required": "không",
        "dress_code": "Casual",
        "alcohol_served": "không",
        "description_short": "Quán hải sản bình dân.",
        "weather_dependency": "Thấp",
    }
    record.google_maps = {
        "name": "Nha Trang Quán Xí Mộng",
        "lat": 12.1996,
        "long": 109.2054,
        "place_id": "ChIJYeOaSmdhcDERIUrnIkft-LE",
        "address": "56X4+R5M, Nam Nha Trang, Khánh Hòa, Việt Nam",
        "phone": "0972752724",
        "rating": 4.2,
        "review_count": 239,
        "hours": {"by_day": {
            "Thứ Hai": {"open": "15:30", "close": "23:00"},
            "Thứ Ba": {"open": "15:30", "close": "23:00"},
        }},
        "photos": {"hero": "https://lh3.googleusercontent.com/a=w1080-h1080-p-k-no",
                   "secondary": ["https://lh3.googleusercontent.com/b=w1080-h1080-p-k-no"]},
        "reviews": {"positive": [{"text": "Cá nóc um cà ri rất ngon."}],
                    "negative": [{"text": "Phục vụ chậm."}]},
    }
    record.menu = {"extracted": {"_raw": 'Kết quả:\n[{"ten": "Cá nhúng giấm", "gia": "160"}, {"ten": "Rau muống", "gia": "40"}]'}}
    record.tiktok = [{"url": "https://www.tiktok.com/@duytannnnnn/video/7650522822728617237",
                      "posted_at": "2026-06-29T10:00:00+00:00", "match_score": 1.0}]
    return record


DEFAULTS = {"category_l1": "FOOD", "status": "active",
            "review_status": "draft", "booking_source": "internal",
            "rating_source": "Google Maps", "labeled_by": "Khải"}


def test_build_row_produces_every_column_exactly_once():
    row = build_row(_sample_record(), DEFAULTS)
    assert list(row.keys()) == COLUMNS


def test_build_row_matches_sample_values():
    row = build_row(_sample_record(), DEFAULTS)
    assert row["category_l1"] == "FOOD"
    # category_l2 giờ tự điền, và phải là một trong 5 nhãn hợp lệ.
    assert row["category_l2"] in CAT["l2_values"]
    assert row["name"] == "Nha Trang Quán Xí Mộng"
    assert row["lat"] == "12.1996" and row["long"] == "109.2054"
    assert row["place_id"] == "ChIJYeOaSmdhcDERIUrnIkft-LE"
    assert row["ward"] == "Nam Nha Trang"
    assert row["city"] == "Khánh Hoà"
    assert row["region"] == "Nam Trung Bộ"
    assert row["open_time"] == "15:30" and row["close_time"] == "23:00"
    # ="..." là công thức Excel trả về text thuần, giữ số 0 đầu.
    assert row["phone"] == '="0972752724"'
    assert row["price_per_person_avg"] == "100,000"
    assert row["price_min"] == "40,000" and row["price_max"] == "160,000"
    assert row["price_level"] == "budget"
    assert row["rating_score"] == "4.2" and row["review_count"] == "239"
    assert row["rating_source"] == "Google Maps"
    assert row["reservation_required"] == "FALSE"
    assert row["alcohol_served"] == "FALSE"
    assert row["dress_code"] == "Casual"
    # seating_capacity để trống dù Gemini có trả về — Gemini chỉ đoán được.
    assert row["seating_capacity"] == ""
    assert row["dest"] == "thanh_pho_nha_trang"
    assert row["status"] == "active" and row["review_status"] == "draft"
    assert row["labeled_by"] == "Khải"
    assert row["by_pass"] == "FALSE"


def test_build_row_puts_images_in_raw_columns_only():
    # Dòng mẫu để cover_image_url/gallery_urls TRỐNG, chỉ điền raw_*.
    row = build_row(_sample_record(), DEFAULTS)
    assert row["cover_image_url"] == ""
    assert row["gallery_urls"] == ""
    assert row["raw_cover_image_url"].endswith("=w1080-h1080-p-k-no")
    assert "googleusercontent" in row["raw_gallery_urls"]


def test_build_row_uses_selected_tiktok_candidate():
    row = build_row(_sample_record(), DEFAULTS)
    assert row["raw_url"].endswith("/video/7650522822728617237")
    assert row["video_posted_date"] == "2026-06-29"


def test_build_row_menu_is_clean_json_without_gemini_preamble():
    row = build_row(_sample_record(), DEFAULTS)
    assert row["menu"].startswith("[")
    items = json.loads(row["menu"])
    assert items[0]["ten"] == "Cá nhúng giấm"


def test_build_row_survives_missing_steps():
    # Bước lỗi thì cột tương ứng để trống chứ không được ném lỗi.
    bare = POIRecord(poi_name="Quán chưa chạy xong")
    row = build_row(bare, DEFAULTS)
    assert row["name"] == "Quán chưa chạy xong"
    assert row["menu"] == "" and row["raw_url"] == "" and row["price_min"] == ""
    assert list(row.keys()) == COLUMNS


# -- Suy luận trường thiếu -------------------------------------------------


def test_signature_dishes_prefers_dac_biet_section():
    # Dòng mẫu: must_try = các món trong mục "Đặc biệt".
    menu = json.dumps([
        {"loai_thuc_pham": "Đặc biệt", "ten": "Cá nóc nhím um cari", "gia": "150"},
        {"loai_thuc_pham": "Đặc biệt", "ten": "Cá nhúng giấm", "gia": "160"},
        {"loai_thuc_pham": "Khai vị", "ten": "Đậu hũ chiên", "gia": "50"},
    ])
    from vsf.profiles.food import signature_dishes
    dishes = signature_dishes(menu)
    assert "Cá nóc nhím um cari" in dishes
    assert "Đậu hũ chiên" not in dishes


def test_signature_dishes_falls_back_to_priciest_items():
    from vsf.profiles.food import signature_dishes
    menu = json.dumps([
        {"loai_thuc_pham": "Ốc", "ten": "Ốc rẻ", "gia": "40"},
        {"loai_thuc_pham": "Tôm", "ten": "Tôm hùm", "gia": "1700"},
    ])
    assert signature_dishes(menu, limit=1) == ["Tôm hùm"]


def test_name_en_strips_diacritics():
    from vsf.schema import name_without_diacritics
    assert name_without_diacritics("Nha Trang Quán Xí Mộng") == "Nha Trang Quan Xi Mong"


def test_derive_missing_fills_gaps_without_overwriting():
    from vsf.profiles.food import derive_missing
    record = _sample_record()
    derived = derive_missing(record.gemini_profile, record)
    # Quán bình dân (100k/người) thì không cần đặt bàn.
    assert derived["reservation_required"] == "không"
    # name_en vẫn không tự suy — chỉ nhận tên tiếng Anh thật.
    assert "name_en" not in derived
    # category_l2 không suy ở đây mà ở normalize_l2: nó cần nhãn ngành Google,
    # thứ derive_missing không nhận vào.
    assert "category_l2" not in derived


def test_first_number_extracts_bare_count():
    from vsf.schema import first_number
    assert first_number("80 - 100 thực khách") == "80"
    assert first_number("60") == "60"
    assert first_number(None) == ""


def test_location_from_url_reads_coords_and_place_id():
    from vsf.sites.gmaps import location_from_url
    url = ("https://www.google.com/maps/place/X/@12.1995967,109.2054078,17z/"
           "data=!4m6!3m5!1s0x317061674a9ae361:0xb1!8m2!3d12.1996!4d109.2054"
           "!19sChIJYeOaSmdhcDERIUrnIkft-LE")
    out = location_from_url(url)
    # Ưu tiên !3d/!4d (toạ độ địa điểm) chứ không phải @ (tâm khung nhìn).
    assert out["lat"] == 12.1996 and out["long"] == 109.2054
    assert out["place_id"] == "ChIJYeOaSmdhcDERIUrnIkft-LE"


def test_location_from_url_falls_back_to_viewport_centre():
    from vsf.sites.gmaps import location_from_url
    out = location_from_url("https://www.google.com/maps/place/X/@12.25,109.19,17z/data=!3m1")
    assert out["lat"] == 12.25 and out["long"] == 109.19


def test_location_from_url_empty_for_search_url():
    from vsf.sites.gmaps import location_from_url
    assert location_from_url("https://www.google.com/maps/search/abc?hl=vi") == {}


def test_clean_address_matches_dataset_style():
    from vsf.schema import clean_address
    # Dataset bỏ ", Việt Nam" và mã bưu chính.
    assert (clean_address("188 Ngô Gia Tự, Nha Trang, Khánh Hòa 650000, Việt Nam")
            == "188 Ngô Gia Tự, Nha Trang, Khánh Hoà")


def test_place_id_derived_from_fid_matches_real_value():
    from vsf.sites.gmaps import place_id_from_fid
    # Đối chiếu với place_id thật trong dòng dữ liệu đúng của Bánh Canh Ghẹ Quận Nhất.
    assert (place_id_from_fid("0x317067143e2e58f5", "0x1a7c88a576fbe210")
            == "ChIJ9VguPhRncDEREOL7dqWIfBo")


def test_location_from_url_uses_fid_when_19s_absent():
    from vsf.sites.gmaps import location_from_url
    url = ("https://www.google.com/maps/place/X/@12.240253,109.1872499,17z/"
           "data=!3m1!4b1!4m6!3m5!1s0x317067143e2e58f5:0x1a7c88a576fbe210"
           "!8m2!3d12.240253!4d109.1872499")
    out = location_from_url(url)
    assert out["place_id"] == "ChIJ9VguPhRncDEREOL7dqWIfBo"
    # Dataset ghi toạ độ 4 chữ số thập phân.
    assert out["lat"] == 12.2403 and out["long"] == 109.1872


# -- Phường sau sáp nhập 2025 ----------------------------------------------

WARD_MAP = {"phuoc tien": "Tây Nha Trang", "ngo gia tu": "Tây Nha Trang",
            "loc tho": "Nam Nha Trang"}


def test_merged_ward_maps_old_ward_name():
    from vsf.schema import merged_ward
    assert merged_ward("12 Lê Lợi, Phước Tiến, Nha Trang", "Phước Tiến", WARD_MAP) == "Tây Nha Trang"


def test_merged_ward_falls_back_to_street_name():
    from vsf.schema import merged_ward
    # Google nhiều khi không trả tên phường -> khớp theo tên đường.
    assert merged_ward("188 Ngô Gia Tự, Nha Trang, Khánh Hoà", "Nha Trang", WARD_MAP) == "Tây Nha Trang"


def test_merged_ward_keeps_google_value_when_unmapped():
    from vsf.schema import merged_ward
    assert merged_ward("1 Đường Lạ, Nha Trang", "Vĩnh Hải", WARD_MAP) == "Vĩnh Hải"


def test_build_row_rewrites_address_with_merged_ward_and_keeps_original():
    from vsf.schema import build_row
    record = _sample_record()
    record.google_maps["address"] = "188 Ngô Gia Tự, Nha Trang, Khánh Hòa 650000, Việt Nam"
    row = build_row(record, DEFAULTS, ward_map=WARD_MAP)
    assert row["ward"] == "Tây Nha Trang"
    assert row["address"] == "188 Ngô Gia Tự, Tây Nha Trang, Khánh Hoà"


def test_old_address_comes_from_gemini_not_from_google():
    # old_address = địa chỉ TRƯỚC sáp nhập 1/7/2025, do bước old_address hỏi Gemini.
    from vsf.schema import build_row
    record = _sample_record()
    assert build_row(record, DEFAULTS)["old_address"] == ""

    record.google_maps["old_address"] = "188 Ngô Gia Tự, Phước Tiến, Nha Trang, Khánh Hòa, Việt Nam"
    row = build_row(record, DEFAULTS)
    assert row["old_address"] == "188 Ngô Gia Tự, Phước Tiến, Nha Trang, Khánh Hoà"


def test_menu_prices_splits_ranges_instead_of_concatenating():
    from vsf.schema import menu_prices
    # Gộp chữ số lại thì "180 - 195" thành 180.195.000đ -> lệch hết xếp hạng món.
    assert menu_prices("180 - 195") == [180000, 195000]
    assert menu_prices("120") == [120000]
    assert menu_prices(None) == []


def test_parse_menu_price_uses_upper_bound_of_range():
    from vsf.schema import parse_menu_price
    assert parse_menu_price("180 - 195") == 195000
    assert parse_menu_price("345") == 345000


def test_signature_dishes_ranks_ranges_against_flat_prices_correctly():
    from vsf.profiles.food import signature_dishes
    # Combo 345k phải đứng trên mẹt 180-195k. Trước đây "180 - 195" bị đọc thành
    # 180.195.000đ nên luôn chiếm vị trí đầu.
    menu = json.dumps([
        {"loai_thuc_pham": "BÁNH CUỐN", "ten": "Mẹt Lớn Lụi Bò", "gia": "180 - 195"},
        {"loai_thuc_pham": "COMBO", "ten": "Combo 10", "gia": "345"},
    ])
    assert signature_dishes(menu, limit=1) == ["Combo 10"]


# -- Gộp giá menu về một số -------------------------------------------------


def test_single_price_keeps_only_lower_bound():
    from vsf.schema import single_price
    assert single_price("25 - 28") == "25"
    assert single_price("120 - 155") == "120"
    assert single_price("69") == "69"


def test_menu_column_collapses_every_price_to_one_number():
    from vsf.profiles.food import menu_json
    record = _sample_record()
    record.menu = {"extracted": {"_raw":
        'Kết quả:\n[{"ten": "Cuốn Đặc Biệt", "gia": "25 - 28"},'
        ' {"ten": "Mẹt Lớn", "gia": "120 - 155"}]'}}
    items = json.loads(menu_json(record))
    assert [i["gia"] for i in items] == ["25", "120"]


def test_menu_json_maps_geminis_fixed_alt_schema_keys():
    # Xác nhận bằng thực nghiệm 2026-08-14 (POI "Greek Cuisine"): mẫu trích
    # xuất thực đơn cố định của Gemini dùng name/description/price/category
    # thay vì loai_thuc_pham/ten/gia dù prompt yêu cầu rõ ràng — "price" là SỐ
    # nguyên đầy đủ VNĐ (165000), phải quy về "nghìn" ("165") để khớp
    # menu_prices() vốn luôn nhân 1000 khi đọc lại.
    from vsf.profiles.food import menu_json
    record = _sample_record()
    record.menu = {"extracted": {"_raw": json.dumps([
        {"name": "Chicken Skewer", "description": "...", "price": 165000, "category": "Main"},
        {"name": "Chicken wrap", "description": "...", "price": 60000, "category": "Pita Wraps"},
    ])}}
    items = json.loads(menu_json(record))
    assert items[0] == {"loai_thuc_pham": "Main", "ten": "Chicken Skewer", "gia": "165"}
    assert items[1]["gia"] == "60"


def test_menu_json_alt_schema_missing_price_leaves_gia_blank():
    from vsf.profiles.food import menu_json
    record = _sample_record()
    record.menu = {"extracted": {"_raw": json.dumps(
        [{"name": "Bí ẩn", "category": "Main"}]
    )}}
    items = json.loads(menu_json(record))
    assert items[0]["gia"] == ""


def test_menu_json_is_indented_valid_json():
    from vsf.profiles.food import menu_json
    record = _sample_record()
    record.menu = {"extracted": {"_raw": '[{"ten": "Phở", "gia": "45"}]'}}
    text = menu_json(record)
    assert "\n" in text
    assert json.loads(text)[0]["ten"] == "Phở"




# -- Danh sách luôn ngăn bằng dấu phẩy --------------------------------------


def test_list_fields_normalise_any_separator_to_comma():
    from vsf.schema import join_list
    assert join_list("Món A\nMón B\nMón C") == "Món A, Món B, Món C"
    assert join_list("Món A; Món B") == "Món A, Món B"
    assert join_list("- Món A\n- Món B") == "Món A, Món B"
    assert join_list(["Món A", "Món B"]) == "Món A, Món B"


def test_must_try_dishes_is_comma_separated_in_row():
    from vsf.schema import build_row
    record = _sample_record()
    record.gemini_profile["must_try_dishes"] = "Cá nhúng giấm\nCá chình um cari"
    assert build_row(record, DEFAULTS)["must_try_dishes"] == "Cá nhúng giấm, Cá chình um cari"


# -- Phân loại category_l1 / category_l2 -----------------------------------


def test_classify_l1_accepts_every_food_label():
    for raw in ["Nhà hàng hải sản", "Quán cà phê", "Quán ăn Việt Nam",
                "Tiệm bánh", "Quán bar", "Nhà hàng chay"]:
        assert classify_l1(raw) == ("FOOD", True), raw


def test_classify_l1_rejects_non_food_labels():
    for raw in ["Khách sạn 3 sao", "Bãi biển", "Siêu thị", "Bảo tàng", "Spa"]:
        assert classify_l1(raw) == ("OTHER", True), raw


def test_classify_l1_fails_open_when_label_missing():
    """Không đọc được nhãn -> coi là FOOD nhưng đánh dấu KHÔNG chắc chắn.

    Chặn nhầm một quán thật chỉ để lại dòng stub mà người gán nhãn khó nhận ra;
    một khách sạn lọt qua thì lộ ngay vì không có menu.
    """
    assert classify_l1("") == ("FOOD", False)
    assert classify_l1("   ") == ("FOOD", False)


def test_classify_l1_ignores_the_place_name():
    """CHỈ xét nhãn ngành Google. "Nhà hàng - Khách sạn Yasaka" có chữ "khách
    sạn" trong TÊN nhưng vẫn là chỗ ăn — lấy tên vào so khớp là tự tạo dương
    tính giả, nên classify_l1 không nhận tên vào."""
    assert classify_l1("Nhà hàng") == ("FOOD", True)


def test_normalize_l2_returns_canonical_spelling():
    """Gemini gõ sai hoa/thường hoặc thiếu dấu -> vẫn về đúng cách viết chuẩn."""
    assert normalize_l2("quán cà phê") == "Quán cà phê"
    assert normalize_l2("QUÁN BAR") == "Quán Bar"
    assert normalize_l2("Ăn via he") == "Ăn vỉa hè"
    assert normalize_l2("nha hang") == "Nhà hàng"


def test_normalize_l2_never_emits_an_invalid_label():
    """Nhãn Gemini tự nghĩ (kể cả bộ snake_case CŨ) không bao giờ ra tới cột."""
    assert normalize_l2("quan_ca_phe", "Nhà hàng hải sản", "X") == "Nhà hàng"
    assert normalize_l2("Tiệm tạp hoá", "Quán cà phê", "Y") == "Quán cà phê"


def test_normalize_l2_infers_from_google_label_then_name():
    assert normalize_l2(None, "Quán bar Sky", "") == "Quán Bar"
    assert normalize_l2(None, "", "Cà Phê Sách Hồng Tươi") == "Quán cà phê"
    assert normalize_l2(None, "", "Nhà hàng Yến Sào") == "Nhà hàng"


def test_normalize_l2_falls_back_for_a_plain_eatery():
    """Quán ăn thường không có từ khoá nào -> l2_fallback, KHÔNG để trống."""
    assert normalize_l2(None, "", "Bánh Canh Trần Văn Ơn") == "Quán ăn"


def test_normalize_l2_matches_on_word_boundaries_not_substrings():
    """Khớp chuỗi con cho dương tính giả rất khó thấy."""
    # "pub" nằm trong "gastropub", "bar" nằm trong "barbecue".
    assert normalize_l2(None, "", "ZAVOD restaurant & gastropub") == "Nhà hàng"
    assert normalize_l2(None, "", "Quán Barbecue Ngon") == "Quán ăn"


def test_normalize_l2_trusts_the_google_label_over_the_place_name():
    """Nhãn ngành Google xét TRƯỚC tên quán, không gộp chung một chuỗi.

    Gộp chung thì thứ tự khai báo hint quyết định thay vì độ tin cậy của nguồn.
    """
    assert normalize_l2(None, "Quán bar", "ZAVOD restaurant & gastropub") == "Quán Bar"
    assert normalize_l2(None, "Nhà hàng", "Cà Phê Sách Hồng Tươi") == "Nhà hàng"


def test_classify_l1_does_not_reject_spaghetti_for_containing_spa():
    assert classify_l1("Nhà hàng Spaghetti") == ("FOOD", True)
    assert classify_l1("Spa") == ("OTHER", True)


def test_build_row_writes_category_l2_now():
    """Đảo quyết định cũ: cột này từng luôn để trống, giờ phải có giá trị."""
    record = _sample_record()
    record.poi_name = "Cà Phê Sách Hồng Tươi"
    record.google_maps["name"] = "Cà Phê Sách Hồng Tươi"
    record.gemini_profile["category_l2"] = "Quán cà phê"
    assert build_row(record, DEFAULTS)["category_l2"] == "Quán cà phê"


def test_build_row_prefers_the_value_already_settled_on_the_record():
    """pipeline chốt sẵn vào record.category_l2 -> tầng xuất không đoán lại."""
    record = _sample_record()
    record.category_l2 = "Quán Bar"
    record.gemini_profile["category_l2"] = "Quán cà phê"
    assert build_row(record, DEFAULTS)["category_l2"] == "Quán Bar"


# -- Dòng stub cho POI không phải đồ ăn -------------------------------------


def test_build_row_stubs_everything_but_name_for_non_food():
    record = _sample_record()
    record.category_l1 = "OTHER"
    row = build_row(record, DEFAULTS)

    assert list(row.keys()) == COLUMNS
    assert row["category_l1"] == "OTHER"
    assert row["name"] == "Nha Trang Quán Xí Mộng"
    # Mọi cột còn lại phải rỗng — kể cả status/labeled_by/last_updated vốn là
    # hằng số trong defaults.
    filled = {k: v for k, v in row.items() if v and k not in ("category_l1", "name")}
    assert filled == {}


def test_build_row_stub_uses_poi_name_when_maps_never_ran():
    record = _sample_record()
    record.category_l1 = "OTHER"
    record.google_maps = {}
    assert build_row(record, DEFAULTS)["name"] == record.poi_name


def test_old_records_without_category_l1_stay_food():
    """data.json cũ không có khoá này -> lùi về defaults, không hoá stub."""
    record = _sample_record()
    assert record.category_l1 == ""
    row = build_row(record, DEFAULTS)
    assert row["category_l1"] == "FOOD"
    assert row["status"] == "active"


# -- Tên tiếng Anh ----------------------------------------------------------


def test_english_name_rejects_diacritic_stripped_vietnamese():
    from vsf.schema import english_name
    assert english_name("Ca phe Hoa Moc Lan", "Cà Phê Hoa Mộc Lan") == ""
    assert english_name("Nha Trang Quan Xi Mong", "Nha Trang Quán Xí Mộng") == ""


def test_english_name_rejects_placeholders_and_vietnamese():
    from vsf.schema import english_name
    for value in ["", None, "không có", "N/A", "-", "Cà Phê Hoa Mộc Lan"]:
        assert english_name(value, "Cà Phê Hoa Mộc Lan") == ""


def test_english_name_keeps_a_real_english_name():
    from vsf.schema import english_name
    assert english_name("Golden Bamboo Restaurant", "Nhà hàng Trúc Vàng") == (
        "Golden Bamboo Restaurant"
    )


def test_build_row_blanks_fake_english_name():
    from vsf.schema import build_row
    record = _sample_record()
    record.gemini_profile["name_en"] = "Nha Trang Quan Xi Mong"
    assert build_row(record, DEFAULTS)["name_en"] == ""


# -- Giới hạn số bình luận & độ tin cậy -------------------------------------


def test_quoted_comments_caps_at_five():
    from vsf.schema import quoted_comments
    reviews = [{"text": f"binh luan {i}"} for i in range(9)]
    assert quoted_comments(reviews).count("\n") == 4  # 5 đoạn, 4 dòng ngăn cách


def test_quoted_comments_skips_empty_then_still_caps():
    """Bài chấm sao không viết gì bị bỏ qua, nhưng vẫn không vượt quá 5 câu."""
    from vsf.schema import quoted_comments
    reviews = [{"text": ""}, {"text": "  "}] + [{"text": f"c{i}"} for i in range(7)]
    assert quoted_comments(reviews) == "c0\nc1\nc2\nc3\nc4"


def test_quoted_comments_accepts_fewer_than_five():
    from vsf.schema import quoted_comments
    assert quoted_comments([{"text": "chỉ có một"}]) == "chỉ có một"


def test_confidence_level_always_comes_from_defaults():
    """Mức Gemini tự chấm bị bỏ qua — dataset dùng mức mặc định đã thống nhất."""
    from vsf.schema import build_row
    record = _sample_record()
    record.gemini_profile["confidence_level"] = "thấp"
    row = build_row(record, {**DEFAULTS, "confidence_level": "Cao"})
    assert row["confidence_level"] == "Cao"


# -- Giá menu ghi kiểu đầy đủ VNĐ có dấu phẩy --------------------------------


def test_degroup_thousands_converts_comma_grouped_vnd():
    from vsf.schema import degroup_thousands
    assert degroup_thousands("129,000") == "129"
    assert degroup_thousands("1,100,000") == "1100"


def test_degroup_thousands_leaves_plain_numbers_alone():
    from vsf.schema import degroup_thousands
    assert degroup_thousands("129") == "129"
    assert degroup_thousands("25 - 28") == "25 - 28"


def test_menu_json_handles_comma_formatted_prices_from_gemini():
    """Gemini đôi khi phớt lờ chỉ dẫn và trả giá đầy đủ VNĐ có dấu phẩy —
    không quy đổi trước thì regex tách số sẽ đọc '1,100,000' thành '1'."""
    from vsf.profiles.food import menu_json
    record = POIRecord(poi_name="X")
    record.menu = {"extracted": {"_raw": json.dumps([
        {"ten": "Tôm nướng", "gia": "129,000"},
        {"ten": "Rượu vang", "gia": "1,100,000"},
    ])}}
    items = json.loads(menu_json(record))
    assert items[0]["gia"] == "129"
    assert items[1]["gia"] == "1100"
