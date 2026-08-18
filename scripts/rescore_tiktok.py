"""Chấm lại ứng viên TikTok của các POI ĐÃ CÀO, so thứ hạng cũ với mới.

Chạy hoàn toàn offline trên data.json sẵn có — KHÔNG tốn một request TikTok nào,
nên có thể chạy đi chạy lại thoải mái mỗi lần chỉnh trọng số.

Đây là thứ đã phát hiện ra cả ba guard trong tiktok.py (Plus code, token author
4 ký tự, stoplist ngành): mỗi guard ứng với một ca nó làm hỏng khi chưa có.

    .venv/bin/python scripts/rescore_tiktok.py
    .venv/bin/python scripts/rescore_tiktok.py --threshold      # dò ngưỡng
    .venv/bin/python scripts/rescore_tiktok.py --poi "Đợi Café" # xem 1 POI
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vsf.config import PROJECT_ROOT  # noqa: E402
from vsf.sites.tiktok import _HANDLE, rank_candidates  # noqa: E402


def load_records() -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(PROJECT_ROOT.glob("output*/*/data.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("tiktok"):
            out.append((path, data))
    return out


def prepare(cands: list[dict]) -> list[dict]:
    """Dựng lại `handle` cho dữ liệu cũ (data.json cũ chỉ lưu nickname ở `author`)."""
    fresh = []
    for c in cands:
        c = dict(c)
        m = _HANDLE.search(c.get("url") or "")
        c["handle"] = m.group(1) if m else ""
        fresh.append(c)
    return fresh


def rescore(data: dict) -> tuple[list[dict], list[dict]]:
    old = prepare(data["tiktok"])
    address = (data.get("google_maps") or {}).get("address", "")
    new = rank_candidates(data.get("poi_name", ""), [dict(c) for c in old], address)
    return old, new


def show(poi: str, old: list[dict], new: list[dict], limit: int = 3) -> None:
    print(f"\n### {poi[:56]}")
    for rank, c in enumerate(new[:limit]):
        was = next((i for i, o in enumerate(old) if o["url"] == c["url"]), "?")
        b = c["score_breakdown"]
        flags = ",".join(f"{k}{v}" for k, v in b.items() if v)
        mark = "→" if rank == 0 else " "
        print(
            f" {mark} cũ#{was} điểm_cũ={c.get('match_score'):<5} mới={c['score']:<7}"
            f" {flags:38} @{str(c.get('author'))[:24]}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poi", help="Chỉ xem một POI")
    ap.add_argument("--threshold", action="store_true", help="Dò ngưỡng tin cậy")
    ap.add_argument("--limit", type=int, default=12, help="Số POI đổi hạng in ra")
    args = ap.parse_args()

    records = load_records()
    if not records:
        print("Không tìm thấy data.json nào có ứng viên TikTok.")
        return 1

    changed, tops = [], []
    for _path, data in records:
        poi = data.get("poi_name", "")
        if args.poi and args.poi.lower() not in poi.lower():
            continue
        old, new = rescore(data)
        tops.append((new[0]["score"], poi))
        if new and old and new[0]["url"] != old[0]["url"]:
            changed.append((poi, old, new))
        if args.poi:
            show(poi, old, new)

    if args.poi:
        return 0

    n = len(records)
    print(f"POI có ứng viên: {n}")
    print(f"POI ĐỔI ứng viên #1: {len(changed)}  ({100 * len(changed) / n:.0f}%)")

    if args.threshold:
        print("\n--- Phân bố điểm #1 (chọn confidence_threshold từ đây) ---")
        tops.sort()
        for cut in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
            below = sum(1 for s, _ in tops if s < cut)
            print(f"  ngưỡng {cut:<5} -> {below:>3}/{n} POI bị bỏ trống ({100 * below / n:.0f}%)")
        print("\n  10 POI điểm thấp nhất:")
        for s, poi in tops[:10]:
            print(f"    {s:<7} {poi[:58]}")
        return 0

    for poi, old, new in changed[: args.limit]:
        show(poi, old, new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
