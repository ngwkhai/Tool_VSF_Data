"""Schema output và parser cho khối text Gemini trả về."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

# Bộ trường mong đợi từ Gemini chat #1 nằm ở TỪNG PROFILE
# (`vsf.profiles.food.PROFILE_FIELDS` / `...accom.PROFILE_FIELDS`) — POI đồ ăn
# hỏi 26 trường, POI lưu trú hỏi 28 trường khác. Parser dưới đây nhận bộ trường
# làm THAM SỐ chứ không tự tra: nó không được phép biết profile nào đang chạy,
# nếu không mỗi lần thêm dataset lại phải sửa vào đây.
#
# Parser KHÔNG bắt buộc đủ hết — thiếu thì để None, thừa thì gom vào `extra`.
# Mục tiêu là không bao giờ mất dữ liệu.

# Một dòng mở đầu trường mới: bắt đầu dòng, key snake_case, dấu hai chấm.
_FIELD_LINE = re.compile(r"^([a-z][a-z0-9_]{2,40}):\s*(.*)$")


def slugify(text: str) -> str:
    """'Bánh Canh Trần Văn Ơn' -> 'banh-canh-tran-van-on'."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "poi"


def parse_profile_block(
    raw: str,
    fields: Sequence[str] = (),
    list_fields: Collection[str] = (),
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Tách khối text ``key: value`` (value có thể trải nhiều dòng) thành dict.

    Luôn giữ lại ``_raw`` để nếu Gemini đổi format thì vẫn không mất gì.

    `fields`/`list_fields`/`aliases` lấy từ profile của POI đang chạy. Bỏ trống
    hết (mặc định) thì hàm chỉ giữ ``_raw`` + gom mọi dòng ``key: value`` vào
    ``extra`` — đúng nhu cầu của bước `menu`/`rooms`, nơi câu trả lời là một
    mảng JSON chứ không phải biểu mẫu, và một danh sách `_missing_fields` của
    profile chỉ là nhiễu.
    """
    aliases = aliases or {}
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
        canonical = key if key in fields else aliases.get(key)
        if canonical in list_fields:
            value = [p.strip(" .") for p in value.split(",") if p.strip(" .")]
        if canonical:
            # Đã có giá trị thật (không phải do alias khác ghi đè) thì đừng để
            # một alias yếu hơn xoá mất — ưu tiên khoá chuẩn đến trước.
            if canonical not in known or not known[canonical]:
                known[canonical] = value
        else:
            extra[key] = value

    for key in fields:
        result[key] = known.get(key)
    if extra:
        result["extra"] = extra

    missing = [k for k in fields if not result.get(k)]
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
    # Bộ dataset của POI này: "food" (73 cột) hay "accom" (72 cột). Quyết định
    # bộ cột, bộ trường hỏi Gemini, danh sách bước, và cả chiều của cổng phân
    # loại ngành — xem vsf/profiles/.
    # Mặc định "food" để 141 bản ghi CŨ (data.json chưa có khoá này) nạp được
    # qua `cls(**data)` và vẫn xuất ra đúng 73 cột như trước.
    profile: str = "food"
    # Địa chỉ mẫu do người dùng cung cấp để phân biệt quán trùng tên — dùng để
    # neo truy vấn Google Maps và đối chiếu kết quả (xem gmaps.address_match).
    # Rỗng thì bỏ qua bước đối chiếu này. Lưu lại để --resume/--only không cần
    # truyền lại --address mỗi lần.
    address_hint: str = ""
    # Google place_id do người dùng cung cấp sẵn (dán kèm danh sách POI). Neo
    # MẠNH hơn hẳn address_hint: mở thẳng đúng địa điểm thay vì tìm theo tên rồi
    # đối chiếu. Lưu lại để --resume/--only không cần truyền lại.
    place_id_hint: str = ""
    # Phân loại chốt ở bước `maps` (l1) và `gemini1` (l2) — xem schema.classify_l1
    # / schema.normalize_l2. `category_l1` khác nhóm ngành của profile ("FOOD"
    # với food, "ACCOM" với accom) là tín hiệu dừng pipeline: các bước sau bị bỏ
    # qua và row.tsv chỉ còn `name` + `category_l1`.
    # Mặc định rỗng để data.json của các lần chạy CŨ (chưa có hai khoá này) vẫn
    # nạp được qua `cls(**data)` mà không cần migration.
    category_l1: str = ""
    category_l2: str = ""
    slug: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Trạng thái từng bước: pending | ok | failed | skipped
    # GIỮ NGUYÊN kiểu chuỗi. `_skip_reason`, scripts/merge_rows.py và
    # scripts/rescore_tiktok.py đều so sánh `== "ok"` — đổi sang dict là vỡ hết.
    # Chi tiết lần chạy đi vào `step_runs` bên dưới.
    steps: dict[str, str] = field(default_factory=dict)
    # Cảnh báo gom theo bước, để chạy lại một bước thì xoá đúng cảnh báo cũ của
    # bước đó chứ không kéo lê cảnh báo đã hết hiệu lực sang lần chạy sau.
    warnings: dict[str, list[str]] = field(default_factory=dict)
    # Chi tiết lần chạy gần nhất của mỗi bước: thời điểm, thời lượng, và khi hỏng
    # thì cả traceback. Trước đây traceback bị vứt (`except Exception as exc` chỉ
    # giữ `str(exc)`), gỡ lỗi một bước hỏng lúc chạy lô qua đêm là bất khả thi.
    #   {"maps": {started_at, finished_at, duration_s,
    #             error_code, error_type, error_message, traceback}}
    step_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Cờ triage máy đọc được (xem errors.FLAG_*), song song với `warnings`.
    # `warnings` để người đọc, `flags` để lọc — không cái nào thay thế cái nào.
    # Gom theo bước Y HỆT `warnings`, vì cùng một lý do: chạy lại `maps` phải xoá
    # cờ `hours_incomplete` của lần trước, không kéo lê cờ đã hết hiệu lực.
    flags: dict[str, list[str]] = field(default_factory=dict)
    # Sửa tay từ giao diện, khoá theo tên cột trong COLUMNS của profile bản ghi.
    # build_row() áp CUỐI CÙNG, nên chạy lại một bước không xoá mất chỗ đã sửa.
    overrides: dict[str, str] = field(default_factory=dict)

    gemini_profile: dict[str, Any] = field(default_factory=dict)
    google_maps: dict[str, Any] = field(default_factory=dict)
    # Kết quả bước `menu` (profile food): thực đơn Gemini #2 trích từ ảnh.
    menu: dict[str, Any] = field(default_factory=dict)
    # Kết quả bước `rooms` (profile accom): bảng giá phòng Gemini #2 tra trên web.
    # Field RIÊNG chứ không tái dùng `menu`: hai thứ khác khoá, khác nguồn, và
    # dùng chung một field thì 141 data.json cũ phải migrate mới đọc đúng.
    rooms: dict[str, Any] = field(default_factory=dict)
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
        # Cờ --force-category (tên cũ --force-food, giữ làm bí danh): chỉ có hiệu
        # lực cho ĐÚNG lần chạy này, cố ý không ghi vào data.json — nếu không,
        # một lần ép tay sẽ vô hiệu cổng phân loại vĩnh viễn ở mọi lần chạy lại
        # sau đó. Tên thuộc tính giữ nguyên `force_food` để khớp cột DB cùng tên
        # và khoá CSV đã dùng, đổi tên chỉ tạo một đợt migration vô ích.
        self.force_food = False

    def begin_step(self, step: str) -> None:
        """Đánh dấu bước đang chạy, xoá cảnh báo + cờ cũ của chính bước đó."""
        self.current_step = step
        self.warnings.pop(step, None)
        self.flags.pop(step, None)

    def warn(self, message: str) -> None:
        bucket = self.warnings.setdefault(self.current_step, [])
        if message not in bucket:
            bucket.append(message)

    def flag(self, code: str) -> None:
        """Gắn cờ triage cho bước đang chạy. Đi kèm `warn()`, không thay thế nó."""
        bucket = self.flags.setdefault(self.current_step, [])
        if code not in bucket:
            bucket.append(code)

    def all_warnings(self) -> list[str]:
        return [f"[{step}] {m}" for step, msgs in self.warnings.items() for m in msgs]

    def all_flags(self) -> list[str]:
        """Cờ của mọi bước, khử trùng lặp, giữ thứ tự xuất hiện."""
        seen: dict[str, None] = {}
        for codes in self.flags.values():
            for code in codes:
                seen.setdefault(code, None)
        return list(seen)

    # -- lưu / nạp -----------------------------------------------------

    @classmethod
    def folder_for(cls, output_dir: Path, poi_name: str, index: int | None = None) -> Path:
        """Thư mục của POI. Có `index` thì đánh số `1_<slug>` để giữ thứ tự danh sách.

        Không có index thì vẫn tìm ra thư mục đã đánh số của lần chạy trước, để
        `vsf export "Tên POI"` không cần nhớ số thứ tự.
        """
        slug = slugify(poi_name)
        if index is not None:
            numbered = output_dir / f"{index}_{slug}"
            if numbered.exists():
                return numbered
            # Có `index` nhưng thư mục đánh số đó KHÔNG tồn tại: tìm tiếp thư mục
            # của cùng POI dưới tên khác trước khi chịu thua.
            #
            # Thiếu nhánh này là một lỗi CÂM: `vsf run` không có --index ghi ra
            # `<slug>/`, rồi `vsf batch reindex` gán seq=1..N cho các thư mục
            # không đánh số, nên giao diện đi tìm `1_<slug>` — không thấy, và
            # `load_or_new` lặng lẽ trả về bản ghi RỖNG. Kết quả: lat/long/
            # place_id và mọi cột lấy từ Google đều trống trên giao diện dù
            # data.json trên đĩa đầy đủ (đã gặp: "Lucky Sun Hotel").
            found = cls._existing_folder(output_dir, slug)
            return found if found is not None else numbered
        return cls._existing_folder(output_dir, slug) or output_dir / slug

    @staticmethod
    def _existing_folder(output_dir: Path, slug: str) -> Path | None:
        """Thư mục CÓ THẬT của POI: đúng tên slug, hoặc bản đã đánh số bất kỳ."""
        exact = output_dir / slug
        if exact.exists():
            return exact
        numbered = sorted(output_dir.glob(f"*_{slug}")) if output_dir.exists() else []
        return numbered[0] if numbered else None

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
    def load_folder(cls, folder: Path) -> "POIRecord":
        """Nạp thẳng từ một thư mục POI đã biết.

        `load_or_new` đi từ TÊN POI nên không dùng được để quét thư mục: tên thư
        mục đã đánh số ("7_bun-bo-tung-hoang") slugify ra "7-bun-bo-tung-hoang",
        không khớp lại chính nó, và hàm đó lặng lẽ trả về một bản ghi RỖNG mới.
        """
        data = json.loads((folder / "data.json").read_text(encoding="utf-8"))
        data.pop("slug", None)
        record = cls(**data)
        record.slug = folder.name
        return record

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
