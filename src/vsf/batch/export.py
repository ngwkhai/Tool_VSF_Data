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
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..profiles import DEFAULT, get_profile

_INDEX = re.compile(r"^(\d+)_")


def sort_key(folder: Path) -> tuple[int, str]:
    m = _INDEX.match(folder.name)
    return (int(m.group(1)) if m else 10**9, folder.name)


@dataclass
class MergeResult:
    path: Path | None = None
    rows: list[dict[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    #: Profile của cả đợt — quyết định bộ cột của file tổng hợp.
    profile: str = DEFAULT

    @property
    def with_url(self) -> int:
        return sum(1 for r in self.rows if r.get("raw_url"))


def _folder_profile(folder: Path) -> str:
    """Profile của một POI, đọc từ data.json cạnh row.tsv.

    row.tsv KHÔNG tự nói nó thuộc bộ cột nào (đọc header rồi đoán thì một đợt
    dở dang, cột trống, sẽ đoán sai), nên nguồn sự thật vẫn là data.json — đúng
    như mọi chỗ khác trong tool.
    """
    data_json = folder / "data.json"
    if not data_json.is_file():
        return DEFAULT
    try:
        data = json.loads(data_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT
    return (data.get("profile") or DEFAULT) if isinstance(data, dict) else DEFAULT


def collect(out_dir: Path) -> tuple[list[dict[str, str]], list[str], str]:
    """Đọc row.tsv của mọi POI trong thư mục đợt, theo đúng thứ tự số.

    Trả thêm profile chung của đợt. Một thư mục TRỘN hai profile là lỗi cấu hình
    chứ không phải chuyện bình thường: hai bộ cột khác nhau không gộp được vào
    một file TSV, và im lặng lấy bộ này áp cho bộ kia thì file tổng hợp mất dữ
    liệu mà không có dấu hiệu gì.
    """
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    profiles: dict[str, list[str]] = {}
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
        profiles.setdefault(_folder_profile(folder), []).append(folder.name)

    if len(profiles) > 1:
        detail = "; ".join(
            f"{name} ({len(items)} POI, vd {items[0]})" for name, items in sorted(profiles.items())
        )
        raise ValueError(
            f"Thư mục {out_dir} trộn nhiều profile: {detail}. Hai bộ cột khác nhau "
            "không gộp chung một file TSV được — tách thành hai thư mục đợt riêng."
        )

    return rows, skipped, next(iter(profiles), DEFAULT)


def write(rows: list[dict[str, str]], target: Path, profile: str = DEFAULT) -> Path:
    columns = get_profile(profile).COLUMNS
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            # Chỉ giữ đúng bộ cột của profile, phòng khi row.tsv cũ thừa/thiếu cột.
            writer.writerow({col: row.get(col, "") for col in columns})
    return target


def merge(out_dir: str | Path, target: str | Path | None = None) -> MergeResult:
    """Gộp cả đợt. `target` bỏ trống -> `<out_dir>/tong_hop_<N>_poi.tsv`."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"Không thấy thư mục {out_dir}")

    rows, skipped, profile = collect(out_dir)
    result = MergeResult(rows=rows, skipped=skipped, profile=profile)
    if not rows:
        return result

    path = Path(target) if target else out_dir / f"tong_hop_{len(rows)}_poi.tsv"
    result.path = write(rows, path, profile)
    return result
