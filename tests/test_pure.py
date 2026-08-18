"""Test các hàm thuần — chạy được không cần browser."""

import pytest

from vsf.sites.gmaps import upgrade_image_url
from vsf.sites.tiktok import match_score, posted_at_from_url

# URL thật lấy từ Google Maps ngày 2026-08-11.
REAL_TILE = (
    "https://lh3.googleusercontent.com/gps-cs-s/AHRPTWnxcNaoZCxzhwFNPOdEdBFthw"
    "RmNDsdmFHryBkg2cZofOZuyQomEYOhd2Rq7sX=w408-h306-k-no"
)


def test_upgrade_replaces_size_suffix():
    # Định dạng dataset đang dùng: =w1080-h1080-p-k-no
    out = upgrade_image_url(REAL_TILE, 1080)
    assert out.endswith("=w1080-h1080-p-k-no")
    assert "w408-h306" not in out
    assert out.startswith("https://lh3.googleusercontent.com/gps-cs-s/")


def test_upgrade_is_idempotent():
    once = upgrade_image_url(REAL_TILE, 1080)
    assert upgrade_image_url(once, 1080) == once


def test_upgrade_leaves_streetview_thumbnails_alone():
    # Ảnh Street View là googleapis.com kèm query string — đụng vào là hỏng URL.
    sv = "https://streetviewpixels-pa.googleapis.com/v1/thumbnail?panoid=abc&w=224&h=298"
    assert upgrade_image_url(sv, 1600) == sv


# -- TikTok: giải mã ngày đăng từ video ID --------------------------------


def test_posted_at_decoded_from_video_id():
    # Video thật của @huykutis, đăng 13/07/2023.
    url = "https://www.tiktok.com/@huykutis/video/7255346757062741254"
    assert posted_at_from_url(url).startswith("2023-07-13")


@pytest.mark.parametrize(
    "url,expected_prefix",
    [
        ("https://www.tiktok.com/@nghiennhatrang/video/7443419261126724871", "2024-12-01"),
        ("https://www.tiktok.com/@thouse2020/video/7096749240818339118", "2022-05-12"),
    ],
)
def test_posted_at_across_multiple_real_videos(url, expected_prefix):
    assert posted_at_from_url(url).startswith(expected_prefix)


def test_posted_at_returns_none_for_non_video_url():
    assert posted_at_from_url("https://www.tiktok.com/@someone") is None


def test_posted_at_rejects_implausible_timestamp():
    # ID quá nhỏ -> timestamp trước khi TikTok tồn tại: phải trả None thay vì
    # bịa ra một ngày năm 1970.
    assert posted_at_from_url("https://www.tiktok.com/@x/video/12345") is None


# -- Chấm điểm khớp tên POI ------------------------------------------------


def test_match_score_ignores_vietnamese_diacritics():
    assert match_score("Bánh Canh Trần Văn Ơn", "banh canh tran van on ngon") == 1.0


def test_match_score_partial():
    score = match_score("Bánh Canh Trần Văn Ơn", "bánh canh lòng cá Nha Trang")
    assert 0 < score < 1


def test_match_score_unrelated_caption_is_zero():
    assert match_score("Bánh Canh Trần Văn Ơn", "hướng dẫn học lập trình") == 0.0


def test_match_score_does_not_leak_short_word_into_longer_one():
    # "on" (từ "Ơn") nằm lọt trong "huong" — từng cho điểm giả 0.2.
    assert match_score("Bánh Canh Trần Văn Ơn", "hướng dẫn nấu ăn") == 0.0


def test_match_score_catches_concatenated_hashtags():
    # Hashtag dính liền là kiểu viết phổ biến trên TikTok.
    score = match_score("Bánh Canh Trần Văn Ơn", "#banhcanhlongca ăn ở Nha Trang")
    assert score >= 0.6


# -- Neo vùng khi tìm kiếm (tên quán trùng nhau giữa các tỉnh) --------------


def test_search_query_appends_region():
    from vsf.sites.gmaps import search_query
    assert search_query("Bánh Canh Ghẹ Quận Nhất", "Nha Trang") == "Bánh Canh Ghẹ Quận Nhất Nha Trang"


def test_search_query_does_not_duplicate_region_already_in_name():
    from vsf.sites.gmaps import search_query
    assert search_query("Nha Trang Quán Xí Mộng", "Nha Trang") == "Nha Trang Quán Xí Mộng"


def test_search_query_without_region_is_unchanged():
    from vsf.sites.gmaps import search_query
    assert search_query("Quán ABC", "") == "Quán ABC"


def test_name_match_catches_wrong_restaurant():
    from vsf.sites.gmaps import name_match
    # Sự cố thật: hỏi "Quận Nhất" (Nha Trang), Google trả "Cô Mỹ" (Hà Nội).
    assert name_match("Bánh Canh Ghẹ Quận Nhất", "Bánh Canh Ghẹ Cô Mỹ") < 0.75
    assert name_match("Bánh Canh Ghẹ Quận Nhất", "Bánh Canh Ghẹ Quận Nhất") == 1.0


def test_name_match_below_new_threshold_for_real_mismatch():
    from vsf.sites.gmaps import name_match
    # Sự cố thật gặp trong output_12/8: hỏi "Greek Cuisine", Google trả về
    # "Greek Kitchen" (quán khác, địa chỉ khác) — khớp đúng 0.5, ngưỡng cũ 0.5
    # với so sánh `<` để lọt qua trong im lặng. Ngưỡng mới phải bắt được ca này.
    assert name_match("Greek Cuisine", "Greek Kitchen") < 0.6


def test_search_query_appends_address_street_before_region():
    from vsf.sites.gmaps import search_query
    assert (
        search_query("Greek Cuisine", "Nha Trang", "223 Nguyễn Thiện Thuật, Nha Trang")
        == "Greek Cuisine 223 Nguyễn Thiện Thuật Nha Trang"
    )


def test_search_query_without_address_hint_falls_back_to_region_only():
    from vsf.sites.gmaps import search_query
    assert search_query("Quán ABC", "Nha Trang", "") == "Quán ABC Nha Trang"


def test_address_match_catches_wrong_street():
    from vsf.sites.gmaps import address_match
    assert address_match(
        "223 Nguyễn Thiện Thuật, Nha Trang", "172/2 Bạch Đằng, Nha Trang, Khánh Hòa"
    ) < 0.5
    assert address_match(
        "223 Nguyễn Thiện Thuật, Nha Trang",
        "223 Nguyễn Thiện Thuật, Nha Trang, Khánh Hòa",
    ) == 1.0


def test_address_match_without_hint_is_always_a_match():
    from vsf.sites.gmaps import address_match
    assert address_match("", "bất kỳ địa chỉ nào") == 1.0


def test_tiktok_simplify_strips_parenthetical_and_suffix():
    from vsf.sites.tiktok import simplify
    # TikTok không ra kết quả với tên dài đầy dấu chấm và ngoặc.
    assert simplify("Bánh Cuốn Tây Sơn. Vn - Ms.Smile (Quán ăn ngon ở Nha Trang)") == "Bánh Cuốn Tây Sơn"
    assert simplify("Quán Xí Mộng") == "Quán Xí Mộng"


def test_tiktok_query_candidates_try_full_then_short():
    from vsf.sites.tiktok import _query_candidates
    qs = _query_candidates("Bánh Cuốn Tây Sơn. Vn - Ms.Smile (Quán ăn ngon ở Nha Trang)", "Nha Trang")
    assert len(qs) == 2
    assert qs[0].startswith("Bánh Cuốn Tây Sơn. Vn")
    assert qs[1] == "Bánh Cuốn Tây Sơn Nha Trang"


def test_tiktok_query_candidates_single_when_name_already_simple():
    from vsf.sites.tiktok import _query_candidates
    assert _query_candidates("Quán Xí Mộng", "Nha Trang") == ["Quán Xí Mộng Nha Trang"]


# -- Giờ mở/đóng cửa --------------------------------------------------------


def test_parse_day_hours_plain_range():
    from vsf.sites.gmaps import parse_day_hours
    assert parse_day_hours("10:00 đến 14:00") == {
        "hours": "10:00 đến 14:00", "open": "10:00", "close": "14:00"
    }


def test_parse_day_hours_open_all_day():
    """'Mở cửa cả ngày' phải thành 0:00–23:59, không được để trống."""
    from vsf.sites.gmaps import parse_day_hours
    entry = parse_day_hours("Mở cửa cả ngày")
    assert entry["open"] == "0:00" and entry["close"] == "23:59"
    assert entry["all_day"] is True


def test_parse_day_hours_open_24_hours_english():
    from vsf.sites.gmaps import parse_day_hours
    for text in ["Mở cửa 24 giờ", "Open 24 hours"]:
        entry = parse_day_hours(text)
        assert (entry["open"], entry["close"]) == ("0:00", "23:59"), text


def test_parse_day_hours_split_shift_spans_first_to_last():
    # Ca gãy: dataset chỉ có một cặp open/close -> lấy mở ca đầu, đóng ca cuối.
    from vsf.sites.gmaps import parse_day_hours
    entry = parse_day_hours("11:00 đến 14:00, 17:00 đến 21:00")
    assert (entry["open"], entry["close"]) == ("11:00", "21:00")


def test_parse_day_hours_closed_day_has_no_times():
    from vsf.sites.gmaps import parse_day_hours
    entry = parse_day_hours("Đóng cửa")
    assert "open" not in entry and "close" not in entry


def test_menu_category_preference_excludes_generic_food_photos():
    """Chỉ lấy ảnh mục Thực đơn — ảnh 'Thực phẩm và đồ uống' là ảnh món khách chụp."""
    from vsf.sites.gmaps import MENU_CATEGORY_PREFERENCE
    assert "Thực phẩm và đồ uống" not in MENU_CATEGORY_PREFERENCE
    assert MENU_CATEGORY_PREFERENCE[0] == "Thực đơn"


# -- Cổng chặn POI không phải đồ ăn ----------------------------------------


def _record(name="X"):
    from vsf.models import POIRecord

    return POIRecord(poi_name=name)


def test_reject_non_food_stops_on_a_hotel_label():
    from vsf.pipeline import _reject_non_food

    record = _record()
    stop = _reject_non_food(record, {"category_raw": "Khách sạn", "name": "Mường Thanh"})
    assert stop is True
    assert record.category_l1 == "OTHER"
    assert any("KHÔNG PHẢI FOOD" in w for w in record.all_warnings())


def test_reject_non_food_lets_a_restaurant_through_and_seeds_l2():
    from vsf.pipeline import _reject_non_food

    record = _record()
    stop = _reject_non_food(record, {"category_raw": "Quán cà phê", "name": "Cà Phê Nhiên"})
    assert stop is False
    assert record.category_l1 == "FOOD"
    # Nhãn Google đã đủ để chốt l2 trước cả khi hỏi Gemini.
    assert record.category_l2 == "Quán cà phê"


def test_reject_non_food_fails_open_and_warns_when_label_unreadable():
    """Selector hỏng -> vẫn chạy tiếp như luồng cũ, nhưng phải kêu lên."""
    from vsf.pipeline import _reject_non_food

    record = _record()
    assert _reject_non_food(record, {"name": "Bánh Canh Trần Văn Ơn"}) is False
    assert record.category_l1 == "FOOD"
    assert any("place_category" in w for w in record.all_warnings())


def test_force_food_overrides_a_non_food_label():
    from vsf.pipeline import _reject_non_food

    record = _record()
    record.force_food = True
    assert _reject_non_food(record, {"category_raw": "Khách sạn", "name": "Y"}) is False
    assert record.category_l1 == "FOOD"


def test_force_food_is_never_persisted_to_data_json():
    """Ép tay chỉ có hiệu lực một lần chạy — ghi vào JSON là vô hiệu cổng vĩnh viễn."""
    from dataclasses import asdict

    record = _record()
    record.force_food = True
    assert "force_food" not in asdict(record)


def test_reject_wrong_place_still_raises_before_anything_expensive():
    from vsf.pipeline import _reject_wrong_place

    data = {"name": "Greek Kitchen", "address": "Phố khác", "name_match": 0.5}
    with pytest.raises(RuntimeError, match="LẤY NHẦM QUÁN"):
        _reject_wrong_place(data, "Greek Cuisine")


def test_maps_runs_before_gemini_so_both_gates_fire_first():
    """Thứ tự bước là một phần của thiết kế, không phải chi tiết ngẫu nhiên."""
    from vsf.pipeline import STEPS

    assert STEPS.index("maps") < STEPS.index("gemini1")


# -- Làm sạch nhãn ngành Google --------------------------------------------


def test_clean_category_strips_the_hotel_layout_middot():
    """Bố cục khách sạn nhét dấu chấm giữa vào đầu nhãn."""
    from vsf.sites.gmaps import clean_category
    assert clean_category("·Khách sạn 3 sao") == "Khách sạn 3 sao"
    assert clean_category("  Quán cà phê  ") == "Quán cà phê"


def test_clean_category_rejects_icon_buttons_and_suggestion_chips():
    """Thà để trống còn hơn nhả nhãn sai — nhãn sai lái cổng phân loại đi lạc.

    Chuỗi có glyph icon Material hoặc nhiều dòng là chip gợi ý ("Khách sạn gần
    đây"), không phải ngành nghề của chính địa điểm đang xem.
    """
    from vsf.sites.gmaps import clean_category
    assert clean_category("\nKhách sạn gần đây") == ""
    assert clean_category("") == ""
    assert clean_category("") == ""


def test_clean_category_keeps_real_labels_seen_on_google():
    """Nhãn thật đọc được ngày 2026-08-18."""
    from vsf.sites.gmaps import clean_category
    for label in ["Nhà hàng", "Quán cà phê", "Bảo tàng", "Quán mì"]:
        assert clean_category(label) == label


# -- Cổng bỏ qua bước ------------------------------------------------------


def _rec_with(steps, l1=""):
    from vsf.models import POIRecord

    r = POIRecord(poi_name="X")
    r.steps = dict(steps)
    r.category_l1 = l1
    return r


def test_skip_reason_never_blocks_maps_itself():
    from vsf.pipeline import _skip_reason

    assert _skip_reason(_rec_with({}), "maps") is None


def test_skip_reason_blocks_everything_when_maps_failed():
    """Đảo thứ tự khiến mọi bước sau phụ thuộc maps.

    Đã gặp thật: "Greek Cuisine" bị chặn vì Google trả "Greek Kitchen", nhưng
    pipeline vẫn đốt 3 lượt Gemini trên dữ liệu rỗng rồi ghi "ok".
    """
    from vsf.pipeline import STEPS, _skip_reason

    record = _rec_with({"maps": "failed"})
    for step in STEPS:
        if step == "maps":
            continue
        assert _skip_reason(record, step) == "bước maps chưa xong", step


def test_skip_reason_blocks_when_maps_never_ran():
    from vsf.pipeline import _skip_reason

    assert _skip_reason(_rec_with({}), "gemini1") == "bước maps chưa xong"


def test_skip_reason_blocks_non_food_after_a_good_maps_run():
    from vsf.pipeline import _skip_reason

    record = _rec_with({"maps": "ok"}, l1="OTHER")
    assert _skip_reason(record, "gemini1") == "không phải FOOD"


def test_skip_reason_lets_food_through():
    from vsf.pipeline import STEPS, _skip_reason

    record = _rec_with({"maps": "ok"}, l1="FOOD")
    assert all(_skip_reason(record, s) is None for s in STEPS)
