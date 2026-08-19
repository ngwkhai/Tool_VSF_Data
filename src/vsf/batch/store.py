"""Hàng đợi lô trên SQLite thuần stdlib.

Không dùng ORM: dự án đang có đúng 3 dependency runtime, và toàn bộ nhu cầu ở đây
là vài câu INSERT/UPDATE/SELECT. Thêm SQLAlchemy để đổi lấy chừng đó là lỗ.

Mỗi thao tác mở một connection riêng thay vì giữ một connection dùng chung:
worker chạy trong thread nền còn API trả lời ở thread khác, mà connection sqlite3
mặc định không chia sẻ được giữa các thread. Ở quy mô vài trăm dòng, chi phí mở
connection là không đáng kể so với một lượt Gemini 360 giây.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "state" / "vsf.db"

# Trạng thái job.
#   queued       — chờ tới lượt
#   running      — worker đang chạy
#   done         — mọi bước xong (có thể vẫn còn cờ cảnh báo)
#   failed       — có bước hỏng vì lý do TẠM THỜI -> đáng thử lại
#   needs_review — hỏng vì lý do dữ liệu (lấy nhầm quán, không phải FOOD).
#                  Chạy lại không sửa được, phải có người quyết định.
#   cancelled    — người dùng huỷ
JOB_STATUSES = ("queued", "running", "done", "failed", "needs_review", "cancelled")

# Trạng thái lô. `paused` là cờ hợp tác: worker đọc giữa hai POI rồi tự dừng.
BATCH_STATUSES = ("idle", "running", "paused", "done", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    -- Một đợt gán nhãn = một thư mục output. Quy ước này đã có sẵn trong dự án
    -- (output_18_8/, output_15_8/...) nên dùng luôn làm khoá tự nhiên: `batch add`
    -- lần hai vào cùng thư mục là THÊM POI vào đợt cũ, không đẻ ra đợt trùng.
    out_dir    TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'idle',
    note       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS job (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    -- Khoá tự nhiên là (batch_id, poi_name) chứ KHÔNG phải seq: nạp danh sách
    -- lần hai hay chạy reindex đều nhận ra đúng POI cũ, kể cả khi số thứ tự đã
    -- được đánh lại. Một đợt không có lý do gì chứa hai lần cùng một POI.
    poi_name      TEXT NOT NULL,
    address_hint  TEXT NOT NULL DEFAULT '',
    -- Google place_id người dùng cung cấp sẵn. Đây là cách neo MẠNH NHẤT: mở
    -- thẳng đúng địa điểm thay vì tìm theo tên rồi hi vọng Google trả đúng quán.
    place_id      TEXT NOT NULL DEFAULT '',
    force_food    INTEGER NOT NULL DEFAULT 0,
    only_step     TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    slug          TEXT NOT NULL DEFAULT '',
    attempts      INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT,
    finished_at   TEXT,
    error_code    TEXT,
    error_message TEXT,
    flags_json    TEXT NOT NULL DEFAULT '[]',
    steps_json    TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    UNIQUE (batch_id, poi_name)
);

CREATE TABLE IF NOT EXISTS event (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER,
    job_id   INTEGER,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    step     TEXT,
    payload  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_job_batch_status ON job (batch_id, status);
CREATE INDEX IF NOT EXISTS idx_job_seq          ON job (batch_id, seq);
CREATE INDEX IF NOT EXISTS idx_event_batch      ON event (batch_id, id);
CREATE INDEX IF NOT EXISTS idx_event_job        ON event (job_id, id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Mở connection đã bật WAL + khoá ngoại, tự commit hoặc rollback."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL: worker ghi tiến độ trong khi UI đọc bảng job liên tục — không có WAL
    # thì mỗi lần ghi là một lần UI bị "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Cột thêm vào sau khi đã có DB chạy thật. `CREATE TABLE IF NOT EXISTS` không đụng
# tới bảng đã tồn tại, nên cột mới phải tự thêm bằng ALTER — nếu không, DB cũ sẽ
# ném "no such column" ngay lần ghi đầu tiên.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("job", "place_id", "TEXT NOT NULL DEFAULT ''"),
)

# Cột mang Ý ĐỊNH CỦA NGƯỜI DÙNG: giá trị rỗng không bao giờ được ghi đè giá trị
# đã có. Xem giải thích ở `upsert_job`.
_STICKY = frozenset({"address_hint", "place_id"})


def init(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for table, column, spec in _MIGRATIONS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")


# -- Lô ---------------------------------------------------------------------


def get_or_create_batch(
    out_dir: str, name: str = "", db_path: Path | None = None
) -> int:
    """Trả về id của lô ứng với `out_dir`, tạo mới nếu chưa có."""
    out_dir = str(out_dir)
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM batch WHERE out_dir = ?", (out_dir,)).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO batch (name, out_dir, created_at, status) VALUES (?,?,?,'idle')",
            (name or out_dir, out_dir, now()),
        )
        return int(cur.lastrowid)


def list_batches(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Danh sách lô kèm số job theo từng trạng thái — đủ để vẽ thanh tiến độ."""
    with connect(db_path) as conn:
        batches = [dict(r) for r in conn.execute("SELECT * FROM batch ORDER BY id DESC")]
        counts: dict[int, dict[str, int]] = {}
        for r in conn.execute("SELECT batch_id, status, COUNT(*) n FROM job GROUP BY 1,2"):
            counts.setdefault(int(r["batch_id"]), {})[r["status"]] = int(r["n"])
    for b in batches:
        b["counts"] = counts.get(int(b["id"]), {})
        b["total"] = sum(b["counts"].values())
    return batches


def get_batch(batch_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()
    return dict(row) if row else None


def set_batch_status(batch_id: int, status: str, db_path: Path | None = None) -> None:
    if status not in BATCH_STATUSES:
        raise ValueError(f"Trạng thái lô không hợp lệ: {status!r}")
    with connect(db_path) as conn:
        conn.execute("UPDATE batch SET status = ? WHERE id = ?", (status, batch_id))


def delete_batch(batch_id: int, db_path: Path | None = None) -> int:
    """Xoá lô khỏi CHỈ MỤC. Trả về số job bị xoá theo.

    **Không đụng tới đĩa.** `data.json` và `row.tsv` trong thư mục output vẫn
    nguyên vẹn, và `vsf batch reindex` dựng lại được lô này bất cứ lúc nào. Đây
    là lối thoát cho trường hợp gõ nhầm tên thư mục lúc nạp danh sách — không có
    nó thì một lỗi đánh máy sẽ nằm lại trong giao diện vĩnh viễn.
    """
    with connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) c FROM job WHERE batch_id = ?", (batch_id,)).fetchone()
        conn.execute("DELETE FROM event WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM job WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM batch WHERE id = ?", (batch_id,))
        return int(n["c"])


def batch_status(batch_id: int, db_path: Path | None = None) -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT status FROM batch WHERE id = ?", (batch_id,)).fetchone()
    return row["status"] if row else "idle"


# -- Job --------------------------------------------------------------------


def upsert_job(
    batch_id: int,
    poi_name: str,
    *,
    seq: int,
    address_hint: str = "",
    place_id: str = "",
    force_food: bool = False,
    only_step: str | None = None,
    db_path: Path | None = None,
    **extra: Any,
) -> int:
    """Thêm job, hoặc cập nhật job đã có cùng (batch_id, poi_name).

    Idempotent: nạp lại cùng danh sách hai lần không đẻ ra job trùng, và KHÔNG
    reset trạng thái của job đã chạy xong — nạp thêm POI vào đợt đang dở là thao
    tác bình thường, không được xoá công đã làm.
    """
    fields: dict[str, Any] = {
        "seq": seq,
        "address_hint": address_hint,
        "place_id": place_id,
        "force_food": int(bool(force_food)),
        "only_step": only_step,
        "updated_at": now(),
        **extra,
    }
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    # Chỉ ghi đè các cột được truyền vào; `status`/`attempts` giữ nguyên trừ khi
    # người gọi cố ý truyền qua **extra (reindex làm thế).
    #
    # `_STICKY`: giá trị do NGƯỜI DÙNG nhập, không bao giờ được để một chuỗi rỗng
    # xoá mất. `reindex` đọc từ đĩa và không biết place_id, nên nếu ghi đè thẳng
    # thì chỉ cần chạy `vsf batch reindex` một lần là bay sạch place_id vừa nạp —
    # hỏng trong im lặng, và chỉ lộ ra ở lần chạy sau khi Google trả nhầm quán.
    updates = ", ".join(
        f"{c}=CASE WHEN excluded.{c} IS NULL OR excluded.{c}='' THEN job.{c} ELSE excluded.{c} END"
        if c in _STICKY
        else f"{c}=excluded.{c}"
        for c in fields
    )
    with connect(db_path) as conn:
        cur = conn.execute(
            f"INSERT INTO job (batch_id, poi_name, {cols}) VALUES (?, ?, {marks}) "
            f"ON CONFLICT (batch_id, poi_name) DO UPDATE SET {updates}",
            (batch_id, poi_name, *fields.values()),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = conn.execute(
            "SELECT id FROM job WHERE batch_id = ? AND poi_name = ?", (batch_id, poi_name)
        ).fetchone()
        return int(row["id"])


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    job["flags"] = json.loads(job.pop("flags_json") or "[]")
    job["steps"] = json.loads(job.pop("steps_json") or "{}")
    job["force_food"] = bool(job["force_food"])
    return job


def list_jobs(
    batch_id: int | None = None,
    *,
    status: str | None = None,
    flag: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    where, params = [], []
    if batch_id is not None:
        where.append("batch_id = ?")
        params.append(batch_id)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM job {clause} ORDER BY batch_id DESC, seq ASC", params
        ).fetchall()
    jobs = [_decode(r) for r in rows]
    # Lọc cờ ở Python: cờ nằm trong JSON, và ở quy mô vài trăm dòng thì LIKE trên
    # chuỗi JSON vừa khó đọc vừa dễ khớp nhầm cờ có tên là tiền tố của cờ khác.
    if flag:
        jobs = [j for j in jobs if flag in j["flags"]]
    return jobs


def get_job(job_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return _decode(row) if row else None


def claim_next(batch_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    """Lấy job kế tiếp và đánh dấu `running` trong CÙNG một transaction.

    Dù hiện chỉ chạy một worker, việc claim phải nguyên tử: nếu không, mở nhầm
    hai tiến trình `vsf batch run` là hai Chrome cùng cào một POI và giẫm lên
    data.json của nhau.
    """
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        # CHỈ nhận `queued`. Nhận cả `failed` sẽ thành vòng lặp vô hạn: job hết
        # lượt thử bị chốt là `failed`, rồi bị claim lại ngay ở vòng kế tiếp,
        # hỏng tiếp, mãi mãi. Chạy lại job hỏng là thao tác CÓ CHỦ Ý của người
        # dùng (`vsf batch retry` -> reset_jobs đưa về `queued`), không phải việc
        # worker tự làm.
        row = conn.execute(
            "SELECT * FROM job WHERE batch_id = ? AND status = 'queued' ORDER BY seq ASC LIMIT 1",
            (batch_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE job SET status='running', started_at=?, attempts=attempts+1, "
            "updated_at=? WHERE id=?",
            (now(), now(), row["id"]),
        )
        job = _decode(row)
    job["status"] = "running"
    job["attempts"] = int(job["attempts"]) + 1
    return job


def finish_job(
    job_id: int,
    *,
    status: str,
    slug: str = "",
    flags: list[str] | None = None,
    steps: dict[str, str] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    db_path: Path | None = None,
) -> None:
    if status not in JOB_STATUSES:
        raise ValueError(f"Trạng thái job không hợp lệ: {status!r}")
    with connect(db_path) as conn:
        # `only_step=NULL`: chỉ thị "chỉ chạy bước X" là DÙNG MỘT LẦN. Để dính lại
        # thì mọi lần chạy sau của job đó vĩnh viễn chỉ chạy đúng một bước — người
        # dùng bấm "Chạy" rồi tưởng cả 6 bước đã chạy, trong khi 5 bước bị bỏ qua
        # trong im lặng.
        conn.execute(
            "UPDATE job SET status=?, slug=?, flags_json=?, steps_json=?, error_code=?, "
            "error_message=?, finished_at=?, updated_at=?, only_step=NULL WHERE id=?",
            (
                status,
                slug,
                json.dumps(flags or [], ensure_ascii=False),
                json.dumps(steps or {}, ensure_ascii=False),
                error_code,
                error_message,
                now(),
                now(),
                job_id,
            ),
        )


def reset_jobs(
    batch_id: int, *, only_failed: bool = True, db_path: Path | None = None
) -> int:
    """Đưa job về hàng đợi để chạy lại. Trả về số job bị ảnh hưởng.

    `needs_review` KHÔNG nằm trong diện reset mặc định: chạy lại một POI bị chặn
    vì lấy nhầm quán chỉ tốn thêm một vòng Gemini rồi lại chặn y hệt.
    """
    clause = "status = 'failed'" if only_failed else "status != 'running'"
    with connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE job SET status='queued', error_code=NULL, error_message=NULL, "
            f"updated_at='{now()}' WHERE batch_id = ? AND {clause}",
            (batch_id,),
        )
        return cur.rowcount


# -- Sự kiện ----------------------------------------------------------------


def add_event(
    kind: str,
    *,
    batch_id: int | None = None,
    job_id: int | None = None,
    step: str | None = None,
    payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO event (batch_id, job_id, ts, kind, step, payload) VALUES (?,?,?,?,?,?)",
            (batch_id, job_id, now(), kind, step, json.dumps(payload or {}, ensure_ascii=False)),
        )


def list_events(
    *,
    batch_id: int | None = None,
    job_id: int | None = None,
    after_id: int = 0,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    where, params = ["id > ?"], [after_id]
    if batch_id is not None:
        where.append("batch_id = ?")
        params.append(batch_id)
    if job_id is not None:
        where.append("job_id = ?")
        params.append(job_id)
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM event WHERE {' AND '.join(where)} ORDER BY id ASC LIMIT ?", params
        ).fetchall()
    out = []
    for r in rows:
        e = dict(r)
        e["payload"] = json.loads(e["payload"] or "{}")
        out.append(e)
    return out
