"""Test cho tầng API.

Tự bỏ qua nếu chưa cài nhóm `[ui]` — core CLI phải test được mà không cần FastAPI.
Không chạm browser: chỉ đọc/ghi trên thư mục output tạm.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="cần `pip install -e '.[ui]'`")
try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:  # starlette báo thiếu httpx bằng RuntimeError, không phải ImportError
    pytest.skip(f"TestClient không dùng được: {exc}", allow_module_level=True)

from vsf.batch import reindex, store  # noqa: E402
from vsf.profiles.food import COLUMNS, STEPS  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Máy chủ trỏ vào một gốc dự án tạm, không đụng dữ liệu thật."""
    out = tmp_path / "output_test"
    folder = out / "1_quan-a"
    folder.mkdir(parents=True)
    (folder / "data.json").write_text(
        json.dumps(
            {
                "poi_name": "Quán A",
                "steps": {s: "ok" for s in STEPS},
                "google_maps": {"name": "Quán A", "address": "1 Đường X, Lộc Thọ, Khánh Hoà"},
                "warnings": {"old_address": ["old_address dùng phường 'X' do Gemini suy đoán"]},
                "tiktok": [
                    {"url": "https://tiktok.com/@a/video/1", "score": 0.9, "posted_at": "2026-01-02"},
                    {"url": "https://tiktok.com/@b/video/2", "score": 0.4},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = tmp_path / "vsf.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setattr("vsf.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("vsf.batch.reindex.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("vsf.server.api.PROJECT_ROOT", tmp_path)

    reindex.reindex_dir(out)

    from vsf.server.app import create_app

    return TestClient(create_app())


def _first_job(client) -> dict:
    batches = client.get("/api/batches").json()["batches"]
    return client.get(f"/api/batches/{batches[0]['id']}/jobs").json()["jobs"][0]


def test_batches_and_jobs_are_listed(client):
    batches = client.get("/api/batches").json()["batches"]
    assert len(batches) == 1 and batches[0]["total"] == 1
    assert _first_job(client)["poi_name"] == "Quán A"


def test_job_detail_returns_all_73_columns(client):
    job = _first_job(client)
    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["columns"] == COLUMNS
    assert len(detail["row"]) == 73
    assert detail["record"]["poi_name"] == "Quán A"


def test_job_detail_backfills_flags_like_the_index_does(client):
    """Bảng job và trang chi tiết phải kể cùng một câu chuyện về cùng một POI."""
    job = _first_job(client)
    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert "old_address_guessed" in detail["record"]["flags"]
    assert detail["record"]["flags"] == job["flags"]


def test_missing_step_is_reported_not_treated_as_unfinished(client, tmp_path):
    """Bản ghi thiếu bước mới vẫn là `done`, và bước thiếu được nêu tên."""
    folder = tmp_path / "output_test" / "2_quan-b"
    folder.mkdir(parents=True)
    (folder / "data.json").write_text(
        json.dumps(
            {"poi_name": "Quán B", "steps": {s: "ok" for s in STEPS if s != "facebook"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client.post("/api/reindex")
    job = next(
        j for j in client.get("/api/jobs").json()["jobs"] if j["poi_name"] == "Quán B"
    )
    assert job["status"] == "done"
    assert client.get(f"/api/jobs/{job['id']}").json()["record"]["missing_steps"] == ["facebook"]


def test_patch_row_persists_override_and_rewrites_tsv(client, tmp_path):
    job = _first_job(client)
    res = client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"seating_capacity": "40"}})
    assert res.status_code == 200

    saved = json.loads((tmp_path / "output_test/1_quan-a/data.json").read_text(encoding="utf-8"))
    assert saved["overrides"] == {"seating_capacity": "40"}

    tsv = (tmp_path / "output_test/1_quan-a/row.tsv").read_text(encoding="utf-8")
    assert "40" in tsv.splitlines()[1].split("\t")

    assert client.get(f"/api/jobs/{job['id']}").json()["row"]["seating_capacity"] == "40"


def test_patch_row_with_null_drops_the_override_instead_of_blanking_it(client, tmp_path):
    """`null` = bỏ sửa tay, `""` = ép cột rỗng. Nút "về mặc định" của tab Ảnh dựa
    vào phân biệt này: gộp hai thứ lại thì bỏ tick sẽ khoá cột ở giá trị trống."""
    job = _first_job(client)
    picked = "https://lh3.googleusercontent.com/x=w1080-h1080-p-k-no"
    client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"raw_gallery_urls": picked}})
    assert client.get(f"/api/jobs/{job['id']}").json()["row"]["raw_gallery_urls"] == picked

    res = client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"raw_gallery_urls": None}})
    assert res.status_code == 200
    assert res.json()["overrides"] == {}
    saved = json.loads((tmp_path / "output_test/1_quan-a/data.json").read_text(encoding="utf-8"))
    assert saved["overrides"] == {}


def test_patch_row_with_empty_string_still_forces_a_blank_column(client):
    job = _first_job(client)
    client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"name": ""}})
    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["record"]["overrides"] == {"name": ""}
    assert detail["row"]["name"] == ""


def test_patch_row_rejects_columns_outside_the_schema(client):
    job = _first_job(client)
    res = client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"khong_co_cot": "x"}})
    assert res.status_code == 400


def test_clear_overrides_restores_derived_values(client):
    job = _first_job(client)
    client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {"seating_capacity": "40"}})
    client.delete(f"/api/jobs/{job['id']}/row")
    assert client.get(f"/api/jobs/{job['id']}").json()["row"]["seating_capacity"] == ""


def test_pick_tiktok_writes_chosen_url_without_reordering_candidates(client):
    job = _first_job(client)
    res = client.post(f"/api/jobs/{job['id']}/tiktok", json={"index": 1})
    assert res.status_code == 200

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["row"]["raw_url"] == "https://tiktok.com/@b/video/2"
    # Điểm số và thứ tự ứng viên phải giữ nguyên để sau còn biết vì sao máy chọn khác.
    assert [c["url"] for c in detail["record"]["tiktok"]] == [
        "https://tiktok.com/@a/video/1",
        "https://tiktok.com/@b/video/2",
    ]


def test_pick_tiktok_rejects_out_of_range_index(client):
    job = _first_job(client)
    assert client.post(f"/api/jobs/{job['id']}/tiktok", json={"index": 9}).status_code == 400


def test_rerun_requeues_the_job(client):
    job = _first_job(client)
    assert client.post(f"/api/jobs/{job['id']}/rerun", json={"only": "maps"}).status_code == 200
    refreshed = _first_job(client)
    assert refreshed["status"] == "queued"
    assert refreshed["only_step"] == "maps"


def test_rerun_rejects_an_unknown_step(client):
    job = _first_job(client)
    res = client.post(f"/api/jobs/{job['id']}/rerun", json={"only": "khong_co_buoc"})
    assert res.status_code == 400


def test_stats_reports_per_step_and_flags(client):
    stats = client.get("/api/stats").json()
    assert stats["total"] == 1
    # /stats gom mọi bước của MỌI profile (có cả `rooms` của lưu trú) — một
    # bảng thống kê theo bước chỉ hữu ích khi nó phủ hết bước đang tồn tại.
    assert set(stats["steps"]) >= set(STEPS)
    assert "rooms" in stats["steps"]
    assert any(f["code"] == "old_address_guessed" for f in stats["flags"])
    # Chỉ profile đang có lô mới được liệt kê; lô mẫu ở đây là food.
    assert {c["profile"] for c in stats["blank_by_column"]} == {"food"}
    assert len(stats["blank_by_column"]) == len(COLUMNS)


def test_creating_a_batch_from_pasted_text(client):
    res = client.post(
        "/api/batches",
        json={"out_dir": "output_moi", "name": "Đợt mới", "text": "Quán X\nQuán Y\n# bỏ qua"},
    )
    assert res.status_code == 200 and res.json()["added"] == 2


def test_creating_a_batch_from_an_empty_list_is_rejected(client):
    res = client.post("/api/batches", json={"out_dir": "output_moi", "name": "", "text": "   "})
    assert res.status_code == 400


def test_export_returns_a_73_column_tsv(client):
    job = _first_job(client)
    client.patch(f"/api/jobs/{job['id']}/row", json={"overrides": {}})  # để sinh row.tsv
    res = client.get(f"/api/export/{job['batch_id']}.tsv")
    assert res.status_code == 200
    assert res.text.splitlines()[0].split("\t") == COLUMNS


def test_unknown_ids_return_404(client):
    assert client.get("/api/jobs/9999").status_code == 404
    assert client.post("/api/batches/9999/start").status_code == 404


def test_deleting_a_batch_removes_it_from_the_index_only(client, tmp_path):
    """Bỏ đợt khỏi chỉ mục KHÔNG được đụng tới file trên đĩa."""
    batch = client.get("/api/batches").json()["batches"][0]
    data_json = tmp_path / "output_test/1_quan-a/data.json"
    assert data_json.is_file()

    res = client.delete(f"/api/batches/{batch['id']}")
    assert res.status_code == 200 and res.json()["removed_jobs"] == 1
    assert client.get("/api/batches").json()["batches"] == []

    # Đĩa còn nguyên -> nạp lại chỉ mục là đợt quay về đầy đủ.
    assert data_json.is_file()
    client.post("/api/reindex")
    assert len(client.get("/api/jobs").json()["jobs"]) == 1


def test_deleting_an_unknown_batch_is_404(client):
    assert client.delete("/api/batches/9999").status_code == 404


def test_pasted_table_is_parsed_into_name_address_place_id(client):
    """Đúng dạng người dùng dán: 3 cột ngăn bởi Tab, không có dòng tiêu đề."""
    text = (
        "Bún Bò Thành Danh\t124 Trần Phú, Nha Trang\tChIJzWzaPZ1ncDER5ZVqZtJM6qY\n"
        "Bún bò Tùng Hoàng\t5 Khúc Thừa Dụ, Nha Trang\tChIJsdCtSwBncDER87JExvFJnBc\n"
    )
    res = client.post("/api/batches", json={"out_dir": "output_dan", "name": "", "text": text})
    assert res.json() | {"batch_id": 0} == {
        "batch_id": 0, "added": 2, "with_place_id": 2, "with_address": 2,
        "profile": "food",
    }

    jobs = client.get(f"/api/batches/{res.json()['batch_id']}/jobs").json()["jobs"]
    assert jobs[0]["poi_name"] == "Bún Bò Thành Danh"
    assert jobs[0]["place_id"] == "ChIJzWzaPZ1ncDER5ZVqZtJM6qY"
    assert jobs[0]["address_hint"] == "124 Trần Phú, Nha Trang"
