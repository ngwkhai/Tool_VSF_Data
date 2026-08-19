"""Test vòng lặp worker mà KHÔNG mở browser.

Thay `Session` bằng một vật giả và thay `HANDLERS` bằng các hàm ghi vào record.
Mọi thứ đáng test ở worker (claim, thử lại, cổng chặn, tạm dừng, xuất file) đều
là logic điều phối — chạy Chrome thật ở đây chỉ làm test chậm và bấp bênh.
"""

from __future__ import annotations

import json

import pytest

from vsf import pipeline
from vsf.batch import store, worker
from vsf.errors import WrongPlaceError
from vsf.models import POIRecord
from vsf.pipeline import STEPS


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Lô một-vài POI trong thư mục tạm, Session giả, không nghỉ giữa các POI."""
    out = tmp_path / "output_test"
    out.mkdir()
    db = tmp_path / "vsf.db"
    store.init(db)

    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "_cfg", lambda: {"max_attempts": 2, "delay_between": 0.0})
    monkeypatch.setattr("vsf.config._OUTPUT_OVERRIDE", out, raising=False)
    monkeypatch.setattr(worker, "set_output_dir", lambda _p: None)
    monkeypatch.setattr(worker, "output_dir", lambda: out)

    batch_id = store.get_or_create_batch(str(out), "Đợt test", db_path=db)
    return {"out": out, "db": db, "batch_id": batch_id}


def _add(env, name, seq):
    return store.upsert_job(env["batch_id"], name, seq=seq, db_path=env["db"])


def _handlers(monkeypatch, behaviour):
    """behaviour: step -> callable(record) hoặc None để bước đó chỉ 'ok'."""
    handlers = {}
    for step in STEPS:
        fn = behaviour.get(step)

        def make(f):
            def handler(_s, record, _poi):
                if f:
                    f(record)

            return handler

        handlers[step] = make(fn)
    monkeypatch.setattr(pipeline, "HANDLERS", handlers)


def test_happy_path_runs_every_step_and_writes_both_files(env, monkeypatch):
    _add(env, "Quán A", 1)
    _handlers(monkeypatch, {"maps": lambda r: r.google_maps.update(name="Quán A")})

    tally = worker.run_batch(env["batch_id"], db_path=env["db"])

    assert tally == {"done": 1}
    folder = env["out"] / "1_quan-a"
    assert (folder / "data.json").is_file()
    assert (folder / "row.tsv").is_file()

    saved = json.loads((folder / "data.json").read_text(encoding="utf-8"))
    assert all(saved["steps"][s] == "ok" for s in STEPS)
    # step_runs phải có thời lượng — đây là thứ giao diện dùng để chỉ ra bước chậm.
    assert "duration_s" in saved["step_runs"]["maps"]


def test_jobs_run_in_seq_order(env, monkeypatch):
    seen: list[str] = []
    _add(env, "Quán J", 10)
    _add(env, "Quán A", 1)
    _handlers(monkeypatch, {"maps": lambda r: seen.append(r.poi_name)})

    worker.run_batch(env["batch_id"], db_path=env["db"])
    assert seen == ["Quán A", "Quán J"]


def test_wrong_place_goes_to_needs_review_without_retrying(env, monkeypatch):
    """Chạy lại một POI lấy nhầm quán chỉ đốt thêm một vòng Gemini."""
    job_id = _add(env, "Greek Cuisine", 1)

    calls = {"n": 0}

    def boom(_record):
        calls["n"] += 1
        raise WrongPlaceError("CÓ THỂ LẤY NHẦM QUÁN: Google trả về Greek Kitchen")

    _handlers(monkeypatch, {"maps": boom})
    tally = worker.run_batch(env["batch_id"], db_path=env["db"])

    assert tally == {"needs_review": 1}
    assert calls["n"] == 1
    job = store.get_job(job_id, db_path=env["db"])
    assert job["status"] == "needs_review"
    assert job["error_code"] == "wrong_place"


def test_transient_failure_is_retried_up_to_max_attempts(env, monkeypatch):
    job_id = _add(env, "Quán A", 1)
    calls = {"n": 0}

    def flaky(_record):
        calls["n"] += 1
        raise TimeoutError("Gemini không trả lời")

    _handlers(monkeypatch, {"menu": flaky})
    worker.run_batch(env["batch_id"], db_path=env["db"])

    # max_attempts=2 -> chạy lần 1 xếp lại hàng đợi, lần 2 chốt là hỏng.
    assert calls["n"] == 2
    assert store.get_job(job_id, db_path=env["db"])["status"] == "failed"


def test_maps_failure_skips_every_later_step(env, monkeypatch):
    """`maps` giữ hai cổng chặn — hỏng là cả chuỗi dừng, không đốt lượt Gemini."""
    _add(env, "Quán A", 1)
    ran: list[str] = []

    def fail(_record):
        raise RuntimeError("Google Maps không mở được")

    handlers = {"maps": fail}
    for step in STEPS[1:]:
        handlers[step] = (lambda s: lambda _r: ran.append(s))(step)
    _handlers(monkeypatch, handlers)

    worker.run_batch(env["batch_id"], db_path=env["db"])
    assert ran == []

    saved = json.loads((env["out"] / "1_quan-a" / "data.json").read_text(encoding="utf-8"))
    assert saved["steps"]["maps"] == "failed"
    assert all(saved["steps"][s] == "skipped" for s in STEPS[1:])


def test_limit_stops_after_n_pois(env, monkeypatch):
    for i in range(1, 4):
        _add(env, f"Quán {i}", i)
    _handlers(monkeypatch, {})

    worker.run_batch(env["batch_id"], limit=2, db_path=env["db"])
    remaining = store.list_jobs(env["batch_id"], status="queued", db_path=env["db"])
    assert len(remaining) == 1


def test_pause_flag_stops_between_pois(env, monkeypatch):
    for i in range(1, 4):
        _add(env, f"Quán {i}", i)

    def pause_after_first(_record):
        store.set_batch_status(env["batch_id"], "paused", db_path=env["db"])

    _handlers(monkeypatch, {"maps": pause_after_first})
    worker.run_batch(env["batch_id"], db_path=env["db"])

    done = store.list_jobs(env["batch_id"], status="done", db_path=env["db"])
    queued = store.list_jobs(env["batch_id"], status="queued", db_path=env["db"])
    assert len(done) == 1 and len(queued) == 2


def test_resume_skips_steps_already_ok(env, monkeypatch):
    """Chạy lại một lô dở dang không được cào lại thứ đã có."""
    record = POIRecord(poi_name="Quán A")
    record.slug = "1_quan-a"
    record.steps = {s: "ok" for s in STEPS}
    record.save(env["out"])
    _add(env, "Quán A", 1)

    ran: list[str] = []
    _handlers(monkeypatch, {s: (lambda s: lambda _r: ran.append(s))(s) for s in STEPS})

    worker.run_batch(env["batch_id"], resume=True, db_path=env["db"])
    assert ran == []


def test_events_are_recorded_for_the_ui(env, monkeypatch):
    _add(env, "Quán A", 1)
    _handlers(monkeypatch, {})

    seen: list[dict] = []
    worker.run_batch(env["batch_id"], db_path=env["db"], on_event=seen.append)

    kinds = {e["kind"] for e in seen}
    assert {"batch_start", "job_start", "step_start", "step_ok", "job_end", "batch_end"} <= kinds
    assert store.list_events(batch_id=env["batch_id"], db_path=env["db"])


def test_overrides_survive_a_rerun(env, monkeypatch):
    """Sửa tay xong chạy lại một bước KHÔNG được xoá chỗ đã sửa."""
    record = POIRecord(poi_name="Quán A")
    record.slug = "1_quan-a"
    record.overrides = {"seating_capacity": "40"}
    record.save(env["out"])
    _add(env, "Quán A", 1)
    _handlers(monkeypatch, {"maps": lambda r: r.google_maps.update(name="Quán A")})

    worker.run_batch(env["batch_id"], db_path=env["db"])

    saved = json.loads((env["out"] / "1_quan-a" / "data.json").read_text(encoding="utf-8"))
    assert saved["overrides"] == {"seating_capacity": "40"}

    import csv

    row = next(csv.DictReader((env["out"] / "1_quan-a" / "row.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert row["seating_capacity"] == "40"


def test_rerunning_a_finished_batch_does_not_crash(env, monkeypatch):
    """Từng ném UnboundLocalError: `path` chỉ được gán bên trong vòng lặp."""
    _add(env, "Quán A", 1)
    _handlers(monkeypatch, {})
    worker.run_batch(env["batch_id"], db_path=env["db"])

    # Mọi bước đã ok -> lượt hai bỏ qua sạch, không bước nào chạy.
    store.reset_jobs(env["batch_id"], only_failed=False, db_path=env["db"])
    assert worker.run_batch(env["batch_id"], resume=True, db_path=env["db"]) == {"done": 1}


def test_only_step_is_a_one_shot_instruction(env, monkeypatch):
    """Chọn "chỉ chạy maps" một lần không được biến job thành vĩnh viễn một bước."""
    job_id = _add(env, "Quán A", 1)
    store.upsert_job(
        env["batch_id"], "Quán A", seq=1, only_step="maps", db_path=env["db"]
    )
    ran: list[str] = []
    _handlers(monkeypatch, {s: (lambda s: lambda _r: ran.append(s))(s) for s in STEPS})

    worker.run_batch(env["batch_id"], db_path=env["db"])
    assert ran == ["maps"]
    assert store.get_job(job_id, db_path=env["db"])["only_step"] is None

    # Lượt sau phải chạy đủ 6 bước.
    ran.clear()
    store.reset_jobs(env["batch_id"], only_failed=False, db_path=env["db"])
    worker.run_batch(env["batch_id"], resume=False, db_path=env["db"])
    assert ran == STEPS
