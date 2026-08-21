"""Hai bộ dataset chạy song song trên cùng một tool.

| Profile | POI | Cột | Bước riêng |
|---|---|---|---|
| `food`  | đồ ăn   | 73 | `menu` — dán ảnh thực đơn vào Gemini #2 |
| `accom` | lưu trú | 72 | `rooms` — Gemini #2 tra bảng giá phòng trên web |

Profile của một POI nằm ở `POIRecord.profile` và được ghi vào data.json, nên
`vsf export` / `vsf batch reindex` đọc lại được mà không cần cờ. Bản ghi cũ
không có khoá này rơi về `food` — đúng với 141 POI đã gán nhãn trước đây.

MỌI thứ phụ thuộc dataset phải đi qua đây. Đừng thêm đường tắt kiểu
`schema.COLUMNS` cấp module: nó sẽ luôn là bộ cột của một profile, và dùng nhầm
cho profile kia thì file TSV lệch cột trong im lặng chứ không báo lỗi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..models import POIRecord
from . import accom as _accom
from . import food as _food

DEFAULT = "food"


@dataclass(frozen=True)
class Profile:
    """Toàn bộ phần phụ thuộc dataset của một bộ POI, gói lại một chỗ."""

    name: str
    #: Thứ tự cột PHẢI khớp tuyệt đối với dataset. Đừng sắp xếp lại.
    COLUMNS: list[str]
    #: Các trường hỏi Gemini #1 trong một lượt (biểu mẫu one-shot).
    PROFILE_FIELDS: list[str]
    #: Trường Gemini trả kiểu danh sách -> tách bằng dấu phẩy khi parse.
    LIST_FIELDS: frozenset[str]
    #: Tên khoá thay thế Gemini hay tự dùng -> tên trường chuẩn.
    FIELD_ALIASES: dict[str, str]
    #: Thứ tự các bước của pipeline.
    STEPS: list[str]
    build_row: Callable[..., dict[str, str]]

    def settings(self) -> dict[str, Any]:
        """settings.toml đã gộp với config/profile_<name>.toml."""
        from ..config import profile_settings

        return profile_settings(self.name)

    @property
    def category_l1(self) -> str:
        """Giá trị cột category_l1 của POI ĐÚNG nhóm ngành ("FOOD" / "ACCOM")."""
        return self.settings()["category"].get("l1_default", "FOOD")


PROFILES: dict[str, Profile] = {
    "food": Profile(
        name="food",
        COLUMNS=_food.COLUMNS,
        PROFILE_FIELDS=_food.PROFILE_FIELDS,
        LIST_FIELDS=_food.LIST_FIELDS,
        FIELD_ALIASES=_food.FIELD_ALIASES,
        STEPS=_food.STEPS,
        build_row=_food.build_row,
    ),
    "accom": Profile(
        name="accom",
        COLUMNS=_accom.COLUMNS,
        PROFILE_FIELDS=_accom.PROFILE_FIELDS,
        LIST_FIELDS=_accom.LIST_FIELDS,
        FIELD_ALIASES=_accom.FIELD_ALIASES,
        STEPS=_accom.STEPS,
        build_row=_accom.build_row,
    ),
}


def get_profile(name: str | None) -> Profile:
    """Tra profile theo tên, báo lỗi rõ ràng thay vì ném KeyError trần."""
    key = (name or DEFAULT).strip().lower()
    try:
        return PROFILES[key]
    except KeyError:
        raise KeyError(
            f"Không có profile {name!r}. Chọn một trong: {', '.join(PROFILES)}."
        ) from None


def profile_for(record: POIRecord) -> Profile:
    """Profile của một bản ghi. Bản ghi cũ không có khoá `profile` -> food."""
    return get_profile(getattr(record, "profile", "") or DEFAULT)


def columns_for(record: POIRecord) -> list[str]:
    return profile_for(record).COLUMNS


def steps_for(record: POIRecord) -> list[str]:
    return profile_for(record).STEPS
