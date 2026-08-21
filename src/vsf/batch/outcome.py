"""Suy trạng thái job từ nội dung một POIRecord.

Dùng chung cho worker (sau khi chạy xong) và reindex (đọc từ đĩa). Phải là MỘT
hàm duy nhất: nếu worker và reindex suy trạng thái khác nhau thì chạy
`vsf batch reindex` sẽ lặng lẽ đổi trạng thái của những job vừa chạy xong.
"""

from __future__ import annotations

from ..errors import TERMINAL_FLAGS
from ..models import POIRecord
from ..profiles import steps_for


def derive_status(record: POIRecord) -> tuple[str, str | None, str | None]:
    """-> (status, error_code, error_message).

    Thứ tự xét là có chủ ý:

    1. **Cờ chốt trước tiên.** `wrong_place` / `not_food` nghĩa là chạy lại cũng
       thế — phải có người quyết định. Xếp chúng vào `failed` thì cơ chế thử lại
       sẽ đốt thêm một vòng Gemini để nhận đúng kết luận cũ.
    2. Bước hỏng -> `failed` (đáng thử lại).
    3. Còn bước chưa chạy -> `queued`.
    4. Hết -> `done`.
    """
    flags = record.all_flags()
    step_runs = getattr(record, "step_runs", None) or {}

    for code in flags:
        if code in TERMINAL_FLAGS:
            message = next(
                (m for step in record.warnings for m in record.warnings[step]),
                None,
            )
            return "needs_review", code, message

    # Duyệt CHÍNH `record.steps` chứ không phải danh sách bước của profile: một
    # bước hỏng nhưng không nằm trong STEPS hiện tại (đổi profile, đổi tên bước)
    # vẫn phải lộ ra là `failed`, không được biến mất thành `done`.
    failed = [s for s, v in record.steps.items() if v == "failed"]
    if failed:
        info = step_runs.get(failed[0]) or {}
        return (
            "failed",
            info.get("error_code") or "error",
            info.get("error_message") or f"bước {failed[0]} hỏng",
        )

    if not record.steps:
        return "queued", None, None

    # Chỉ xét các bước ĐÃ CÓ trong bản ghi. Một bước mới được thêm vào STEPS sau
    # này (như `facebook` ở main-v2) vắng mặt trong 139 bản ghi cũ; coi đó là
    # "chưa xong" sẽ đẩy toàn bộ công việc đã hoàn thành ngược về hàng đợi và
    # chạy lại cả trăm POI. Bước thiếu được báo riêng qua `missing_steps()` để
    # người dùng tự quyết có chạy bù hay không.
    #
    # `skipped` tính là đã xử lý xong: các bước sau `maps` bị bỏ qua là hệ quả có
    # chủ ý của cổng chặn, không phải việc còn dang dở.
    if any(v not in ("ok", "skipped") for v in record.steps.values()):
        return "queued", None, None

    return "done", None, None


def missing_steps(record: POIRecord) -> list[str]:
    """Các bước trong STEPS chưa từng chạy cho bản ghi này.

    Gần như luôn là `facebook` với dữ liệu cũ. UI dùng để mời chạy bù đúng bước
    còn thiếu (`--only facebook`) thay vì cào lại từ đầu.

    Xét theo danh sách bước CỦA PROFILE bản ghi: POI lưu trú không có bước `menu`
    và không bao giờ nên bị báo là thiếu nó.
    """
    return [s for s in steps_for(record) if s not in record.steps]
