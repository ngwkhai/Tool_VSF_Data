"""Schema output và parser cho khối text Gemini trả về."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Các trường mong đợi từ Gemini chat #1. Parser KHÔNG bắt buộc đủ hết —
# thiếu thì để None, thừa thì gom vào `extra`. Mục tiêu là không bao giờ mất dữ liệu.
PROFILE_FIELDS = [
    "name_en",
    "category_l2",
    "tags",
    "cuisine_type",
    "must_try_dishes",
    "price_per_person_avg",
    "seating_capacity",
    "dietary_options",
    "reservation_required",
    "dress_code",
    "alcohol_served",
    "view_type",
    "operating_note",
    "description_short",
    "description_long",
    "best_time_to_visit",
    "estimated_duration",
    "suitable_for",
    "not_suitable_for",
    "insider_tips",
    "weather_dependency",
    "crowd_level_note",
    "matched_intents",
    "search_keywords",
    "confidence_level",
    "info_expiry_note",
]

# Những trường vốn là danh sách ngăn cách bởi dấu phẩy.
LIST_FIELDS = {
    "tags",
    "matched_intents",
    "search_keywords",
    "cuisine_type",
    "must_try_dishes",
}

# Một dòng mở đầu trường mới: bắt đầu dòng, key snake_case, dấu hai chấm.
_FIELD_LINE = re.compile(r"^([a-z][a-z0-9_]{2,40}):\s*(.*)$")

# Gemini có một mẫu "hồ sơ địa điểm" CỐ ĐỊNH do tính năng grounding/tìm kiếm
# tự kích hoạt — đã kiểm chứng lặp lại Y HỆT (cùng bộ khoá, cùng thứ tự) trên
# nhiều lượt khác nhau dù prompt yêu cầu rõ ràng dùng đúng PROFILE_FIELDS.
# Không phải Gemini "quên" — đây là template nội bộ không đổi được bằng prompt.
# Ánh xạ các khoá lặp lại đó sang trường chuẩn còn map được nghĩa được; loại
# thuần trùng lặp với Google Maps (name/address/phone/rating/opening_hours) và
# loại không có trường tương ứng (payment_methods/parking/social_media/
# delivery_services/takeaway_available/amenities/child_friendly) thì bỏ qua —
# vẫn giữ nguyên trong `extra`, không mất dữ liệu.
FIELD_ALIASES = {
    "famous_dishes": "must_try_dishes",
    "price_range": "price_per_person_avg",  # xấp xỉ: lấy số đầu tiên tìm được
    "reservation": "reservation_required",
    "ambiance": "description_short",
    "service_style": "operating_note",
}


def slugify(text: str) -> str:
    """'Bánh Canh Trần Văn Ơn' -> 'banh-canh-tran-van-on'."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "poi"


def parse_profile_block(raw: str) -> dict[str, Any]:
    """Tách khối text ``key: value`` (value có thể trải nhiều dòng) thành dict.

    Luôn giữ lại ``_raw`` để nếu Gemini đổi format thì vẫn không mất gì.
    """
    parsed: dict[str, list[str]] = {}
    current: str | None = None

    for line in raw.splitlines():
        match = _FIELD_LINE.match(line.strip())
        if match:
            current = match.group(1)
            parsed[current] = [match.group(2).strip()]
        elif current and line.strip():
            # Dòng nối tiếp của trường đang mở.
            parsed[current].append(line.strip())

    result: dict[str, Any] = {"_raw": raw}
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}

    for key, chunks in parsed.items():
        value = " ".join(c for c in chunks if c).strip()
        canonical = key if key in PROFILE_FIELDS else FIELD_ALIASES.get(key)
        if canonical in LIST_FIELDS:
            value = [p.strip(" .") for p in value.split(",") if p.strip(" .")]
        if canonical:
            # Đã có giá trị thật (không phải do alias khác ghi đè) thì đừng để
            # một alias yếu hơn xoá mất — ưu tiên khoá chuẩn đến trước.
            if canonical not in known or not known[canonical]:
                known[canonical] = value
        else:
            extra[key] = value

    for key in PROFILE_FIELDS:
        result[key] = known.get(key)
    if extra:
        result["extra"] = extra

    missing = [k for k in PROFILE_FIELDS if not result.get(k)]
    if missing:
        result["_missing_fields"] = missing

    return result


@dataclass
class Review:
    author: str | None = None
    stars: int | None = None
    date: str | None = None
    text: str = ""


@dataclass
class TikTokCandidate:
    url: str
    caption: str = ""
    author: str | None = None
    posted_at: str | None = None
    match_score: float = 0.0


@dataclass
class POIRecord:
    """Toàn bộ dữ liệu thu thập được cho một POI. Serialise thẳng ra data.json."""

    poi_name: str
    # Địa chỉ mẫu do người dùng cung cấp để phân biệt quán trùng tên — dùng để
    # neo truy vấn Google Maps và đối chiếu kết quả (xem gmaps.address_match).
    # Rỗng thì bỏ qua bước đối chiếu này. Lưu lại để --resume/--only không cần
    # truyền lại --address mỗi lần.
    address_hint: str = ""
    # Phân loại chốt ở bước `maps` (l1) và `gemini1` (l2) — xem schema.classify_l1
    # / schema.normalize_l2. `category_l1` != "FOOD" là tín hiệu dừng pipeline:
    # các bước sau bị bỏ qua và row.tsv chỉ còn `name` + `category_l1`.
    # Mặc định rỗng để data.json của các lần chạy CŨ (chưa có hai khoá này) vẫn
    # nạp được qua `cls(**data)` mà không cần migration.
    category_l1: str = ""
    category_l2: str = ""
    slug: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Trạng thái từng bước: pending | ok | failed | skipped
    steps: dict[str, str] = field(default_factory=dict)
    # Cảnh báo gom theo bước, để chạy lại một bước thì xoá đúng cảnh báo cũ của
    # bước đó chứ không kéo lê cảnh báo đã hết hiệu lực sang lần chạy sau.
    warnings: dict[str, list[str]] = field(default_factory=dict)

    gemini_profile: dict[str, Any] = field(default_factory=dict)
    google_maps: dict[str, Any] = field(default_factory=dict)
    menu: dict[str, Any] = field(default_factory=dict)
    tiktok: list[dict[str, Any]] = field(default_factory=list)
    # {"candidates": [...], "verified": {...}|None, "reels": [...]} — nguồn XÁC MINH
    # danh tính (địa chỉ Trang đối chiếu địa chỉ Google), Reels chỉ là phần phụ.
    # Mặc định rỗng để data.json của các lần chạy CŨ vẫn nạp được qua `cls(**data)`.
    facebook: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.slug = self.slug or slugify(self.poi_name)
        self.created_at = self.created_at or now
        self.updated_at = now
        # Không phải field của dataclass -> asdict() bỏ qua, không lọt vào JSON.
        self.current_step = "?"
        # Cờ --force-food: chỉ có hiệu lực cho ĐÚNG lần chạy này, cố ý không ghi
        # vào data.json — nếu không, một lần ép tay sẽ vô hiệu cổng phân loại
        # vĩnh viễn ở mọi lần chạy lại sau đó.
        self.force_food = False

    def begin_step(self, step: str) -> None:
        """Đánh dấu bước đang chạy và xoá cảnh báo cũ của chính bước đó."""
        self.current_step = step
        self.warnings.pop(step, None)

    def warn(self, message: str) -> None:
        bucket = self.warnings.setdefault(self.current_step, [])
        if message not in bucket:
            bucket.append(message)

    def all_warnings(self) -> list[str]:
        return [f"[{step}] {m}" for step, msgs in self.warnings.items() for m in msgs]

    # -- lưu / nạp -----------------------------------------------------

    @staticmethod
    def folder_for(output_dir: Path, poi_name: str, index: int | None = None) -> Path:
        """Thư mục của POI. Có `index` thì đánh số `1_<slug>` để giữ thứ tự danh sách.

        Không có index thì vẫn tìm ra thư mục đã đánh số của lần chạy trước, để
        `vsf export "Tên POI"` không cần nhớ số thứ tự.
        """
        slug = slugify(poi_name)
        if index is not None:
            return output_dir / f"{index}_{slug}"
        exact = output_dir / slug
        if exact.exists():
            return exact
        numbered = sorted(output_dir.glob(f"*_{slug}")) if output_dir.exists() else []
        return numbered[0] if numbered else exact

    @staticmethod
    def path_for(output_dir: Path, poi_name: str, index: int | None = None) -> Path:
        return POIRecord.folder_for(output_dir, poi_name, index) / "data.json"

    def save(self, output_dir: Path) -> Path:
        """Ghi data.json. Gọi sau MỖI bước để bước sau fail không mất bước trước."""
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = output_dir / self.slug / "data.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    @classmethod
    def load_or_new(cls, output_dir: Path, poi_name: str, index: int | None = None) -> "POIRecord":
        folder = cls.folder_for(output_dir, poi_name, index)
        path = folder / "data.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("slug", None)
            record = cls(**data)
            record.slug = folder.name  # giữ đúng tên thư mục đang có
            return record
        record = cls(poi_name=poi_name)
        record.slug = folder.name
        return record
