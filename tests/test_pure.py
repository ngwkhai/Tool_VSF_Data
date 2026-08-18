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


# -- Chấm điểm đa tín hiệu -------------------------------------------------
#
# Mỗi test dưới đây ứng với MỘT lỗi thật quan sát được trên dữ liệu đã cào, không
# phải ca giả định. Xem scripts/rescore_tiktok.py để dựng lại.


def _df(captions):
    from vsf.sites.tiktok import document_frequency

    return document_frequency(captions), len(captions)


def test_caption_score_kills_words_present_in_every_candidate():
    """Từ có ở MỌI ứng viên thì không phân biệt được gì -> phải hết trọng số.

    Đây là gốc của thế hoà điểm: "Ăn Vặt Trịnh Huệ" từng được 0.5 cho cả 5 ứng
    viên chỉ nhờ khớp "ăn vặt", từ mà mọi video ăn uống Nha Trang đều có.
    """
    from vsf.sites.tiktok import caption_score

    captions = [
        "quán ăn vặt ngon ở Nha Trang",
        "ăn vặt Nha Trang siêu rẻ",
        "top món ăn vặt Nha Trang",
        "ăn vặt Nha Trang nè",
    ]
    df, n = _df(captions)
    # Không caption nào nhắc "Trịnh Huệ" -> phải gần 0, không phải 0.5.
    assert caption_score("Ăn Vặt Trịnh Huệ", captions[0], df, n) < 0.2


def test_caption_score_rewards_the_distinctive_word():
    from vsf.sites.tiktok import caption_score

    captions = [
        "quán ăn vặt ngon ở Nha Trang",
        "ăn vặt Nha Trang siêu rẻ",
        "ăn vặt Trịnh Huệ Nha Trang chuẩn vị",
    ]
    df, n = _df(captions)
    hit = caption_score("Ăn Vặt Trịnh Huệ", captions[2], df, n)
    miss = caption_score("Ăn Vặt Trịnh Huệ", captions[0], df, n)
    assert hit > miss * 2


def test_author_score_ignores_short_tokens_after_diacritic_stripping():
    """GUARD: 'Đam' không được khớp '@Xóm Đầm'. Đầm ≠ Đam."""
    from vsf.sites.tiktok import author_score

    assert author_score("Đam Coffee & Fruit Juice", "Xóm Đầm") == 0.0


def test_author_score_matches_a_single_name_segment():
    """Tên quán ghép nhiều biến thể, handle chỉ lấy MỘT đoạn."""
    from vsf.sites.tiktok import author_score

    assert author_score("La Tra Milk Tea - Smoothie - Trà Sữa Lá Trà", "trasualatra") == 1.0
    assert author_score("ФоБорщ / PhoBorsch", "phoborsch") == 1.0


def test_author_score_survives_when_owner_posted_every_candidate():
    """idf của caption KHÔNG được dùng ở đây.

    Chính chủ đăng cả 5 video -> tên quán có ở mọi caption -> idf về 0. Nếu lọc
    'từ đặc trưng' theo idf thì ném đi đúng cái tên cần khớp ("chớm brew&bloom"
    từng được 0.0 dù cả 5 ứng viên đều của @chớm in the yard).
    """
    from vsf.sites.tiktok import author_score

    assert author_score("chớm brew&bloom", "chớm in the yard") > 0.0


def test_street_of_rejects_plus_code_and_river_name():
    """GUARD: Plus code và tên sông KHÔNG phải địa chỉ đường."""
    from vsf.sites.tiktok import street_of

    assert street_of("65VV+G77, Nha Trang") == ("", [])
    assert street_of("Sông Cái, Nha Trang") == ("", [])
    number, words = street_of("121 Phạm Văn Đồng, Nha Trang")
    assert number == "121" and "pham" in words


def test_address_score_separates_two_branches_of_one_brand():
    """Ca thật: 'Cà phê Đất Vàng' ở 121 Phạm Văn Đồng vs chi nhánh Mai Xuân Thưởng."""
    from vsf.sites.tiktok import address_score

    right = address_score("121 Phạm Văn Đồng, Nha Trang", "121 Phạm Văn Đồng Nha Trang #cafedatvang")
    wrong = address_score("121 Phạm Văn Đồng, Nha Trang", "Cafe Đất Vàng, Mai Xuân Thưởng, Nha Trang.")
    assert right > wrong


def test_industry_stopword_does_not_make_a_category_word_distinctive():
    """idf một mình không đủ: corpus tiếng Việt coi 'milk' là hiếm."""
    from vsf.sites.tiktok import author_score

    # "milk"/"tea" là từ ngành -> không được coi là bằng chứng chính chủ.
    assert author_score("La Tra Milk Tea", "kachamilkteanhatrang") < 1.0


def test_rank_candidates_puts_official_account_first():
    from vsf.sites.tiktok import rank_candidates

    cands = [
        {"url": "https://x/@reviewer/video/1", "caption": "quán cà phê đẹp ở Nha Trang", "author": "reviewer", "handle": "reviewer"},
        {"url": "https://x/@mosa.nhatrang/video/2", "caption": "mo:sa có món mới nè", "author": "mo:sa coffee", "handle": "mosa.nhatrang"},
    ]
    ranked = rank_candidates("mosa coffee", cands, official_handles=frozenset({"mosa.nhatrang"}))
    assert ranked[0]["handle"] == "mosa.nhatrang"
    assert ranked[0]["score_breakdown"]["author"] == 1.0


# -- Cổng chặn tin cậy -----------------------------------------------------


def _record_with_tiktok(cands, facebook=None):
    from vsf.models import POIRecord

    rec = POIRecord(poi_name="Quán Thử")
    rec.tiktok = cands
    if facebook is not None:
        rec.facebook = facebook
    return rec


def test_pick_video_blanks_low_confidence_candidate():
    from vsf.schema import pick_video

    rec = _record_with_tiktok([{"url": "https://t/1", "score": 0.02}])
    assert pick_video(rec) == {}


def test_pick_video_keeps_confident_candidate():
    from vsf.schema import pick_video

    rec = _record_with_tiktok([{"url": "https://t/1", "score": 0.9}])
    assert pick_video(rec)["url"] == "https://t/1"


def test_pick_video_respects_a_manual_choice_below_threshold():
    """Người dùng đã tự nhìn danh sách rồi -> đừng phủ quyết họ."""
    from vsf.schema import pick_video

    rec = _record_with_tiktok(
        [{"url": "https://t/1", "score": 0.9}, {"url": "https://t/2", "score": 0.01}]
    )
    assert pick_video(rec, tiktok_index=1)["url"] == "https://t/2"


def test_pick_video_keeps_old_records_without_scores():
    """data.json cũ chưa có `score` -> không POI nào bỗng dưng mất link."""
    from vsf.schema import pick_video

    rec = _record_with_tiktok([{"url": "https://t/1", "match_score": 0.5}])
    assert pick_video(rec)["url"] == "https://t/1"


def test_pick_video_falls_back_to_verified_facebook_reel():
    from vsf.schema import pick_video

    rec = _record_with_tiktok(
        [{"url": "https://t/1", "score": 0.01}],
        facebook={"verified": {"name": "X"}, "reels": [{"url": "https://fb/reel/9"}]},
    )
    assert pick_video(rec)["url"] == "https://fb/reel/9"


def test_pick_video_ignores_facebook_reels_when_page_unverified():
    """Trang chưa khớp địa chỉ thì Reels của nó có thể là quán trùng tên tỉnh khác."""
    from vsf.schema import pick_video

    rec = _record_with_tiktok(
        [{"url": "https://t/1", "score": 0.01}],
        facebook={"verified": None, "reels": [{"url": "https://fb/reel/9"}]},
    )
    assert pick_video(rec) == {}


# -- Facebook: xác minh bằng địa chỉ ---------------------------------------


def test_facebook_meta_parser_finds_the_address_among_other_fields():
    """Dòng meta gộp nhãn ngành + đánh giá + giá + địa chỉ + giờ + follower."""
    from vsf.sites.facebook import _address_from_meta

    meta = (
        "Sản phẩm/Dịch vụ · 1 đánh giá · $ · 17/1 Lê Thánh Tôn, Phường Nha Trang, "
        "Khánh Hoà · Đang mở cửa · 238 người theo dõi"
    )
    assert _address_from_meta(meta).startswith("17/1 Lê Thánh Tôn")


def test_facebook_meta_parser_skips_counts_that_also_contain_digits():
    """'1 đánh giá' và '238 người theo dõi' có số nhưng không phải địa chỉ."""
    from vsf.sites.facebook import _address_from_meta

    assert _address_from_meta("Quán cà phê · 12 đánh giá · 340 người theo dõi") == ""


def test_facebook_verify_rejects_same_name_shop_in_another_province():
    """Ca thật: 'mosa coffee' cho ra quán đúng + 2 shop thời trang tỉnh khác.

    Quan trọng là loại được cả khi Trang sai CÓ địa chỉ đường đầy đủ — tức phải
    do địa chỉ LỆCH, không phải do không parse nổi.
    """
    from vsf.sites.facebook import verify_page

    pages = [
        {"name": "Xưởng Thời Trang Nam - Mosa", "address": "25 Cầu Giấy, Hà Nội"},
        {"name": "mo:sa coffee - Nha Trang", "address": "17/1 Lê Thánh Tôn, Nha Trang"},
    ]
    verified = verify_page("mosa coffee", "17/1 Lê Thánh Tôn, Nha Trang, Khánh Hòa", pages)
    assert verified is not None
    assert verified["name"] == "mo:sa coffee - Nha Trang"


def test_facebook_verify_returns_none_without_a_google_address():
    """Không có địa chỉ Google thì không có gì để đối chiếu -> đừng đoán bừa."""
    from vsf.sites.facebook import verify_page

    assert verify_page("X", "", [{"name": "X", "address": "1 Đường A"}]) is None


def test_parse_views_handles_k_and_m_suffixes():
    from vsf.sites.tiktok import parse_views

    assert parse_views("7254") == 7254
    assert parse_views("12.3K") == 12300
    assert parse_views("1.2M") == 1_200_000
    assert parse_views("") == 0
    assert parse_views("N/A") == 0


def test_views_break_ties_but_never_outrank_a_real_signal():
    """Video nhiều view nhất về quán KHÁC vẫn là video sai quán."""
    from vsf.sites.tiktok import rank_candidates

    cands = [
        {"url": "https://x/@a/video/1", "caption": "quán nào đó", "handle": "a", "views": "9.9M"},
        {"url": "https://x/@mosa.nhatrang/video/2", "caption": "mo:sa nè", "handle": "mosa.nhatrang", "views": "10"},
    ]
    ranked = rank_candidates("mosa coffee", cands, official_handles=frozenset({"mosa.nhatrang"}))
    assert ranked[0]["handle"] == "mosa.nhatrang"

    tied = [
        {"url": "https://x/@m/video/1", "caption": "mo:sa nè", "handle": "m", "views": "26"},
        {"url": "https://x/@m/video/2", "caption": "mo:sa nè", "handle": "m", "views": "7254"},
    ]
    assert rank_candidates("mosa coffee", tied)[0]["views"] == "7254"


def test_cyrillic_names_are_transliterated_before_matching():
    """Không chuyển tự thì _squash trả chuỗi RỖNG và mọi so khớp âm thầm ra 0.

    Đây là gốc của việc 12 POI tên Nga/Hàn toàn 0.0 điểm.
    """
    from vsf.sites.tiktok import _squash, author_score

    assert _squash("Кафе Лан") == "kafelan"
    assert _squash("ФоБорщ") == "foborshch"
    # Tên có kèm alias Latin thì khớp được qua chính đoạn Latin đó.
    assert author_score("ФоБорщ / PhoBorsch", "phoborsch") == 1.0


def test_no_fuzzy_matching_on_account_names():
    """Chốt lại một hướng ĐÃ THỬ VÀ LOẠI, để đừng ai thêm lại.

    So mờ trên tên đã dính liền chọn SAI đúng ca cần cứu: với "Кафе Лан"
    (-> "kafelan"), quán KHÁC "Cafe Lan Anh" đạt 0.86 còn tài khoản đúng
    "@caflan.flan.gi.s" chỉ 0.71. Tên quán quá ngắn và quá giống nhau.
    """
    from vsf.sites.tiktok import author_score

    # Không khớp được thì phải trả 0 và để cổng tin cậy bỏ trống,
    # KHÔNG được đoán bừa sang một quán tên na ná.
    assert author_score("Кафе Лан", "cafelananh") == 0.0


def test_facebook_street_segment_skips_google_plus_code():
    """Google hay đặt Plus code làm đoạn đầu, và address_match lấy đúng đoạn đó.

    Không lọc thì đem "65VV+G77" đi so với địa chỉ Facebook -> luôn 0 -> Trang
    ĐÚNG bị loại trong im lặng (đã gặp nguyên văn với "mosa coffee").
    """
    from vsf.sites.facebook import street_segment, verify_page

    google = "65VV+G77, 19 Đ. Lê Thánh Tôn, Nha Trang, Khánh Hòa 650000, Việt Nam"
    assert street_segment(google) == "19 Đ. Lê Thánh Tôn"

    pages = [{"name": "mo:sa coffee - Nha Trang", "address": "17/1 Lê Thánh Tôn, Nha Trang"}]
    assert verify_page("mosa coffee", google, pages) is not None


def test_facebook_page_ref_handles_both_id_and_vanity_slug():
    from vsf.sites.facebook import page_ref

    assert page_ref("https://www.facebook.com/profile.php?id=61591157881013&__tn__=%3C") == "61591157881013"
    assert page_ref("/mosacoffee") == "mosacoffee"
    assert page_ref("") == ""
    # /reel/ và /watch không phải định danh Trang.
    assert page_ref("/reel/123456789") == ""
