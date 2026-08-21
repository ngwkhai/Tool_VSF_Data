"""Dựng lại hàng đợi từ những gì có thật trên đĩa.

Đây là thứ khiến việc thêm SQLite trở nên an toàn: DB không giữ dữ liệu nào mà
đĩa không có. Xoá `state/vsf.db` rồi chạy `vsf batch reindex` là mọi POI đã gán
nhãn từ trước hiện lại đầy đủ trong giao diện — kể cả 121 POI có từ trước khi
chế độ lô tồn tại.

Idempotent: chạy bao nhiêu lần cũng ra cùng một kết quả.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..errors import flags_from_warnings
from ..models import POIRecord
from . import store
from .outcome import derive_status

# Thư mục POI theo quy ước `<số>_<slug>`; không có số thì seq suy theo thứ tự tên.
_NUMBERED = re.compile(r"^(\d+)_")


def _load(data_json: Path) -> POIRecord | None:
    """Nạp một data.json, bỏ qua file hỏng thay vì làm gãy cả lượt reindex."""
    try:
        data = json.loads(data_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("poi_name"):
        return None
    # `slug` được suy lại từ tên thư mục thật, y hệt POIRecord.load_or_new — thư
    # mục có thể đã được đổi tên sau khi ghi.
    data.pop("slug", None)
    try:
        record = POIRecord(**data)
    except TypeError:
        # data.json của một phiên bản có khoá mà bản hiện tại không biết.
        known = {f for f in POIRecord.__dataclass_fields__}
        record = POIRecord(**{k: v for k, v in data.items() if k in known})
    record.slug = data_json.parent.name

    # Bản ghi có từ trước khi `flags` tồn tại: suy cờ từ câu cảnh báo tiếng Việt
    # đã lưu. KHÔNG ghi ngược vào data.json — đây là suy diễn, không phải dữ liệu
    # gốc, và data.json chỉ nên chứa thứ pipeline thực sự quan sát được.
    if not record.flags and record.warnings:
        record.flags = flags_from_warnings(record.warnings)
    return record


def scan_dir(out_dir: Path) -> list[tuple[int, POIRecord]]:
    """Đọc mọi POI trong một thư mục đợt, kèm số thứ tự suy từ tên thư mục."""
    found: list[tuple[int, POIRecord]] = []
    for folder in sorted(out_dir.iterdir() if out_dir.is_dir() else []):
        data_json = folder / "data.json"
        if not data_json.is_file():
            continue
        record = _load(data_json)
        if record is None:
            continue
        match = _NUMBERED.match(folder.name)
        found.append((int(match.group(1)) if match else 0, record))

    # Thư mục không đánh số vẫn phải có seq ổn định để bảng job sắp xếp được.
    next_seq = max((s for s, _ in found), default=0) + 1
    result: list[tuple[int, POIRecord]] = []
    for seq, record in found:
        if seq == 0:
            seq, next_seq = next_seq, next_seq + 1
        result.append((seq, record))
    return result


def reindex_dir(
    out_dir: str | Path, name: str = "", db_path: Path | None = None
) -> dict[str, Any]:
    """Nạp một thư mục đợt vào DB. Trả về thống kê tóm tắt."""
    path = Path(out_dir)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    rel = str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)

    store.init(db_path)
    records = list(scan_dir(path))

    # Profile của cả lô, đọc từ data.json trên đĩa. Quét TRƯỚC khi tạo lô để lô
    # mới ra đời đã đúng bộ dataset; lô cũ thì chốt lại bên dưới, vì reindex đọc
    # từ nguồn sự thật nên nó được phép sửa chỉ mục. Không có bước này thì mọi lô
    # dựng lại bằng reindex đều mang nhãn 'food' — trang thống kê đếm ô trống
    # theo bộ cột sai, và file tổng hợp xuất theo profile của lô cũng sai luôn.
    # Thư mục trộn hai profile (hoặc rỗng) thì KHÔNG chốt gì cả — để nguyên giá
    # trị đang có thay vì đoán bừa; `batch export` sẽ báo lỗi rõ ràng khi tới đó.
    found = {getattr(r, "profile", "") or "food" for _, r in records}
    profile = next(iter(found)) if len(found) == 1 else None

    batch_id = store.get_or_create_batch(
        rel, name or rel, db_path=db_path, profile=profile or "food"
    )
    if profile and store.get_batch(batch_id, db_path=db_path)["profile"] != profile:
        store.set_batch_profile(batch_id, profile, db_path=db_path)

    counts: dict[str, int] = {}
    for seq, record in records:
        status, error_code, error_message = derive_status(record)
        counts[status] = counts.get(status, 0) + 1
        store.upsert_job(
            batch_id,
            record.poi_name,
            seq=seq,
            address_hint=record.address_hint,
            # Round-trip qua đĩa. Cùng với bộ chặn `_STICKY` ở store, place_id do
            # người dùng nạp không bao giờ bị reindex xoá mất.
            place_id=getattr(record, "place_id_hint", ""),
            # Cũng round-trip qua đĩa: `profile` nằm trong data.json nên reindex
            # biết chắc, không phải đoán từ DB.
            profile=getattr(record, "profile", "") or "food",
            db_path=db_path,
            # reindex là nguồn sự thật -> ghi đè cả trạng thái, vì nó đọc thẳng
            # từ data.json chứ không phải đoán.
            status=status,
            slug=record.slug,
            flags_json=json.dumps(record.all_flags(), ensure_ascii=False),
            steps_json=json.dumps(record.steps, ensure_ascii=False),
            error_code=error_code,
            error_message=error_message,
            finished_at=record.updated_at,
        )
    return {"batch_id": batch_id, "out_dir": rel, "counts": counts, "total": sum(counts.values())}


def reindex_all(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Quét mọi thư mục `output*` ở gốc dự án."""
    results = []
    for path in sorted(PROJECT_ROOT.glob("output*")):
        if not path.is_dir():
            continue
        # Đợt lồng nhau kiểu `output_12/8`: thư mục con chứa POI, không phải POI.
        subdirs = [p for p in sorted(path.iterdir()) if p.is_dir()]
        if subdirs and not any((p / "data.json").is_file() for p in subdirs):
            for sub in subdirs:
                results.append(reindex_dir(sub, db_path=db_path))
            continue
        results.append(reindex_dir(path, db_path=db_path))
    return results
