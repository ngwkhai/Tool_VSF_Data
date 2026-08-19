"""Gộp các row.tsv của một đợt thành MỘT file tổng hợp.

Chuyển từ `scripts/merge_rows.py` vào đây để CLI, giao diện và script cũ dùng
CHUNG một đường code — trước đây giao diện muốn xuất thì phải gọi script qua
subprocess hoặc chép lại logic, cả hai đều dẫn tới hai bản trôi lệch nhau.

Hai điểm không được làm khác đi:

* Sắp xếp theo SỐ THỨ TỰ thư mục (`1_slug`, `2_slug`, ...), không theo chữ cái —
  `10_` phải đứng sau `9_`, sắp xếp chuỗi thì không.
* Đọc bằng `csv` chứ không nối file bằng `cat`: cột bình luận chứa xuống dòng nên
  mỗi row.tsv trải nhiều dòng vật lý, nối thô là vỡ cấu trúc.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import COLUMNS

_INDEX = re.compile(r"^(\d+)_")


def sort_key(folder: Path) -> tuple[int, str]:
    m = _INDEX.match(folder.name)
    return (int(m.group(1)) if m else 10**9, folder.name)


@dataclass
class MergeResult:
    path: Path | None = None
    rows: list[dict[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def with_url(self) -> int:
        return sum(1 for r in self.rows if r.get("raw_url"))


def collect(out_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Đọc row.tsv của mọi POI trong thư mục đợt, theo đúng thứ tự số."""
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    folders = sorted((p for p in out_dir.iterdir() if p.is_dir()), key=sort_key)
    for folder in folders:
        tsv = folder / "row.tsv"
        if not tsv.exists():
            skipped.append(f"{folder.name}: không có row.tsv")
            continue
        with tsv.open(encoding="utf-8") as fh:
            found = list(csv.DictReader(fh, delimiter="\t"))
        if not found:
            skipped.append(f"{folder.name}: row.tsv rỗng")
            continue
        rows.append(found[0])
    return rows, skipped


def write(rows: list[dict[str, str]], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            # Chỉ giữ đúng 73 cột của schema, phòng khi row.tsv cũ có cột thừa/thiếu.
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return target


def merge(out_dir: str | Path, target: str | Path | None = None) -> MergeResult:
    """Gộp cả đợt. `target` bỏ trống -> `<out_dir>/tong_hop_<N>_poi.tsv`."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"Không thấy thư mục {out_dir}")

    rows, skipped = collect(out_dir)
    result = MergeResult(rows=rows, skipped=skipped)
    if not rows:
        return result

    path = Path(target) if target else out_dir / f"tong_hop_{len(rows)}_poi.tsv"
    result.path = write(rows, path)
    return result
