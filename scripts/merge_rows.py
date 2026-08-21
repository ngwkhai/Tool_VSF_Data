"""Gộp các row.tsv của một đợt gán nhãn thành MỘT file tổng hợp.

    .venv/bin/python scripts/merge_rows.py output_18_8
    .venv/bin/python scripts/merge_rows.py output_18_8 -o output_18_8/tong_hop.tsv

Logic thật nằm ở `vsf.batch.export` — CLI (`vsf batch export`), giao diện web và
script này dùng chung một đường code. Script giữ lại vì đã đi vào thói quen dùng
và được nhắc trong tài liệu.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vsf.batch.export import merge  # noqa: E402
from vsf.profiles import get_profile  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", help="Thư mục đợt gán nhãn, vd output_18_8")
    ap.add_argument(
        "-o", "--output", help="Đường dẫn file tổng hợp (mặc định: tong_hop_<N>_poi.tsv)"
    )
    args = ap.parse_args()

    try:
        result = merge(args.out_dir, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1

    if not result.rows:
        print("Không gom được dòng nào.")
        return 1

    n_cols = len(get_profile(result.profile).COLUMNS)
    print(
        f"Đã ghi {result.path}  "
        f"({len(result.rows)} dòng, {n_cols} cột, profile {result.profile})"
    )
    print(f"  có raw_url: {result.with_url} | để trống: {len(result.rows) - result.with_url}")
    for note in result.skipped:
        print(f"  [bỏ qua] {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
