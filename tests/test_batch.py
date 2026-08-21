"""Test cho tầng chạy lô: hàng đợi, nạp danh sách, suy trạng thái, dựng lại chỉ mục.

Không đụng browser — toàn bộ ở đây là logic thuần và SQLite trong thư mục tạm.
"""

from __future__ import annotations

import json

import pytest

from vsf.batch import ingest, store
from vsf.batch.outcome import derive_status, missing_steps
from vsf.errors import (
    FLAG_NOT_FOOD,
    FLAG_OLD_ADDRESS_GUESSED,
    FLAG_TIKTOK_LOW,
    WrongPlaceError,
    flags_from_warnings,
)
from vsf.models import POIRecord
from vsf.pipeline import STEPS


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    store.init(path)
    return path


def _record(steps: dict[str, str], **kw) -> POIRecord:
    rec = POIRecord(poi_name=kw.pop("poi_name", "Quán Test"), steps=steps, **kw)
    return rec


# -- Nạp danh sách ----------------------------------------------------------


def test_parse_text_one_name_per_line():
    pois = ingest.parse("Bánh Canh Cô Tâm\n\n  Cà Phê Nhiên  \n# ghi chú\nQuán Ốc")
    assert [p.name for p in pois] == ["Bánh Canh Cô Tâm", "Cà Phê Nhiên", "Quán Ốc"]
    # seq đánh liên tục theo POI thật, KHÔNG theo số dòng — dòng trống và dòng
    # chú thích không được để lại lỗ hổng trong dãy số thư mục.
    assert [p.seq for p in pois] == [1, 2, 3]


def test_parse_csv_with_address_and_flags():
    text = "name,address,force_food\nGreek Cuisine,15 Tô Hiến Thành,1\nQuán B,,0\n"
    pois = ingest.parse(text)
    assert pois[0].name == "Greek Cuisine"
    assert pois[0].address == "15 Tô Hiến Thành"
    assert pois[0].force_food is True
    assert pois[1].force_food is False


def test_parse_csv_honours_explicit_index():
    pois = ingest.parse("name,index\nQuán A,7\nQuán B,9\n")
    assert [p.seq for p in pois] == [7, 9]


def test_name_with_comma_is_not_mistaken_for_csv():
    """Tên quán chứa dấu phẩy không được biến danh sách text thành CSV."""
    pois = ingest.parse("Bún Chả Cá, chi nhánh 2\nQuán Ốc")
    assert [p.name for p in pois] == ["Bún Chả Cá, chi nhánh 2", "Quán Ốc"]


def test_duplicate_names_collapse():
    """Khoá tự nhiên là (batch, poi_name) -> bản trùng phải bị bỏ ngay khi nạp."""
    pois = ingest.parse("Quán A\nQuán B\nquán a\n")
    assert [p.name for p in pois] == ["Quán A", "Quán B"]


# -- Hàng đợi ---------------------------------------------------------------


def test_upsert_is_idempotent(db):
    bid = store.get_or_create_batch("output_test", "Đợt test", db_path=db)
    for _ in range(3):
        store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    assert len(store.list_jobs(bid, db_path=db)) == 1


def test_get_or_create_batch_reuses_same_out_dir(db):
    a = store.get_or_create_batch("output_x", "A", db_path=db)
    b = store.get_or_create_batch("output_x", "B", db_path=db)
    assert a == b


def test_claim_next_marks_running_and_counts_attempts(db):
    bid = store.get_or_create_batch("output_test", db_path=db)
    store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    job = store.claim_next(bid, db_path=db)
    assert job["status"] == "running" and job["attempts"] == 1
    # Job đang chạy không được claim lần hai -> tránh hai worker giẫm lên nhau.
    assert store.claim_next(bid, db_path=db) is None


def test_claim_next_follows_seq_order(db):
    bid = store.get_or_create_batch("output_test", db_path=db)
    for seq, name in [(10, "Quán J"), (2, "Quán B"), (1, "Quán A")]:
        store.upsert_job(bid, name, seq=seq, db_path=db)
    assert store.claim_next(bid, db_path=db)["poi_name"] == "Quán A"
    assert store.claim_next(bid, db_path=db)["poi_name"] == "Quán B"
    assert store.claim_next(bid, db_path=db)["poi_name"] == "Quán J"


def test_finish_job_persists_flags_and_steps(db):
    bid = store.get_or_create_batch("output_test", db_path=db)
    jid = store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    store.finish_job(
        jid,
        status="done",
        slug="1_quan-a",
        flags=[FLAG_TIKTOK_LOW],
        steps={"maps": "ok"},
        db_path=db,
    )
    job = store.get_job(jid, db_path=db)
    assert job["flags"] == [FLAG_TIKTOK_LOW]
    assert job["steps"] == {"maps": "ok"}


def test_list_jobs_filters_by_flag(db):
    bid = store.get_or_create_batch("output_test", db_path=db)
    a = store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    b = store.upsert_job(bid, "Quán B", seq=2, db_path=db)
    store.finish_job(a, status="done", flags=[FLAG_TIKTOK_LOW], db_path=db)
    store.finish_job(b, status="done", flags=[FLAG_OLD_ADDRESS_GUESSED], db_path=db)
    found = store.list_jobs(bid, flag=FLAG_TIKTOK_LOW, db_path=db)
    assert [j["poi_name"] for j in found] == ["Quán A"]


def test_reset_jobs_leaves_needs_review_alone(db):
    """Chạy lại một POI bị chặn vì lấy nhầm quán chỉ tốn thêm một vòng Gemini."""
    bid = store.get_or_create_batch("output_test", db_path=db)
    a = store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    b = store.upsert_job(bid, "Quán B", seq=2, db_path=db)
    store.finish_job(a, status="failed", db_path=db)
    store.finish_job(b, status="needs_review", db_path=db)
    assert store.reset_jobs(bid, db_path=db) == 1
    assert store.get_job(b, db_path=db)["status"] == "needs_review"


def test_invalid_status_is_rejected(db):
    bid = store.get_or_create_batch("output_test", db_path=db)
    jid = store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    with pytest.raises(ValueError):
        store.finish_job(jid, status="xong_roi", db_path=db)


# -- Suy trạng thái ---------------------------------------------------------


def test_all_ok_is_done():
    rec = _record({s: "ok" for s in STEPS})
    assert derive_status(rec)[0] == "done"


def test_skipped_counts_as_settled():
    rec = _record({"maps": "ok", **{s: "skipped" for s in STEPS if s != "maps"}})
    assert derive_status(rec)[0] == "done"


def test_failed_step_is_failed_and_carries_error_code():
    rec = _record({"maps": "failed"})
    rec.step_runs = {"maps": {"error_code": "wrong_place", "error_message": "sai quán"}}
    status, code, message = derive_status(rec)
    assert (status, code, message) == ("failed", "wrong_place", "sai quán")


def test_terminal_flag_outranks_failed_step():
    """`not_food` phải cho ra needs_review, không phải failed — chạy lại vô ích."""
    rec = _record({"maps": "ok", "gemini1": "failed"})
    rec.flags = {"maps": [FLAG_NOT_FOOD]}
    assert derive_status(rec)[0] == "needs_review"


def test_empty_record_is_queued():
    assert derive_status(_record({}))[0] == "queued"


def test_missing_new_step_does_not_requeue_finished_work():
    """139 bản ghi cũ không có bước `facebook` — không được đẩy hết về hàng đợi."""
    old_steps = {s: "ok" for s in STEPS if s != "facebook"}
    rec = _record(old_steps)
    assert derive_status(rec)[0] == "done"
    assert missing_steps(rec) == ["facebook"]


# -- Bắc cầu cờ từ warning cũ ------------------------------------------------


def test_flags_from_warnings_recognises_historical_messages():
    warnings = {
        "old_address": ["old_address dùng phường 'Vĩnh Hiệp' do Gemini suy đoán — nên kiểm tra"],
        "menu": ["Bỏ qua bước thực đơn: không có ảnh thực đơn nào từ Google Maps"],
        "tiktok": ["TikTok: ứng viên tốt nhất chỉ đạt 0.3 < 0.5 — raw_url sẽ để trống"],
    }
    flags = flags_from_warnings(warnings)
    assert flags["old_address"] == [FLAG_OLD_ADDRESS_GUESSED]
    assert flags["menu"] == ["no_menu_photos"]
    assert flags["tiktok"] == [FLAG_TIKTOK_LOW]


def test_flags_from_warnings_ignores_unrelated_text():
    assert flags_from_warnings({"maps": ["Google Maps: chỉ tìm được 2/5 bài tiêu cực"]}) == {}


# -- Dựng lại chỉ mục -------------------------------------------------------


def _write_poi(out_dir, folder, **fields):
    d = out_dir / folder
    d.mkdir(parents=True)
    payload = {"poi_name": fields.pop("poi_name", folder), "steps": {}, **fields}
    (d / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return d


def test_reindex_is_idempotent_and_reads_seq_from_folder(tmp_path, db, monkeypatch):
    from vsf.batch import reindex

    out = tmp_path / "output_test"
    _write_poi(out, "1_quan-a", poi_name="Quán A", steps={s: "ok" for s in STEPS})
    _write_poi(out, "2_quan-b", poi_name="Quán B", steps={"maps": "failed"})

    for _ in range(2):
        result = reindex.reindex_dir(out, db_path=db)
    assert result["total"] == 2

    jobs = store.list_jobs(result["batch_id"], db_path=db)
    assert len(jobs) == 2
    assert [j["seq"] for j in jobs] == [1, 2]
    assert {j["poi_name"]: j["status"] for j in jobs} == {"Quán A": "done", "Quán B": "failed"}


def test_reindex_backfills_flags_from_old_warnings(tmp_path, db):
    from vsf.batch import reindex

    out = tmp_path / "output_test"
    _write_poi(
        out,
        "1_quan-a",
        poi_name="Quán A",
        steps={s: "ok" for s in STEPS},
        warnings={"old_address": ["old_address dùng phường 'X' do Gemini suy đoán"]},
    )
    result = reindex.reindex_dir(out, db_path=db)
    job = store.list_jobs(result["batch_id"], db_path=db)[0]
    assert FLAG_OLD_ADDRESS_GUESSED in job["flags"]


def test_reindex_survives_corrupt_data_json(tmp_path, db):
    """Một file hỏng không được làm gãy cả lượt nạp lại."""
    from vsf.batch import reindex

    out = tmp_path / "output_test"
    _write_poi(out, "1_quan-a", poi_name="Quán A", steps={s: "ok" for s in STEPS})
    bad = out / "2_hong"
    bad.mkdir()
    (bad / "data.json").write_text("{ khong phai json", encoding="utf-8")

    result = reindex.reindex_dir(out, db_path=db)
    assert result["total"] == 1


def test_reindex_tolerates_unknown_keys_from_future_versions(tmp_path, db):
    from vsf.batch import reindex

    out = tmp_path / "output_test"
    _write_poi(
        out, "1_quan-a", poi_name="Quán A", steps={s: "ok" for s in STEPS}, khoa_la="gì đó"
    )
    assert reindex.reindex_dir(out, db_path=db)["total"] == 1


# -- Lỗi có mã --------------------------------------------------------------


def test_wrong_place_error_is_still_a_runtime_error():
    """Code cũ (và test cũ) bắt RuntimeError — không được phá hợp đồng đó."""
    exc = WrongPlaceError("CÓ THỂ LẤY NHẦM QUÁN", name_match=0.5)
    assert isinstance(exc, RuntimeError)
    assert exc.code == "wrong_place"
    assert exc.name_match == 0.5


# -- Bảng dán không có tiêu đề: tên · địa chỉ · place_id ----------------------

# Đúng dạng người dùng dán ra từ bảng tính / kết quả Google Places.
PASTED = [
    ("Bún Bò Thành Danh", "124 Trần Phú, Nha Trang, Khánh Hòa 650000, Việt Nam",
     "ChIJzWzaPZ1ncDER5ZVqZtJM6qY"),
    ("Bún bò Tùng Hoàng", "5 Khúc Thừa Dụ, Nam Nha Trang, Khánh Hòa, Việt Nam",
     "ChIJsdCtSwBncDER87JExvFJnBc"),
    ("Bún bò Tùng Hoàng - chi nhánh 2", "335 Võ Thị Sáu, Nam Nha Trang, Khánh Hòa 65000, Việt Nam",
     "ChIJU7gjfCRhcDERg0r3wHORF3g"),
]


@pytest.mark.parametrize("sep", ["\t", "    "])
def test_parse_headerless_table(sep):
    """Tab là dạng gốc; dán qua trình soạn thảo trơn thì tab thành nhiều dấu cách."""
    pois = ingest.parse("\n".join(sep.join(r) for r in PASTED))
    assert [p.name for p in pois] == [r[0] for r in PASTED]
    assert [p.place_id for p in pois] == [r[2] for r in PASTED]
    assert pois[0].address.startswith("124 Trần Phú")


def test_same_name_branches_stay_separate():
    """"Tùng Hoàng" và "Tùng Hoàng - chi nhánh 2" là hai quán, không được gộp."""
    pois = ingest.parse("\n".join("\t".join(r) for r in PASTED))
    assert len({p.place_id for p in pois}) == 3
    assert len({p.name for p in pois}) == 3


def test_place_id_is_peeled_by_shape_not_by_column_count():
    """Địa chỉ chứa dấu phẩy -> số ô thay đổi; place_id vẫn phải nhận ra được."""
    name, address, place_id = ingest.split_row(
        "Quán A\tsố 1, ngõ 2, phường 3, Nha Trang\tChIJzWzaPZ1ncDER5ZVqZtJM6qY"
    )
    assert (name, place_id) == ("Quán A", "ChIJzWzaPZ1ncDER5ZVqZtJM6qY")
    assert address == "số 1, ngõ 2, phường 3, Nha Trang"


def test_a_name_without_place_id_still_parses():
    assert ingest.split_row("Quán A\t12 Trần Phú, Nha Trang") == (
        "Quán A", "12 Trần Phú, Nha Trang", "",
    )


def test_uppercase_run_on_name_is_not_mistaken_for_a_place_id():
    """"BUNBOTUNGHOANGCHINHANH2" dài và không dấu cách — nhưng không phải place_id."""
    assert not ingest.looks_like_place_id("BUNBOTUNGHOANGCHINHANH2")
    assert not ingest.looks_like_place_id("khongdaukhongcachdaihonhaimuoiky")
    assert ingest.looks_like_place_id("ChIJzWzaPZ1ncDER5ZVqZtJM6qY")


def test_single_spaces_do_not_split_a_plain_name():
    """Tên quán đầy dấu cách đơn — không được cắt nhầm thành tên + địa chỉ."""
    assert ingest.split_row("Bún Bò Hai Chị Em Bún Cá Mực Hải sản") == (
        "Bún Bò Hai Chị Em Bún Cá Mực Hải sản", "", "",
    )


def test_seq_is_renumbered_after_dropping_duplicates():
    """Bỏ bản trùng ở giữa không được để thủng số thứ tự thư mục."""
    pois = ingest.parse("Quán A\nQuán B\nquán a\nQuán C")
    assert [p.seq for p in pois] == [1, 2, 3]


def test_explicit_index_column_is_preserved():
    pois = ingest.parse("name,index\nQuán A,7\nQuán B,9\n")
    assert [p.seq for p in pois] == [7, 9]


def test_csv_header_can_carry_place_id():
    pois = ingest.parse("name,address,place_id\nQuán A,12 Trần Phú,ChIJzWzaPZ1ncDER5ZVqZtJM6qY\n")
    assert pois[0].place_id == "ChIJzWzaPZ1ncDER5ZVqZtJM6qY"


# -- place_id không bị mất ---------------------------------------------------


def test_reindex_does_not_wipe_a_place_id_it_knows_nothing_about(tmp_path, db):
    """Chạy `vsf batch reindex` không được xoá place_id vừa nạp."""
    from vsf.batch import reindex

    out = tmp_path / "output_test"
    bid = store.get_or_create_batch(str(out), db_path=db)
    store.upsert_job(bid, "Quán A", seq=1, place_id="ChIJzWzaPZ1ncDER5ZVqZtJM6qY", db_path=db)

    _write_poi(out, "1_quan-a", poi_name="Quán A", steps={s: "ok" for s in STEPS})
    reindex.reindex_dir(out, db_path=db)

    assert store.list_jobs(bid, db_path=db)[0]["place_id"] == "ChIJzWzaPZ1ncDER5ZVqZtJM6qY"


def test_reloading_the_same_list_keeps_the_place_id(db):
    """Nạp lại danh sách chỉ có tên (không place_id) không được xoá place_id cũ."""
    bid = store.get_or_create_batch("output_test", db_path=db)
    store.upsert_job(bid, "Quán A", seq=1, place_id="ChIJzWzaPZ1ncDER5ZVqZtJM6qY", db_path=db)
    store.upsert_job(bid, "Quán A", seq=1, db_path=db)
    assert store.list_jobs(bid, db_path=db)[0]["place_id"] == "ChIJzWzaPZ1ncDER5ZVqZtJM6qY"


def test_place_id_url_points_at_one_exact_place():
    from vsf.sites.gmaps import place_id_url

    url = place_id_url("ChIJzWzaPZ1ncDER5ZVqZtJM6qY")
    assert "place_id:ChIJzWzaPZ1ncDER5ZVqZtJM6qY" in url
    assert "/maps/place/" in url


def test_place_id_navigation_disables_the_wrong_place_gate():
    """Tên người dùng gõ khác tên Google đăng ký là chuyện thường — và khi đã mở
    thẳng bằng place_id thì danh tính chắc chắn, chặn ở đây là loại oan."""
    from vsf.pipeline import _reject_wrong_place

    data = {
        "name": "Bún Cá Sứa Nha Trang 9 Tăng Bạt Hổ",
        "address": "9 Tăng Bạt Hổ",
        "name_match": 0.2,
        "address_match": 0.0,
        "opened_by_place_id": "ChIJC1dTkBFncDERcf6YMZ2KbZk",
    }
    record = POIRecord(poi_name="Bún Cá Sứa NhaTrang")
    record.begin_step("maps")
    _reject_wrong_place(data, "Bún Cá Sứa NhaTrang", record)   # không được ném

    # Không chặn, nhưng cũng không im lặng.
    assert any("place_id" in w for w in record.warnings.get("maps", []))


def test_without_place_id_the_gate_still_blocks():
    from vsf.pipeline import _reject_wrong_place

    data = {"name": "Greek Kitchen", "address": "Phố khác", "name_match": 0.5}
    with pytest.raises(WrongPlaceError):
        _reject_wrong_place(data, "Greek Cuisine", POIRecord(poi_name="Greek Cuisine"))


# -- Hai profile sống chung -------------------------------------------------


def test_reindex_round_trips_the_profile_from_disk(tmp_path, db):
    """`profile` nằm trong data.json nên reindex biết chắc, không phải đoán."""
    from vsf.batch import reindex
    from vsf.profiles import get_profile

    out = tmp_path / "output_accom"
    _write_poi(
        out, "1_lucky-sun",
        poi_name="Lucky Sun Hotel", profile="accom",
        steps={s: "ok" for s in get_profile("accom").STEPS},
    )
    result = reindex.reindex_dir(out, db_path=db)
    assert store.list_jobs(result["batch_id"], db_path=db)[0]["profile"] == "accom"


def test_reindex_stamps_the_profile_onto_the_batch_too(tmp_path, db):
    """Không có bước này thì mọi lô dựng lại bằng reindex đều mang nhãn 'food',
    và trang thống kê đếm ô trống theo bộ cột SAI."""
    from vsf.batch import reindex
    from vsf.profiles import get_profile

    out = tmp_path / "output_accom"
    _write_poi(
        out, "1_lucky-sun",
        poi_name="Lucky Sun Hotel", profile="accom",
        steps={s: "ok" for s in get_profile("accom").STEPS},
    )
    res = reindex.reindex_dir(out, db_path=db)
    assert store.get_batch(res["batch_id"], db_path=db)["profile"] == "accom"


def test_reindex_leaves_the_profile_alone_for_an_empty_directory(tmp_path, db):
    """Thư mục rỗng không có căn cứ nào để chốt — đừng đoán bừa về 'food'."""
    from vsf.batch import reindex

    out = tmp_path / "output_accom"
    out.mkdir(parents=True)
    bid = store.get_or_create_batch(str(out), db_path=db, profile="accom")
    reindex.reindex_dir(out, db_path=db)
    assert store.get_batch(bid, db_path=db)["profile"] == "accom"


def test_reindex_never_downgrades_an_accom_job_to_food(tmp_path, db):
    """Cùng bài học với place_id: rỗng không được ghi đè giá trị đã có.

    Không có chốt `_STICKY` thì một lần upsert thiếu `profile` là cả đợt lưu trú
    âm thầm quay về bộ 73 cột của đồ ăn — chỉ lộ ra ở lần export sau.
    """
    bid = store.get_or_create_batch("output_accom", db_path=db, profile="accom")
    store.upsert_job(bid, "Khách sạn A", seq=1, profile="accom", db_path=db)
    store.upsert_job(bid, "Khách sạn A", seq=1, db_path=db)  # không truyền profile
    assert store.list_jobs(bid, db_path=db)[0]["profile"] == "accom"


def test_adding_to_an_existing_batch_does_not_change_its_profile(db):
    """`batch add` lần hai là thêm POI, không phải đổi bộ cột của đợt đang dở."""
    first = store.get_or_create_batch("output_accom", db_path=db, profile="accom")
    again = store.get_or_create_batch("output_accom", db_path=db, profile="food")
    assert again == first
    assert store.get_batch(first, db_path=db)["profile"] == "accom"


def test_missing_steps_uses_the_profile_step_list(tmp_path):
    """POI lưu trú không có bước `menu` và không bao giờ bị báo là thiếu nó."""
    from vsf.batch.outcome import missing_steps
    from vsf.models import POIRecord

    record = POIRecord(poi_name="Khách sạn A", profile="accom")
    record.steps = {"maps": "ok", "gemini1": "ok"}
    assert "menu" not in missing_steps(record)
    assert "rooms" in missing_steps(record)


def test_a_failed_step_outside_the_profile_list_still_shows_as_failed(tmp_path):
    """Bước hỏng không được biến mất thành `done` chỉ vì đổi profile."""
    from vsf.batch.outcome import derive_status
    from vsf.models import POIRecord

    record = POIRecord(poi_name="X", profile="accom")
    record.steps = {"maps": "ok", "menu": "failed"}
    assert derive_status(record)[0] == "failed"


def test_export_refuses_a_directory_mixing_two_profiles(tmp_path):
    """Hai bộ cột khác nhau không gộp chung một file TSV được."""
    import csv as _csv

    from vsf.batch import export as batch_export
    from vsf.profiles import get_profile

    out = tmp_path / "output_mixed"
    for folder, profile in (("1_quan-a", "food"), ("2_khach-san-b", "accom")):
        d = _write_poi(out, folder, poi_name=folder, profile=profile)
        with (d / "row.tsv").open("w", encoding="utf-8", newline="") as fh:
            cols = get_profile(profile).COLUMNS
            w = _csv.DictWriter(fh, fieldnames=cols, delimiter="\t")
            w.writeheader()
            w.writerow({c: "" for c in cols})

    with pytest.raises(ValueError, match="trộn nhiều profile"):
        batch_export.merge(out)


def test_ui_finds_a_record_saved_without_an_index(tmp_path):
    """`vsf run` không --index ghi ra `<slug>/`, reindex gán seq=1 -> phải khớp.

    Không có nhánh lùi trong `folder_for`, `load_or_new` lặng lẽ trả bản ghi
    RỖNG và mọi cột lấy từ Google (lat/long/place_id...) trống trơn trên giao
    diện dù data.json trên đĩa đầy đủ.
    """
    from vsf.models import POIRecord

    out = tmp_path / "output_x"
    _write_poi(out, "quan-a", poi_name="Quán A", google_maps={"lat": 12.34, "place_id": "ChIJx"})

    rec = POIRecord.load_or_new(out, "Quán A", index=1)
    assert rec.google_maps.get("place_id") == "ChIJx"
    assert rec.slug == "quan-a"


def test_numbered_folder_still_wins_when_it_exists(tmp_path):
    """Có đúng thư mục đánh số thì dùng nó, không lùi về bản không số."""
    from vsf.models import POIRecord

    out = tmp_path / "output_x"
    _write_poi(out, "quan-a", poi_name="Quán A", google_maps={"place_id": "khong-so"})
    _write_poi(out, "1_quan-a", poi_name="Quán A", google_maps={"place_id": "co-so"})

    assert POIRecord.load_or_new(out, "Quán A", index=1).google_maps["place_id"] == "co-so"


def test_new_poi_with_an_index_still_gets_a_numbered_folder(tmp_path):
    """POI chưa từng chạy vẫn phải ra `<index>_<slug>`, không mất cách đánh số."""
    from vsf.models import POIRecord

    out = tmp_path / "output_x"
    out.mkdir(parents=True)
    assert POIRecord.folder_for(out, "Quán Mới", 3).name == "3_quan-moi"
