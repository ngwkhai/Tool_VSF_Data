"""Test cho phần sửa tay 73 cột (`POIRecord.overrides`).

Điều kiện để người gán nhãn dám sửa tay trong giao diện: sửa xong chạy lại một
bước KHÔNG được xoá mất chỗ vừa sửa.
"""

from __future__ import annotations

from vsf.models import POIRecord
from vsf.profiles.food import COLUMNS
from vsf.schema import build_row

DEFAULTS = {"status": "active", "labeled_by": "Khải", "confidence_level": "Cao"}


def _record(**kw) -> POIRecord:
    return POIRecord(poi_name=kw.pop("poi_name", "Quán Test"), **kw)


def _row(record: POIRecord) -> dict[str, str]:
    return build_row(record, DEFAULTS, ward_map={})


def test_no_overrides_changes_nothing():
    rec = _record(google_maps={"name": "Quán Ăn A"})
    assert _row(rec)["name"] == "Quán Ăn A"


def test_override_wins_over_derived_value():
    rec = _record(google_maps={"name": "Quán Ăn A"}, overrides={"name": "Quán Ăn A (sửa tay)"})
    assert _row(rec)["name"] == "Quán Ăn A (sửa tay)"


def test_override_can_fill_a_column_the_pipeline_leaves_blank():
    """`seating_capacity` cố ý luôn trống — đây đúng là cột người dùng tự điền."""
    rec = _record(overrides={"seating_capacity": "40"})
    assert _row(rec)["seating_capacity"] == "40"


def test_override_can_clear_a_value():
    rec = _record(google_maps={"phone": "0258 1234"}, overrides={"phone": ""})
    assert _row(rec)["phone"] == ""


def test_unknown_column_never_reaches_the_row():
    """Khoá lạ không được đẻ ra cột thứ 74 làm lệch cả file TSV."""
    rec = _record(overrides={"khong_phai_cot": "x", "name": "Quán B"})
    row = _row(rec)
    assert list(row.keys()) == COLUMNS
    assert "khong_phai_cot" not in row
    assert row["name"] == "Quán B"


def test_override_applies_to_non_food_stub_too():
    rec = _record(category_l1="OTHER", overrides={"reviewer_note": "đã kiểm tra, đúng là spa"})
    row = _row(rec)
    assert row["category_l1"] == "OTHER"
    assert row["reviewer_note"] == "đã kiểm tra, đúng là spa"
    # Vẫn là dòng stub: các cột khác vẫn trống.
    assert row["address"] == ""


def test_overrides_survive_a_rerun_of_one_step():
    """Mô phỏng `--only maps`: google_maps bị ghi đè toàn bộ, override phải còn."""
    rec = _record(google_maps={"name": "Tên Sai"}, overrides={"name": "Tên Đúng"})
    assert _row(rec)["name"] == "Tên Đúng"

    rec.google_maps = {"name": "Tên Sai Lần Hai", "address": "123 Đường X, Lộc Thọ, Khánh Hoà"}
    row = _row(rec)
    assert row["name"] == "Tên Đúng"          # sửa tay còn nguyên
    assert "123 Đường X" in row["address"]     # dữ liệu mới vẫn vào


def test_overrides_round_trip_through_data_json(tmp_path):
    rec = _record(overrides={"seating_capacity": "40"})
    rec.slug = "quan-test"
    rec.save(tmp_path)
    loaded = POIRecord.load_or_new(tmp_path, "Quán Test")
    assert loaded.overrides == {"seating_capacity": "40"}


def test_old_data_json_without_overrides_still_loads(tmp_path):
    """Bản ghi cũ không có khoá `overrides` — `cls(**data)` phải vẫn nạp được."""
    import json

    folder = tmp_path / "quan-cu"
    folder.mkdir()
    (folder / "data.json").write_text(
        json.dumps({"poi_name": "Quán Cũ", "steps": {"maps": "ok"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = POIRecord.load_or_new(tmp_path, "Quán Cũ")
    assert loaded.overrides == {}
    assert loaded.flags == {}
    assert loaded.step_runs == {}


# -- Tick chọn ảnh phụ ở tab "Ảnh" -----------------------------------------
#
# Bể ứng viên là 10 ảnh, cột chỉ nhận 3. Mặc định = 3 ảnh đầu; người gán nhãn
# tick khác đi thì lựa chọn nằm ở `overrides` và phải thắng.

_HERO = "https://lh3.googleusercontent.com/hero=w1080-h1080-p-k-no"
_POOL = [f"https://lh3.googleusercontent.com/g{i}=w1080-h1080-p-k-no" for i in range(10)]


def _record_with_gallery(**kw) -> POIRecord:
    return _record(
        google_maps={
            "photos": {"hero": _HERO},
            "gallery_candidates": {"images": [_HERO, *_POOL]},
        },
        **kw,
    )


def test_gallery_defaults_to_first_three_candidates_after_the_cover():
    """Ảnh đầu mục "Tất cả" CHÍNH LÀ ảnh đại diện -> phải bị bỏ qua, không thì
    raw_gallery_urls mở đầu bằng đúng raw_cover_image_url."""
    row = _row(_record_with_gallery())
    assert row["raw_cover_image_url"] == _HERO
    assert row["raw_gallery_urls"] == ", ".join(_POOL[:3])


def test_ticking_other_photos_overrides_the_default_three():
    picked = [_POOL[7], _POOL[2], _POOL[9]]
    rec = _record_with_gallery(overrides={"raw_gallery_urls": ", ".join(picked)})
    # Giữ nguyên THỨ TỰ tick, không sắp lại theo vị trí trong bể ứng viên.
    assert _row(rec)["raw_gallery_urls"] == ", ".join(picked)


def test_rerunning_maps_keeps_the_ticked_photos():
    """Cào lại bể ứng viên (ảnh mới, thứ tự mới) không được xoá chỗ đã tick."""
    picked = [_POOL[7], _POOL[2]]
    rec = _record_with_gallery(overrides={"raw_gallery_urls": ", ".join(picked)})
    rec.google_maps["gallery_candidates"]["images"] = list(reversed(_POOL))
    assert _row(rec)["raw_gallery_urls"] == ", ".join(picked)
