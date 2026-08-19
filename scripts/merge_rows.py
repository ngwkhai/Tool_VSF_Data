"""Gộp các row.tsv của một đợt gán nhãn thành MỘT file tổng hợp.

    .venv/bin/python scripts/merge_rows.py output_18_8
    .venv/bin/python scripts/merge_rows.py output_18_8 -o output_18_8/tong_hop.tsv

Thứ tự dòng theo SỐ THỨ TỰ thư mục (`1_slug`, `2_slug`, ...) chứ không theo thứ
tự chữ cái — `10_` phải đứng sau `9_`, sắp xếp chuỗi thì không.

Đọc bằng csv chứ không nối file bằng `cat`: cột bình luận chứa xuống dòng nên
mỗi row.tsv trải nhiều dòng vật lý, nối thô sẽ vỡ cấu trúc.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vsf.schema import COLUMNS  # noqa: E402

_INDEX = re.compile(r"^(\d+)_")


def sort_key(folder: Path) -> tuple[int, str]:
    m = _INDEX.match(folder.name)
    return (int(m.group(1)) if m else 10**9, folder.name)


def collect(out_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    for folder in sorted((p for p in out_dir.iterdir() if p.is_dir()), key=sort_key):
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", help="Thư mục đợt gán nhãn, vd output_18_8")
    ap.add_argument("-o", "--output", help="Đường dẫn file tổng hợp (mặc định: tong_hop_<N>_poi.tsv)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        print(f"Không thấy thư mục {out_dir}")
        return 1

    rows, skipped = collect(out_dir)
    if not rows:
        print("Không gom được dòng nào.")
        return 1

    target = Path(args.output) if args.output else out_dir / f"tong_hop_{len(rows)}_poi.tsv"
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            # Chỉ giữ đúng 73 cột của schema, phòng khi row.tsv cũ có cột thừa/thiếu.
            writer.writerow({col: row.get(col, "") for col in COLUMNS})

    have_url = sum(1 for r in rows if r.get("raw_url"))
    print(f"Đã ghi {target}  ({len(rows)} dòng, {len(COLUMNS)} cột)")
    print(f"  có raw_url: {have_url} | để trống: {len(rows) - have_url}")
    for note in skipped:
        print(f"  [bỏ qua] {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
