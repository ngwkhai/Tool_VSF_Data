"""Đọc danh sách POI đầu vào cho một lô.

Nhận ba dạng, tự nhận biết:

1. **CSV/TSV có dòng tiêu đề** chứa cột `name` — kèm được `address`, `place_id`,
   `index`, `force_food`, `only`.
2. **Bảng KHÔNG có tiêu đề**, các cột theo thứ tự: `tên`, `địa chỉ`, `place_id`.
   Đây là thứ dán thẳng ra được từ bảng tính hoặc từ kết quả Google Places, nên
   là dạng hay dùng nhất trong thực tế.
3. **Text thuần**, mỗi dòng một tên POI.

Dòng trống và dòng bắt đầu bằng `#` luôn bị bỏ qua để chú thích được ngay trong
file danh sách.

Bắt người dùng dựng CSV đúng chuẩn chỉ để chạy được là thêm một bước vô ích —
họ đã có sẵn bảng, việc của tool là đọc được nó.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

# Tên cột chấp nhận cho từng trường — người dùng gõ tiếng Việt hay tiếng Anh đều nhận.
_NAME_KEYS = ("name", "poi", "poi_name", "ten", "tên", "ten_poi")
_ADDRESS_KEYS = ("address", "dia_chi", "địa chỉ", "diachi")
_PLACE_ID_KEYS = ("place_id", "placeid", "id")
_INDEX_KEYS = ("index", "seq", "stt", "so_thu_tu")
_FORCE_FOOD_KEYS = ("force_food", "forcefood", "ep_food")
_ONLY_KEYS = ("only", "only_step", "buoc")
_PROFILE_KEYS = ("profile", "dataset", "bo_du_lieu")

_TRUE = {"1", "true", "yes", "y", "x", "co", "có"}

# Place ID của Google: chuỗi base64url dài, không dấu cách. Thực tế bắt đầu bằng
# "ChIJ"/"GhIJ"/"EiQ"/"Ei"… nhưng KHÔNG khoá cứng tiền tố — Google có đổi trong
# quá khứ. Ràng buộc đủ chặt là: đủ dài, chỉ ký tự an toàn URL, và có cả chữ hoa
# lẫn chữ thường (tên quán viết liền không bao giờ như vậy).
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")

# Hai ô trong bảng dán ra thường cách nhau bằng TAB; dán qua vài lớp trung gian
# thì tab hay bị đổi thành nhiều dấu cách. Một dấu cách đơn KHÔNG tính — tên quán
# và địa chỉ đều chứa dấu cách đơn.
_CELL_GAP = re.compile(r"\t+| {2,}")


@dataclass
class ParsedPOI:
    seq: int
    name: str
    address: str = ""
    place_id: str = ""
    force_food: bool = False
    only_step: str | None = None
    # Rỗng = theo profile của cả đợt (cờ --profile của `batch add`). Chỉ khai ở
    # đây khi muốn một dòng lẻ chạy bộ dataset khác với phần còn lại.
    profile: str = ""


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        for actual, value in row.items():
            if (actual or "").strip().lower() == k:
                return (value or "").strip()
    return ""


def looks_like_place_id(token: str) -> bool:
    """Token này có phải Google place_id không?

    Đòi hỏi có cả chữ hoa lẫn chữ thường: nếu không, một tên quán viết liền không
    dấu ("BUNBOTUNGHOANGCHINHANH2") cũng lọt và bị cắt mất khỏi tên.
    """
    token = token.strip()
    if not _PLACE_ID.match(token):
        return False
    return any(c.islower() for c in token) and any(c.isupper() for c in token)


def split_row(line: str) -> tuple[str, str, str]:
    """Tách một dòng không có tiêu đề thành (tên, địa chỉ, place_id).

    Bóc `place_id` TRƯỚC, bằng hình dạng chuỗi chứ không bằng vị trí cột: dán từ
    nguồn khác nhau cho ra số cột khác nhau, nhưng place_id thì luôn nhận ra được.
    Phần còn lại mới tách theo tab / nhiều dấu cách.
    """
    line = line.strip()
    place_id = ""

    cells = [c.strip() for c in _CELL_GAP.split(line) if c.strip()]
    if cells and looks_like_place_id(cells[-1]):
        place_id = cells.pop()
    elif cells:
        # Tab bị nuốt hẳn (dán qua trình soạn thảo trơn): place_id vẫn tách rời
        # bằng một dấu cách ở cuối dòng.
        head, _, tail = cells[-1].rpartition(" ")
        if head and looks_like_place_id(tail):
            place_id = tail
            cells[-1] = head.strip()

    if not cells:
        return "", "", place_id
    if len(cells) == 1:
        # Không tách được tên khỏi địa chỉ -> giữ nguyên làm tên. Đoán bừa ranh
        # giới ở đây là gán cho POI một địa chỉ sai, tệ hơn hẳn việc không có.
        return cells[0], "", place_id

    name = cells[0]
    address = ", ".join(cells[1:])
    return name, address, place_id


def _header_cells(line: str) -> list[str]:
    delimiter = "\t" if "\t" in line else ","
    return [c.strip().lower() for c in next(csv.reader([line], delimiter=delimiter), [])]


def _looks_like_csv(text: str) -> bool:
    """Dòng đầu có phải dòng TIÊU ĐỀ không?

    Chỉ nhìn dòng đầu, và chỉ chấp nhận khi thấy đúng một tên cột đã biết. "Có
    dấu phẩy" không đủ để kết luận là CSV — tên quán và địa chỉ đầy dấu phẩy.
    """
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return any(c in _NAME_KEYS for c in _header_cells(first))


def parse(text: str) -> list[ParsedPOI]:
    """Phân tích nội dung danh sách thành các POI, đã đánh số thứ tự.

    `seq` đánh liên tục theo POI thật (bắt đầu từ 1) để khớp quy ước thư mục
    `<N>_<slug>` sẵn có và cách sắp xếp của phần gộp xuất (regex `^(\\d+)_`).
    Cột `index` trong file ghi đè giá trị này khi người dùng muốn tự đánh số.
    """
    if not text.strip():
        return []

    rows: list[ParsedPOI] = []
    has_explicit_index = False

    if _looks_like_csv(text):
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        delimiter = "\t" if "\t" in first else ","
        for i, row in enumerate(csv.DictReader(io.StringIO(text), delimiter=delimiter), start=1):
            name = _pick(row, _NAME_KEYS)
            if not name or name.startswith("#"):
                continue
            raw_index = _pick(row, _INDEX_KEYS)
            has_explicit_index = has_explicit_index or raw_index.isdigit()
            rows.append(
                ParsedPOI(
                    seq=int(raw_index) if raw_index.isdigit() else i,
                    name=name,
                    address=_pick(row, _ADDRESS_KEYS),
                    place_id=_pick(row, _PLACE_ID_KEYS),
                    force_food=_pick(row, _FORCE_FOOD_KEYS).lower() in _TRUE,
                    only_step=_pick(row, _ONLY_KEYS) or None,
                    profile=_pick(row, _PROFILE_KEYS).strip().lower(),
                )
            )
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            name, address, place_id = split_row(line)
            if not name:
                continue
            rows.append(
                ParsedPOI(seq=len(rows) + 1, name=name, address=address, place_id=place_id)
            )

    # Trùng tên trong cùng một danh sách: giữ lần xuất hiện ĐẦU. Khoá tự nhiên của
    # bảng job là (batch_id, poi_name), nên để lọt bản trùng thì bản sau chỉ lặng
    # lẽ ghi đè bản trước — thà bỏ ngay ở đây cho rõ ràng.
    seen: set[str] = set()
    unique: list[ParsedPOI] = []
    for poi in rows:
        key = poi.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(poi)

    # Đánh lại số liên tục sau khi bỏ bản trùng, TRỪ KHI người dùng tự đánh số.
    # Bỏ một dòng trùng ở giữa mà không đánh lại sẽ để thủng một số thứ tự, và
    # thư mục nhảy từ `3_` sang `5_` trông y như một POI bị mất.
    if not has_explicit_index:
        for i, poi in enumerate(unique, start=1):
            poi.seq = i
    return unique


def parse_file(path: str | Path) -> list[ParsedPOI]:
    return parse(Path(path).read_text(encoding="utf-8"))
