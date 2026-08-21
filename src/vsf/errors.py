"""Mã lỗi và cờ triage máy đọc được.

Trước đây mọi tín hiệu chẩn đoán chỉ tồn tại dưới dạng chuỗi tiếng Việt tự do
trong `record.warnings` — đọc bằng mắt thì được, lọc bằng máy thì không. Chạy lô
hàng chục POI cần trả lời được "POI nào cần người xem lại?" mà không phải mở
từng file, nên mỗi tình huống đáng chú ý có thêm một mã ngắn bên cạnh câu cảnh
báo. Cảnh báo tiếng Việt GIỮ NGUYÊN — mã là thứ thêm vào, không phải thứ thay thế.
"""

from __future__ import annotations


class VsfError(RuntimeError):
    """Lỗi có mã máy đọc được. `code` đi thẳng vào `job.error_code`.

    Kế thừa `RuntimeError` chứ không phải `Exception` là CỐ Ý: các cổng chặn
    trước đây ném `RuntimeError` trần, nên mọi chỗ đang bắt `RuntimeError` (kể cả
    test) vẫn bắt được nguyên như cũ. Mã lỗi là thứ thêm vào, không phá hợp đồng
    sẵn có.
    """

    code = "error"


class WrongPlaceError(VsfError):
    """Google trả về một quán KHÁC quán được hỏi.

    Chạy lại không sửa được — phải có người đối chiếu tên/địa chỉ rồi quyết định
    (thêm `--address`, hoặc bỏ POI). Vì thế worker đưa thẳng vào `needs_review`
    thay vì đếm vào số lần thử lại.
    """

    code = "wrong_place"

    def __init__(
        self,
        message: str,
        *,
        name_match: float | None = None,
        address_match: float | None = None,
    ) -> None:
        super().__init__(message)
        self.name_match = name_match
        self.address_match = address_match


# -- Cờ triage --------------------------------------------------------------
#
# Đặt cạnh mỗi `record.warn(...)` đáng để lọc. Không phải cảnh báo nào cũng có
# cờ: chỉ những thứ mà người gán nhãn thực sự cần một hàng đợi riêng để xử lý.

# "POI không thuộc nhóm ngành của profile". Mã chuỗi GIỮ NGUYÊN `not_food` dù
# giờ dùng cho cả profile lưu trú: nó đã nằm trong `flags` của data.json và
# `flags_json` của SQLite cho 141 POI cũ, đổi mã là hàng đợi triage mất sạch
# lịch sử. Chỉ nhãn hiển thị được đổi cho trung tính.
FLAG_NOT_FOOD = "not_food"
FLAG_TIKTOK_LOW = "tiktok_below_threshold"
FLAG_TIKTOK_NONE = "tiktok_not_found"
FLAG_NO_MENU_PHOTOS = "no_menu_photos"
FLAG_MENU_NOT_JSON = "menu_not_json"
FLAG_OLD_ADDRESS_GUESSED = "old_address_guessed"
FLAG_OLD_ADDRESS_MISSING = "old_address_missing"
FLAG_GEMINI_MISSING_FIELDS = "gemini_missing_fields"
FLAG_FEW_SECONDARY_PHOTOS = "few_secondary_photos"
FLAG_NO_COVER_PHOTO = "no_cover_photo"
FLAG_HOURS_INCOMPLETE = "hours_incomplete"
FLAG_CATEGORY_UNKNOWN = "category_unknown"
FLAG_FACEBOOK_UNVERIFIED = "facebook_unverified"
FLAG_FACEBOOK_UNAVAILABLE = "facebook_unavailable"

# Nhãn tiếng Việt để UI hiển thị, và `severity` để xếp thứ tự hàng đợi triage.
# "block" = dòng dữ liệu không dùng được như hiện trạng; "warn" = dùng được
# nhưng có ô trống hoặc giá trị đáng ngờ.
FLAG_LABELS: dict[str, tuple[str, str]] = {
    WrongPlaceError.code: ("Có thể lấy nhầm quán", "block"),
    FLAG_NOT_FOOD: ("Sai nhóm ngành", "block"),
    FLAG_TIKTOK_LOW: ("TikTok dưới ngưỡng tin cậy", "warn"),
    FLAG_TIKTOK_NONE: ("Không tìm được video TikTok", "warn"),
    FLAG_NO_MENU_PHOTOS: ("Không có ảnh thực đơn", "warn"),
    FLAG_MENU_NOT_JSON: ("Thực đơn không ra JSON", "warn"),
    FLAG_OLD_ADDRESS_GUESSED: ("old_address do Gemini đoán", "warn"),
    FLAG_OLD_ADDRESS_MISSING: ("Thiếu old_address", "warn"),
    FLAG_GEMINI_MISSING_FIELDS: ("Gemini thiếu trường", "warn"),
    FLAG_FEW_SECONDARY_PHOTOS: ("Thiếu ảnh phụ", "warn"),
    FLAG_NO_COVER_PHOTO: ("Thiếu ảnh đại diện", "warn"),
    FLAG_HOURS_INCOMPLETE: ("Bảng giờ không đủ 7 ngày", "warn"),
    FLAG_CATEGORY_UNKNOWN: ("Không đọc được nhãn ngành Google", "warn"),
    FLAG_FACEBOOK_UNVERIFIED: ("Không xác minh được Trang Facebook", "warn"),
    FLAG_FACEBOOK_UNAVAILABLE: ("Facebook không truy cập được", "warn"),
}

# Cờ nghĩa là "chạy lại cũng thế, cần người quyết định" -> worker KHÔNG retry.
TERMINAL_FLAGS = frozenset({WrongPlaceError.code, FLAG_NOT_FOOD})


def flag_label(code: str) -> str:
    return FLAG_LABELS.get(code, (code, "warn"))[0]


def flag_severity(code: str) -> str:
    return FLAG_LABELS.get(code, (code, "warn"))[1]


# -- Bắc cầu từ dữ liệu cũ --------------------------------------------------
#
# 141 POI đã gán nhãn từ trước khi `flags` tồn tại. Tín hiệu chẩn đoán của chúng
# CÓ SẴN — chỉ là nằm trong câu cảnh báo tiếng Việt. Không bắc cầu thì hàng đợi
# triage rỗng trơn đúng lúc cần nó nhất, và người dùng phải chạy lại cả 141 POI
# chỉ để có được thứ đã nằm sẵn trên đĩa.
#
# Khớp theo cụm từ ĐẶC TRƯNG và ỔN ĐỊNH của từng câu cảnh báo, không khớp theo
# hình dạng chung — cùng một bài học với `_plausible_ward`: lọc theo hình dạng
# chuỗi luôn dính dương tính giả.
_WARNING_PATTERNS: tuple[tuple[str, str], ...] = (
    ("do gemini suy đoán", FLAG_OLD_ADDRESS_GUESSED),
    ("không lấy được tên phường trước sáp nhập", FLAG_OLD_ADDRESS_MISSING),
    ("bỏ qua bước địa chỉ cũ", FLAG_OLD_ADDRESS_MISSING),
    ("gemini không cung cấp", FLAG_GEMINI_MISSING_FIELDS),
    ("không có ảnh thực đơn nào", FLAG_NO_MENU_PHOTOS),
    ("không có mục thực đơn", FLAG_NO_MENU_PHOTOS),
    ("không tìm thấy nút mở gallery", FLAG_NO_MENU_PHOTOS),
    ("vẫn không ra json", FLAG_MENU_NOT_JSON),
    ("bảng giờ mở cửa không đủ", FLAG_HOURS_INCOMPLETE),
    ("ảnh phụ không trùng nhau", FLAG_FEW_SECONDARY_PHOTOS),
    ("không lấy được ảnh đại diện", FLAG_NO_COVER_PHOTO),
    ("raw_url sẽ để trống", FLAG_TIKTOK_LOW),
    ("không tìm được video nào", FLAG_TIKTOK_NONE),
    # Câu cũ ("KHÔNG PHẢI FOOD") của 141 POI đã chạy trước khi có profile lưu
    # trú, và câu mới trung tính. Giữ CẢ HAI: bản ghi cũ trên đĩa không được
    # viết lại, nên bỏ needle cũ là hàng đợi triage mất đúng nhóm block.
    ("không phải food", FLAG_NOT_FOOD),
    ("sai nhóm ngành", FLAG_NOT_FOOD),
    ("có thể lấy nhầm quán", WrongPlaceError.code),
    ("không đọc được nhãn ngành", FLAG_CATEGORY_UNKNOWN),
    ("không trang nào khớp địa chỉ", FLAG_FACEBOOK_UNVERIFIED),
    ("chưa đăng nhập hoặc không có kết quả", FLAG_FACEBOOK_UNAVAILABLE),
)


def flags_from_warnings(warnings: dict[str, list[str]]) -> dict[str, list[str]]:
    """Suy cờ triage từ các câu cảnh báo tiếng Việt của những lần chạy cũ.

    Chỉ dùng cho bản ghi CHƯA có `flags`. Bản ghi mới ghi cờ trực tiếp lúc chạy,
    không đi qua đây — đối chiếu chuỗi luôn kém tin cậy hơn nguồn gốc.
    """
    out: dict[str, list[str]] = {}
    for step, messages in (warnings or {}).items():
        for message in messages:
            low = (message or "").casefold()
            for needle, code in _WARNING_PATTERNS:
                if needle in low:
                    bucket = out.setdefault(step, [])
                    if code not in bucket:
                        bucket.append(code)
    return out
