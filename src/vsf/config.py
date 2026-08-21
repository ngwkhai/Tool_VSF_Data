"""Nạp config/settings.toml, config/profile_*.toml và config/selectors.toml."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Thiếu file config: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    return _load("settings.toml")


@lru_cache(maxsize=8)
def profile_settings(name: str) -> dict[str, Any]:
    """settings.toml gộp với config/profile_<name>.toml — file profile THẮNG.

    Gộp NÔNG, theo từng section: `[gemini]` của profile chỉ ghi đè những khoá nó
    khai (các prompt), còn `profile_chat_url`/`response_timeout` ở settings.toml
    vẫn giữ nguyên. Gộp sâu hơn sẽ khiến `[category].markers` của hai profile
    trộn vào nhau — mà một bên là danh sách trắng, một bên là danh sách đen, hợp
    nhất lại thì cổng chặn vô nghĩa.

    Section chỉ có ở profile (`[dataset]`, `[category]`) được thêm nguyên khối.
    """
    merged: dict[str, Any] = {}
    for section, value in settings().items():
        merged[section] = dict(value) if isinstance(value, dict) else value
    for section, value in _load(f"profile_{name}.toml").items():
        if isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section] = {**merged[section], **value}
        else:
            merged[section] = value
    return merged


@lru_cache(maxsize=1)
def selectors() -> dict[str, Any]:
    """Toàn bộ CSS selector của 3 site.

    Khi Google/TikTok đổi giao diện, đây là file duy nhất cần vá.
    Dùng `/poi-recon <site>` để dò lại selector mới.
    """
    return _load("selectors.toml")


def sel(site: str, key: str) -> str | list[str]:
    """Lấy selector, báo lỗi rõ ràng nếu thiếu thay vì ném KeyError trần."""
    try:
        return selectors()[site][key]
    except KeyError:
        raise KeyError(
            f"Thiếu selector [{site}].{key} trong config/selectors.toml. "
            f"Chạy /poi-recon {site} để dò lại."
        ) from None


def sel_list(site: str, key: str) -> list[str]:
    """Selector dạng danh sách ứng viên — thử lần lượt tới khi khớp.

    Cho phép giữ nhiều biến thể selector, UI đổi một cái vẫn còn cái khác.
    """
    value = sel(site, key)
    return value if isinstance(value, list) else [value]


_OUTPUT_OVERRIDE: Path | None = None


def set_output_dir(path: str | Path | None) -> None:
    """Đổi thư mục output cho cả lần chạy này (cờ --out của CLI).

    Dùng khi muốn tách kết quả từng đợt gán nhãn ra thư mục riêng thay vì trộn
    chung vào `output/`.
    """
    global _OUTPUT_OVERRIDE
    if path is None:
        _OUTPUT_OVERRIDE = None
        return
    candidate = Path(path).expanduser()
    _OUTPUT_OVERRIDE = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def output_dir() -> Path:
    return _OUTPUT_OVERRIDE or PROJECT_ROOT / settings()["output"]["dir"]
