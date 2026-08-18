"""Test việc rút địa chỉ trước sáp nhập 1/7/2025 từ câu trả lời của Gemini.

Prompt hiện ép Gemini trả về ĐÚNG MỘT object JSON `{"old_ward": "..."}` (kèm
tên quán + địa chỉ hiện tại làm ngữ cảnh đầu vào) — parser ưu tiên đọc JSON,
chỉ lùi về phân tích dòng văn bản cũ khi câu trả lời không chứa JSON nào.
"""

from vsf.pipeline import compose_old_address, extract_old_ward

WARDS = ["Vĩnh Hiệp", "Phước Tiến", "Lộc Thọ", "Xương Huân"]


# -- Đường JSON (đường chính, theo prompt hiện tại) -------------------------


def test_extract_old_ward_reads_json_object():
    assert extract_old_ward('{"old_ward": "Vĩnh Hiệp"}', "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_reads_json_with_surrounding_noise():
    # Gemini đôi khi vẫn kèm rác quanh JSON dù đã bị cấm — vẫn phải đọc được.
    answer = "```json\n{\"old_ward\": \"Vĩnh Hiệp\"}\n```"
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_json_strips_phuong_prefix():
    assert extract_old_ward('{"old_ward": "Phường Phước Tiến"}', "Tây Nha Trang", WARDS) == "Phước Tiến"


def test_extract_old_ward_json_rejects_echo_of_new_ward():
    assert extract_old_ward('{"old_ward": "Tây Nha Trang"}', "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_json_empty_value_is_no_answer():
    assert extract_old_ward('{"old_ward": ""}', "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_json_array_value_is_no_answer():
    # Gemini phớt lờ yêu cầu "một khoá" và trả cả mảng -> không suy diễn phần tử
    # nào, coi như JSON có nhưng không hợp lệ (KHÔNG lùi về phân tích dòng thô
    # của chính khối JSON đó — dễ nhặt nhầm phần tử đầu mảng).
    answer = '{"old_ward": ["Vĩnh Hiệp", "Phước Tiến", "Lộc Thọ"]}'
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_json_normalises_to_canonical_spelling():
    assert extract_old_ward('{"old_ward": "Vinh Hiep"}', "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


# -- Đường lùi: không có JSON trong câu trả lời -----------------------------


def test_extract_old_ward_reads_labelled_answer():
    assert extract_old_ward("old_ward: Vĩnh Hiệp", "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_strips_phuong_prefix():
    assert extract_old_ward("old_ward: Phường Phước Tiến", "Tây Nha Trang", WARDS) == "Phước Tiến"


def test_extract_old_ward_rejects_echo_of_new_ward():
    assert extract_old_ward("old_ward: Tây Nha Trang", "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_rejects_prose():
    answer = "Cảm ơn bạn, tôi đã ghi nhận thông tin cập nhật này."
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) is None


def test_compose_old_address_swaps_ward_keeping_street():
    out = compose_old_address(
        "Đ. Hoàng Cầm/17 KĐT, Vĩnh Điềm Trung, Tây Nha Trang, Khánh Hòa 650000, Việt Nam",
        "Vĩnh Hiệp", "Khánh Hoà")
    assert out == "Đ. Hoàng Cầm/17 KĐT, Vĩnh Hiệp, TP. Nha Trang, Khánh Hoà"


def test_compose_old_address_matches_sample_row_shape():
    # Dòng đúng của người dùng: "188 Ngô Gia Tự, Phước Tiến, Nha Trang, Khánh Hòa"
    out = compose_old_address("188 Ngô Gia Tự, Tây Nha Trang, Khánh Hoà", "Phước Tiến", "Khánh Hoà")
    assert out == "188 Ngô Gia Tự, Phước Tiến, TP. Nha Trang, Khánh Hoà"


def test_extract_old_ward_rejects_citation_source_names():
    # Sự cố thật: Gemini chèn nguồn trích dẫn thành dòng riêng -> nhặt nhầm
    # "Laodong.vn" làm tên phường.
    answer = "old_ward: Vĩnh Hiệp\nLaodong.vn\nBaokhanhhoa.com.vn"
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_ignores_bare_domain_without_label():
    assert extract_old_ward("Laodong.vn", "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_requires_two_syllables():
    # Tên phường tiếng Việt luôn từ 2 âm tiết trở lên.
    assert extract_old_ward("Vinhhiep", "Tây Nha Trang", WARDS) is None
    assert extract_old_ward("Vĩnh Hiệp", "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_prefers_labelled_line_over_earlier_noise():
    answer = "Nguồn tham khảo\nBáo Khánh\nold_ward: Vĩnh Hiệp"
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_extract_old_ward_rejects_citation_title_not_in_ward_list():
    # Sự cố thật: Gemini chèn tiêu đề nguồn "Khu du lịch Bửu Long -" thành một
    # dòng riêng — ngắn, có khoảng trắng, không phải tên miền, nên chỉ lọc theo
    # hình dạng thì lọt. Đối chiếu danh sách phường cũ mới chặn được.
    answer = "Khu du lịch Bửu Long -\nBáo Khánh Hoà"
    assert extract_old_ward(answer, "Tây Nha Trang", WARDS) is None


def test_extract_old_ward_normalises_to_canonical_spelling():
    # Gemini gõ không dấu -> vẫn trả về cách viết chuẩn trong danh sách.
    assert extract_old_ward("old_ward: Vinh Hiep", "Tây Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_ward_in_address_found_directly():
    from vsf.pipeline import ward_in_address
    # Google nhiều khi vẫn giữ tên phường cũ -> khỏi phải hỏi Gemini.
    assert ward_in_address("12 Lê Lợi, Lộc Thọ, Nha Trang, Khánh Hoà", WARDS) == "Lộc Thọ"


def test_ward_in_address_ignores_diacritic_variants():
    from vsf.pipeline import ward_in_address
    assert ward_in_address("12 Lê Lợi, VINH HIEP, Nha Trang", WARDS) == "Vĩnh Hiệp"


def test_ward_in_address_returns_none_when_absent():
    from vsf.pipeline import ward_in_address
    assert ward_in_address("188 Ngô Gia Tự, Tây Nha Trang, Khánh Hoà", WARDS) is None
