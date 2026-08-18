"""Tìm video TikTok liên quan tới POI."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page

from ..config import sel, sel_list, settings
from ..waits import wait_until

_VIDEO_ID = re.compile(r"/video/(\d+)")
# Handle nằm ở href (/@handle/video/<id>). KHÔNG lấy từ search-card-user-unique-id:
# phần tử đó hiển thị NICKNAME, không phải handle (đã đo 2026-08-18 — so nhầm ở đây
# làm tôi kết luận sai rằng tài khoản chính chủ vắng mặt trong tab Videos).
_HANDLE = re.compile(r"/@([^/?#]+)")
# Plus code Google ("65VV+G77") đứng ở vị trí số nhà nhưng KHÔNG phải địa chỉ đường.
_PLUS_CODE = re.compile(r"^[0-9A-Z]{4}\+")
_HOUSE_NUMBER = re.compile(r"\s*(\d+[a-z]?)\b")


def posted_at_from_url(url: str) -> str | None:
    """Giải mã ngày đăng từ chính video ID.

    32 bit cao của ID TikTok là Unix timestamp lúc đăng. Chính xác tuyệt đối và
    không tốn thêm một lượt tải trang nào cho mỗi video.
    """
    m = _VIDEO_ID.search(url)
    if not m:
        return None
    ts = int(m.group(1)) >> 32
    # Chặn giá trị vô lý (ID lạ / đổi định dạng): TikTok ra đời 2016.
    if not (1451606400 < ts < 4102444800):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# Chuyển tự Cyrillic -> Latin. Không có bảng này thì `_squash("Кафе Лан")` ra chuỗi
# RỖNG (regex chỉ giữ [a-z0-9]) và mọi phép so khớp đều trả 0 trong im lặng — đó là
# lý do 12 POI tên Nga/Hàn toàn 0.0 điểm. Đủ dùng cho tên quán, không cần chuẩn ISO.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _normalize(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(_CYRILLIC.get(c, c) for c in text)


def _squash(text: str) -> str:
    """Bản dính liền, chỉ còn chữ và số — để bắt hashtag kiểu '#banhcanhlongca'."""
    return re.sub(r"[^a-z0-9]", "", _normalize(text))


def _words(text: str) -> list[str]:
    return [w for w in _normalize(text).split() if len(w) > 1]


def match_score(poi: str, caption: str) -> float:
    """Tỉ lệ từ trong tên POI xuất hiện ở caption (đã bỏ dấu).

    Khớp theo RANH GIỚI TỪ, không theo chuỗi con: từ ngắn như "on" (từ "Ơn") nằm
    lọt trong "huong" của "hướng dẫn" và sẽ tạo điểm giả.

    Riêng từ dài >= 3 ký tự còn được đối chiếu với bản caption đã bỏ hết khoảng
    trắng, để bắt được hashtag dính liền kiểu "#banhcanhlongca".

    Giữ lại làm chỉ số THÔ (không trọng số) — `score_candidate` mới là thứ quyết
    định thứ hạng.
    """
    words = _words(poi)
    if not words:
        return 0.0

    hay = _normalize(caption)
    squashed = _squash(caption)

    hits = 0
    for word in words:
        if _hits(word, hay, squashed):
            hits += 1
    return hits / len(words)


def _hits(word: str, hay: str, squashed: str) -> bool:
    if re.search(rf"\b{re.escape(word)}\b", hay):
        return True
    return len(word) >= 3 and word in squashed


# -- Chấm điểm đa tín hiệu -------------------------------------------------


def document_frequency(captions: list[str]) -> dict[str, int]:
    """Số caption chứa mỗi từ, tính TRÊN CHÍNH bể ứng viên của truy vấn này.

    Đây là mấu chốt phá thế hoà điểm: từ nào xuất hiện ở MỌI ứng viên thì không
    phân biệt được gì và phải bị triệt tiêu trọng số. Đo trên 595 caption thật:
    "nha" có ở 61.7% caption, "trang" 53.6%, "quan" 27.9% — nên mọi POI có
    "Nha Trang" trong tên đều được cộng điểm miễn phí ở mọi video, và cả 5 ứng
    viên hoà nhau (đã gặp: "Ăn Vặt Trịnh Huệ" = 0.5 cho cả 5, không cái nào nhắc
    tới "Trịnh Huệ").

    Tính cục bộ theo từng truy vấn nên tự hiệu chỉnh, không cần corpus dựng sẵn.
    """
    df: dict[str, int] = {}
    for caption in captions:
        for word in set(re.findall(r"[a-z0-9]+", _normalize(caption))):
            df[word] = df.get(word, 0) + 1
    return df


def _idf(word: str, df: dict[str, int], total: int) -> float:
    """Trọng số của một từ: càng phổ biến trong bể ứng viên càng gần 0."""
    return math.log((total + 1) / (df.get(word, 0) + 1))


def _industry_stopwords() -> set[str]:
    """Từ chỉ NGÀNH, không chỉ danh tính quán — khai báo tay, đã bỏ dấu.

    Cần thêm danh sách này BÊN CẠNH idf: idf tính trên corpus caption tiếng Việt
    nên coi từ ngành tiếng Anh là "hiếm" và cho điểm cao oan (đã gặp: "milk"
    được coi là đặc trưng, khiến "La Tra Milk Tea" khớp nhầm sang tài khoản
    "@kachamilkteanhatrang").
    """
    raw = settings()["tiktok"].get("industry_stopwords", [])
    return {_normalize(w) for w in raw}


def caption_score(poi: str, caption: str, df: dict[str, int], total: int) -> float:
    """Tỉ lệ khớp có TRỌNG SỐ: từ đặc trưng nặng, từ chung ngành gần như không tính."""
    words = _words(poi)
    if not words:
        return 0.0
    stop = _industry_stopwords()
    hay = _normalize(caption)
    squashed = _squash(caption)

    weights = {}
    for word in words:
        weight = _idf(word, df, total)
        if word in stop:
            weight *= 0.15
        weights[word] = weight

    denominator = sum(weights.values())
    if denominator <= 0:
        return 0.0
    got = sum(w for word, w in weights.items() if _hits(word, hay, squashed))
    return got / denominator


def _name_segments(poi: str) -> list[str]:
    """Tên đầy đủ + từng đoạn tách bởi dấu ngăn.

    Tên POI hay gộp nhiều biến thể của cùng một quán — tên Việt, tên Latin, tên
    mặt hàng — mà tài khoản chính chủ chỉ lấy MỘT trong số đó làm handle.
    """
    parts = [poi, *re.split(r"[.\-–—|/(),]", poi)]
    return [p.strip() for p in parts if p.strip()]


def author_score(poi: str, author: str) -> float:
    """Mức tin rằng tài khoản này CHÍNH LÀ quán.

    Tín hiệu mạnh nhất và trước nay bị bỏ phí hoàn toàn: đo trên 121 POI, 55 POI
    có tài khoản chính chủ trong danh sách, 25 trong số đó không được xếp #1
    (@doi.cafenhatrang, @gachcua.nhatrang, @quan.cay.me.nha.trang... đều bị xếp
    dưới reviewer vãng lai).

    GUARD: chỉ nhận token >= 4 ký tự. Từ ngắn sau khi bỏ dấu sinh dương tính giả
    rất khó thấy — "Đam" khớp "@Xóm Đầm" (Đầm ≠ Đam).

    CỐ Ý KHÔNG dùng idf của caption ở đây. So tên-với-handle là việc KHÁC với
    phân biệt caption: khi chính chủ đăng cả 5 video, tên quán có mặt ở mọi
    caption nên idf tụt về 0 và bộ lọc "từ đặc trưng" ném đi đúng cái tên cần
    khớp (đã gặp: "chớm brew&bloom" được 0.0 dù cả 5 ứng viên đều của @chớm).
    """
    handle = _squash(author)
    if not handle:
        return 0.0

    # Tên quán viết dính liền nằm nguyên trong handle -> gần như chắc chắn chính chủ.
    # Xét cả TỪNG ĐOẠN của tên, không chỉ toàn bộ: tên quán hay ghép nhiều biến thể
    # ("La Tra Milk Tea - Smoothie - Trà Sữa Lá Trà" -> @trasualatra;
    # "ФоБорщ / PhoBorsch" -> @phoborsch) và chỉ MỘT đoạn khớp handle.
    for segment in _name_segments(poi):
        squashed = _squash(segment)
        if len(squashed) >= 5 and squashed in handle:
            return 1.0

    stop = _industry_stopwords()
    core = [w for w in _words(poi) if len(w) >= 4 and w not in stop]
    if not core:
        return 0.0
    return sum(1 for w in core if w in handle) / len(core)


def tag_score(poi: str, caption: str) -> float:
    """Tên quán viết dính liền xuất hiện nguyên khối (thường là hashtag)."""
    whole = _squash(poi)
    if len(whole) < 6:
        return 0.0
    return 1.0 if whole in _squash(caption) else 0.0


def street_of(address: str) -> tuple[str, list[str]]:
    """Tách số nhà + tên đường, hoặc ('', []) nếu đoạn đầu không phải địa chỉ đường.

    GUARD: bỏ Plus code ("65VV+G77") và các mục không có số nhà ("Sông Cái" — tên
    sông). Không có guard này thì tín hiệu địa chỉ bắn lung tung: "ĐẢO GÀ SÁU LỘC"
    từng bị tài khoản cho thuê ca-nô thắng vì cùng nhắc "Sông Cái".
    """
    if not address:
        return "", []
    head = address.split(",")[0].strip()
    if _PLUS_CODE.match(head):
        return "", []
    m = _HOUSE_NUMBER.match(_normalize(head))
    if not m:
        return "", []
    words = [w for w in _normalize(head).split() if len(w) > 2 and not w[0].isdigit()]
    return m.group(1), words


def address_score(address: str, caption: str) -> float:
    """Caption có nhắc số nhà / tên đường của quán không.

    Đây là thứ phân biệt CHI NHÁNH, việc mà khớp tên không bao giờ làm được: "Cà
    phê Đất Vàng" ở 121 Phạm Văn Đồng từng bị gán video của chi nhánh Mai Xuân
    Thưởng, trong khi ứng viên đúng có hẳn "121 Phạm Văn Đồng" trong caption.
    """
    number, words = street_of(address)
    if not number:
        return 0.0
    hay = _normalize(caption)
    score = 0.0
    if re.search(rf"\b{re.escape(number)}\b", hay):
        score += 0.5
    if words and sum(1 for w in words if w in hay) / len(words) >= 0.6:
        score += 0.5
    return score


def score_candidate(
    poi: str,
    cand: dict[str, Any],
    df: dict[str, int],
    total: int,
    address: str = "",
    official_handles: frozenset[str] = frozenset(),
) -> tuple[float, dict[str, float]]:
    """Điểm tổng + bảng phân rã từng tín hiệu.

    Bảng phân rã được lưu vào data.json để về sau biết ĐƯỢC CHỌN VÌ SAO, thay vì
    chỉ thấy một con số trần trụi.
    """
    cfg = settings()["tiktok"]
    caption = cand.get("caption") or ""
    author = cand.get("author") or ""
    handle = cand.get("handle") or ""

    parts = {
        "caption": round(caption_score(poi, caption, df, total), 3),
        # Tài khoản đã được tab Users xác nhận thì khỏi đoán qua tên.
        "author": 1.0
        if handle and _normalize(handle) in official_handles
        else round(max(author_score(poi, author), author_score(poi, handle)), 3),
        "tag": tag_score(poi, caption),
        "address": address_score(address, caption),
    }
    total_score = (
        cfg["weight_caption"] * parts["caption"]
        + cfg["weight_author"] * parts["author"]
        + cfg["weight_tag"] * parts["tag"]
        + cfg["weight_address"] * parts["address"]
    )
    return round(total_score, 4), parts


def parse_views(text: str) -> int:
    """'7254' -> 7254, '1.2M' -> 1200000, '12.3K' -> 12300."""
    raw = (text or "").strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB]?)$", raw)
    if not m:
        return 0
    try:
        value = float(m.group(1))
    except ValueError:
        return 0
    return int(value * {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2)])


def rank_candidates(
    poi: str,
    candidates: list[dict[str, Any]],
    address: str = "",
    official_handles: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Chấm điểm và sắp xếp giảm dần, gắn `score` + `score_breakdown` vào từng ứng viên."""
    captions = [c.get("caption") or "" for c in candidates]
    df = document_frequency(captions)
    total = len(captions)

    for cand in candidates:
        score, parts = score_candidate(poi, cand, df, total, address, official_handles)
        cand["score"] = score
        cand["score_breakdown"] = parts

    # Lượt xem CHỈ dùng để phá thế hoà, không phải một tín hiệu có trọng số: video
    # nhiều view nhất về quán khác vẫn là video sai quán. Nhưng khi mọi ứng viên
    # cùng của tài khoản chính chủ (hay gặp — cả 5 đều đúng), chọn cái nhiều người
    # xem hơn là hợp lý hẳn (đã gặp: "Đợi Café" hoà 0.9 cả 5, ứng viên đầu chỉ 26
    # view trong khi có cái 7.254 view).
    candidates.sort(key=lambda c: (c["score"], parse_views(c.get("views", ""))), reverse=True)
    return candidates


def simplify(poi: str) -> str:
    """Rút gọn tên POI thành từ khoá tìm kiếm.

    TikTok không ra kết quả với tên dài đầy dấu chấm và ngoặc
    ("Bánh Cuốn Tây Sơn. Vn - Ms.Smile (Quán ăn ngon ở Nha Trang)").
    Bỏ phần chú thích trong ngoặc và cắt tại dấu ngăn đầu tiên.

    Dấu `/` cũng là dấu ngăn: nhiều POI Nha Trang mang cả tên gốc lẫn tên Latin
    ("ФоБорщ / PhoBorsch") — nửa Latin mới là thứ khớp được caption tiếng Việt.
    """
    text = re.sub(r"\([^)]*\)", " ", poi)
    text = re.split(r"[.\-–—|/]", text)[0]
    return re.sub(r"\s+", " ", text).strip()


def _query_candidates(poi: str, region: str) -> list[str]:
    """Các truy vấn sẽ thử lần lượt: tên đầy đủ trước, rút gọn sau."""
    anchored = poi if not region or _normalize(region) in _normalize(poi) else f"{poi} {region}"
    queries = [anchored]

    short = simplify(poi)
    if short and _normalize(short) != _normalize(poi):
        if region and _normalize(region) not in _normalize(short):
            short = f"{short} {region}"
        queries.append(short)
    return queries



# -- Cào ứng viên ----------------------------------------------------------

# Duyệt thẳng các thẻ <a href="/@..."> trên trang kết quả Người dùng.
# KHÔNG đi ngược từ nút follow lên cha: walk-up chạm container chung của cả danh
# sách nên 20 card gộp thành 1 (đã gặp khi dò 2026-08-18).
_USER_CARDS_JS = """
() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href^="/@"]')) {
    const href = a.getAttribute('href') || '';
    if (!/^\\/@[^/?#]+$/.test(href) || seen.has(href)) continue;
    const lines = a.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
    // Link điều hướng (avatar, menu) chỉ có 0-1 dòng; card thật có nickname + handle.
    if (lines.length < 2) continue;
    seen.add(href);
    out.push({handle: href.slice(2), nickname: lines[0]});
  }
  return out;
}
"""


# Tab Người dùng CHỈ chạy khi đã đăng nhập TikTok. Chưa đăng nhập thì nó render
# "Đã xảy ra lỗi" kèm nút Đăng nhập và không bao giờ có kết quả — phát hiện sớm để
# khỏi chờ hết timeout ở MỖI POI trong một đợt gán nhãn dài.
_USER_TAB_BLOCKED_JS = """
() => /Đã xảy ra lỗi|Something went wrong/.test(document.body.innerText)
"""


def search_users(page: Page, poi: str) -> list[dict[str, Any]]:
    """Tra tab "Người dùng" để tìm TÀI KHOẢN CHÍNH CHỦ của quán.

    Đây là cách duy nhất gỡ được nhóm POI tên không phải Latin: công cụ tìm kiếm
    của TikTok tự chuyển tự, "Кафе Лан" ra "@caflan.flan.gi.s / CAFLAN NHA TRANG"
    — việc mà mọi cách so chuỗi cục bộ (bỏ dấu, fuzzy, idf) đều bó tay vì caption
    tiếng Việt không chứa một ký tự Cyrillic nào.

    CHỈ lấy tên tài khoản để làm trọng số xếp hạng. KHÔNG mở trang profile: lưới
    video ở đó trả "Đã xảy ra lỗi", còn trang chi tiết video trả HTTP 403.
    """
    cfg = settings()["tiktok"]
    region = settings()["gmaps"].get("search_region", "")
    query = _query_candidates(poi, region)[0]

    page.goto(cfg["user_search_url"].format(query=quote(query)), wait_until="domcontentloaded")
    if page.locator(sel("tiktok", "captcha")).count():
        raise RuntimeError("TikTok đang chặn bằng captcha. Mở cửa sổ tool và giải thủ công.")

    # KHÔNG chờ bằng wait_for_selector("a[href^='/@']"): thanh điều hướng bên trái
    # đã có sẵn link dạng đó, nên điều kiện thoả mãn NGAY LẬP TỨC, evaluate chạy
    # trước khi kết quả kịp nạp và trả về 0 tài khoản — trông y hệt "không có kết
    # quả" (đã gặp: trình duyệt thấy 20, tool thấy 0). Phải chờ tới khi có CARD
    # THẬT, tức link kèm cả nickname lẫn handle.
    state: dict[str, Any] = {}

    def ready() -> bool:
        state["users"] = page.evaluate(_USER_CARDS_JS)
        if state["users"]:
            return True
        # Chưa đăng nhập thì tab Người dùng trả thẳng "Đã xảy ra lỗi" và sẽ KHÔNG
        # bao giờ có kết quả -> thoát ngay, đừng đốt hết timeout cho mỗi POI.
        state["blocked"] = page.evaluate(_USER_TAB_BLOCKED_JS)
        return bool(state["blocked"])

    try:
        wait_until(
            ready,
            timeout=cfg["search_timeout_ms"] / 1000,
            what="kết quả tab Người dùng TikTok",
        )
    except TimeoutError:
        return []

    users: list[dict[str, Any]] = state.get("users") or []
    return users[: cfg["user_candidate_count"]]


def official_handles(poi: str, users: list[dict[str, Any]]) -> frozenset[str]:
    """Lọc ra tài khoản thực sự mang tên quán.

    Tab Users trả 20 kết quả xếp theo độ liên quan CỦA TIKTOK, không phải của ta:
    truy vấn "Кафе Лан" cho tài khoản 62K follower không liên quan ở #1 và quán
    thật ở #2. Nên vẫn phải tự đối chiếu tên.

    ĐỪNG thêm so khớp mờ (SequenceMatcher) ở đây — đã đo và nó chọn SAI đúng vào
    ca cần cứu: với "Кафе Лан" (chuyển tự "kafelan"), quán khác tên "Cafe Lan Anh"
    đạt 0.86 trong khi tài khoản đúng "@caflan.flan.gi.s" chỉ 0.71. Tên quán ngắn
    và na ná nhau quá nhiều để so mờ an toàn. Không khớp được thì để cổng tin cậy
    bỏ trống và người dùng chọn tay — sai lặng lẽ tệ hơn ô trống.
    """
    threshold = settings()["tiktok"]["official_account_threshold"]

    picked = set()
    for user in users:
        handle = user.get("handle") or ""
        nickname = user.get("nickname") or ""
        score = max(author_score(poi, handle), author_score(poi, nickname))
        if score >= threshold:
            picked.add(_normalize(handle))
    return frozenset(picked)


# Caption hiển thị bị CSS cắt cụt, nhưng thuộc tính alt của ảnh giữ NGUYÊN VẸN —
# kể cả địa chỉ đường ("📍Đợi Cf : Tầng trệt căn TO3, ... Đường Phước Lộc Thọ").
# Chính địa chỉ đó là thứ phân biệt chi nhánh, nên đọc alt trước.
_CARD_JS = """
([sel, captionSels]) => {
  const items = document.querySelectorAll(sel);
  const out = [];
  for (const it of items) {
    const a = it.querySelector('a[href*="/video/"]');
    if (!a) continue;
    const img = it.querySelector('img');
    let caption = img ? (img.alt || '').trim() : '';
    // Lùi về phần tử caption khi alt rỗng: nó bị CSS cắt cụt nên kém hơn alt,
    // nhưng caption cụt vẫn hơn hẳn không có caption nào (điểm sẽ sập về 0).
    if (!caption) {
      for (const cs of captionSels) {
        const el = it.querySelector(cs);
        if (el && el.innerText.trim()) { caption = el.innerText.trim(); break; }
      }
    }
    const views = it.querySelector('[data-e2e="video-views"]');
    out.push({
      url: a.href,
      alt: caption,
      views: views ? views.innerText.trim() : '',
    });
  }
  return out;
}
"""


def _collect(page: Page, url: str, item_sel: str, timeout: int) -> list[dict[str, Any]]:
    """Cào một tab kết quả. Trả [] khi tab không có gì (không phải lỗi)."""
    page.goto(url, wait_until="domcontentloaded")
    if page.locator(sel("tiktok", "captcha")).count():
        raise RuntimeError("TikTok đang chặn bằng captcha. Mở cửa sổ tool và giải thủ công.")
    try:
        page.wait_for_selector(item_sel, timeout=timeout)
    except Exception:
        if page.locator(sel("tiktok", "captcha")).count():
            raise RuntimeError("TikTok chặn bằng captcha.") from None
        return []
    return page.evaluate(_CARD_JS, [item_sel, sel_list("tiktok", "caption")])


def search(page: Page, poi: str, address: str = "") -> list[dict[str, Any]]:
    """Trả về danh sách ứng viên, sắp theo mức khớp POI giảm dần.

    Thử tên đầy đủ trước; không ra kết quả thì thử lại với tên rút gọn.
    """
    cfg = settings()["tiktok"]
    region = settings()["gmaps"].get("search_region", "")

    users = search_users(page, poi)
    handles = official_handles(poi, users)

    for query in _query_candidates(poi, region):
        if found := _search_once(page, poi, query, address, handles):
            return found
    return []


def _search_once(
    page: Page,
    poi: str,
    query: str,
    address: str,
    handles: frozenset[str],
) -> list[dict[str, Any]]:
    cfg = settings()["tiktok"]
    encoded = quote(query)
    timeout = cfg["search_timeout_ms"]

    # Hợp hai tab: "Top" trộn nhiều loại nội dung và chỉ cho 5-12 kết quả, tab
    # "Video" cho 23-24. Cuộn KHÔNG ra thêm (đã đo: 24 -> 24 sau 4 lần cuộn), nên
    # mở rộng bể ứng viên phải bằng cách đổi tab chứ không phải cuộn sâu hơn.
    rows = _collect(page, cfg["search_url"].format(query=encoded), sel("tiktok", "search_item"), timeout)
    rows += _collect(
        page,
        cfg["video_search_url"].format(query=encoded),
        sel("tiktok", "search_video_item"),
        timeout,
    )

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        url = row.get("url") or ""
        if "/video/" not in url or url in seen:
            continue
        seen.add(url)
        handle_match = _HANDLE.search(url)
        out.append(
            {
                "url": url,
                "caption": row.get("alt") or "",
                "author": handle_match.group(1) if handle_match else None,
                "handle": handle_match.group(1) if handle_match else "",
                "views": row.get("views") or "",
                "posted_at": posted_at_from_url(url),
                "match_score": round(match_score(poi, row.get("alt") or ""), 3),
            }
        )

    if not out:
        return []
    ranked = rank_candidates(poi, out, address, handles)
    return ranked[: cfg["candidate_count"]]
