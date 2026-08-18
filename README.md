# Tool VSF Data

Tool gán nhãn & tăng cường dữ liệu POI (quán ăn, quán cà phê…) ở Nha Trang.

Đưa vào **tên một quán**, tool tự mở Chrome, chạy qua 5 nguồn và ghi ra một dòng
dữ liệu đúng 73 cột của dataset:

```bash
.venv/bin/vsf run "Bánh Canh Trần Văn Ơn"
```

```
output/banh-canh-tran-van-on/
├── row.tsv      ← output chính thức, 73 cột, dán thẳng vào dataset
└── data.json    ← dữ liệu thô từng bước, để checkpoint và tra lại khi nghi ngờ
```

---

## Yêu cầu

| | |
|---|---|
| Hệ điều hành | **macOS** — đường dẫn Chrome đang hardcode trong `src/vsf/browser.py:25`. Máy Windows/Linux phải sửa dòng đó trước |
| Python | 3.11 trở lên |
| Google Chrome | Chrome **thật**, cài sẵn. Tool KHÔNG dùng Chromium của Playwright |
| Tài khoản | Một tài khoản Google (để dùng Gemini) và một tài khoản TikTok |

Tool tự mở một Chrome riêng với profile riêng (`~/.vsf-chrome-profile`) trên cổng
9222 — **không đụng vào Chrome cá nhân của bạn**, không dùng chung cookie, không
thấy tab của bạn.

---

## Cài đặt lần đầu

### 1. Tải code và cài thư viện

```bash
git clone <URL-repo> Tool_VSF_Data
cd Tool_VSF_Data

python3 -m venv .venv
.venv/bin/pip install -e .
```

Nếu có `uv` thì nhanh hơn: `uv venv && uv pip install -e .`

Kiểm tra:

```bash
.venv/bin/vsf --help
```

### 2. Đăng nhập Google + TikTok

```bash
.venv/bin/vsf login
```

Lệnh này mở cửa sổ Chrome riêng của tool. Trong cửa sổ đó, **tự tay đăng nhập**:

- <https://gemini.google.com> — tài khoản Google
- <https://www.tiktok.com> — tài khoản TikTok

Đăng nhập xong cứ để cửa sổ đó đấy. Profile được lưu lại nên chỉ phải làm một lần.

### 3. Tạo 2 thread Gemini của riêng bạn

Tool cần **hai cuộc trò chuyện Gemini riêng biệt**, dùng đi dùng lại:

| Thread | Việc |
|---|---|
| #1 | Hỏi 26 trường mô tả POI, và hỏi tên phường trước sáp nhập 1/7/2025 |
| #2 | Nhận ảnh thực đơn dán vào, trả về menu dạng JSON |

Vào <https://gemini.google.com>, tạo 2 cuộc trò chuyện mới, gửi mỗi cái một câu
bất kỳ để nó có URL cố định. URL sẽ có dạng:

```
https://gemini.google.com/app/bac782da2aaa6656
                              └── phần này là ID thread
```

### 4. Sửa `config/settings.toml`

Mở file, sửa **3 chỗ**:

```toml
[gemini]
profile_chat_url = "https://gemini.google.com/app/<ID-thread-1-cua-ban>?hl=vi"
menu_chat_url    = "https://gemini.google.com/app/<ID-thread-2-cua-ban>?hl=vi"

[dataset]
labeled_by = "<tên bạn>"
```

> ⚠️ URL thread của người khác **không dùng được** — Gemini chỉ cho chủ tài khoản
> mở thread của mình. Bắt buộc phải thay bằng thread của chính bạn.

### 5. Kiểm tra

```bash
.venv/bin/vsf doctor
```

Phải thấy ✓ ở cả 4 dòng: Chrome + cổng CDP, Gemini chat #1, Gemini chat #2,
TikTok truy cập được. Có ✗ thì xem bảng [Khi có gì đó hỏng](#khi-có-gì-đó-hỏng).

---

## Dùng hằng ngày

```bash
# Chạy một POI
.venv/bin/vsf run "Cà Phê Nhiên"

# Quán trùng tên với quán khác -> đưa thêm địa chỉ để neo cho đúng
.venv/bin/vsf run "Greek Cuisine" --address "172/2 Bạch Đằng"

# Đánh số thứ tự + tách riêng thư mục theo đợt gán nhãn
.venv/bin/vsf run "Cà Phê Nhiên" --index 3 --out output_20_8

# Chạy lại, bỏ qua các bước đã xong
.venv/bin/vsf run "Cà Phê Nhiên" --resume

# Chạy lại đúng một bước (khi bước đó hỏng)
.venv/bin/vsf run "Cà Phê Nhiên" --only maps
#   các bước: maps | gemini1 | old_address | menu | tiktok

# Xuất lại row.tsv từ data.json đã có (không cần mở Chrome)
.venv/bin/vsf export "Cà Phê Nhiên"

# Đổi sang link TikTok khác trong 5 ứng viên
.venv/bin/vsf export "Cà Phê Nhiên" --tiktok 2
```

**Đừng đóng cửa sổ Chrome của tool giữa các lần chạy.** Nó cố ý sống qua nhiều
lần chạy để lần sau attach vào luôn, không phải mở lại và đăng nhập lại.

---

## Tool chạy những bước gì

Đúng 5 bước, chạy theo thứ tự này:

| Bước | Nguồn | Lấy gì |
|---|---|---|
| `maps` | Google Maps | Nhãn ngành nghề, tên, địa chỉ, toạ độ, place_id, SĐT, giờ mở/đóng, ảnh đại diện + 3 ảnh phụ, 5 review 4–5★, 5 review 1–2★, ảnh thực đơn |
| `gemini1` | Gemini #1 | 26 trường mô tả (mô tả ngắn/dài, tags, đối tượng phù hợp, mẹo, khung giờ nên đi…) |
| `old_address` | Gemini #1 | Tên phường **trước** sáp nhập 1/7/2025 |
| `menu` | Gemini #2 | Dán ảnh thực đơn sang, nhận lại menu dạng JSON |
| `tiktok` | TikTok | Top 5 video ứng viên + caption + ngày đăng |

`maps` chạy **đầu tiên** là cố ý. Hai cổng chặn nằm ở đó:

1. **Lấy nhầm quán** — Google trả về quán khác tên/khác địa chỉ thì dừng hẳn,
   báo lỗi, không ghi bừa dữ liệu sai. Gặp lỗi này thì chạy lại với `--address`.
2. **Không phải quán ăn** — nếu Google xếp địa điểm vào ngành khách sạn / bảo
   tàng / bãi biển / siêu thị…, tool dừng luôn và `row.tsv` chỉ có mỗi cột `name`.
   Nhãn Google sai (ví dụ quán ăn trong khách sạn bị xếp ngành "Khách sạn") thì
   chạy lại với `--force-food`.

Cả hai cổng đều bắn **trước** khi tốn lượt Gemini nào — POI bị loại chỉ mất vài
giây thay vì vài phút.

Sau **mỗi** bước tool đều ghi `data.json`. Bước sau hỏng không làm mất kết quả
bước trước, cứ `--resume` là chạy tiếp từ chỗ dở.

---

## Kết quả trông thế nào

`row.tsv` là file TSV có **1 dòng tiêu đề + 1 dòng dữ liệu**, đúng 73 cột theo
thứ tự dataset. Mở bằng Excel/Google Sheets, hoặc copy dòng dữ liệu dán thẳng
vào sheet chung.

Vài cột được **cố ý để trống** cho người gán nhãn tự điền:
`seating_capacity`, `cover_image_url`, `gallery_urls`, `poi_id`, `reviewer_note`.
Ảnh chỉ để ở các cột `raw_*`.

Quy ước chi tiết từng cột (giá tính theo nghìn, giờ mở ca gãy, phường sau sáp
nhập, cách ngăn bình luận…) nằm ở bảng trong `CLAUDE.md`, mục *Tầng xuất dữ liệu*.

---

## Khi có gì đó hỏng

| Triệu chứng | Xử lý |
|---|---|
| `Không tìm thấy Chrome tại /Applications/...` | Chưa cài Chrome, hoặc không phải máy macOS. Sửa `CHROME_BIN` ở `src/vsf/browser.py:25` |
| `Chưa đăng nhập Google trong profile của tool` | Chạy `.venv/bin/vsf login` rồi đăng nhập lại trong cửa sổ đó |
| `CÓ THỂ LẤY NHẦM QUÁN: hỏi 'X' nhưng Google trả về 'Y'` | Đúng như báo — Google trả nhầm quán. Chạy lại kèm `--address "<số nhà + tên đường>"` |
| `KHÔNG PHẢI FOOD: Google xếp ... -> category_l1=OTHER` | Tool cho rằng đây không phải quán ăn. Đúng thì bỏ qua POI này; sai thì chạy lại với `--force-food` |
| `Timeout waiting for selector` / một trường bỗng rỗng | Google hoặc TikTok đổi giao diện. Selector nằm hết ở `config/selectors.toml` — sửa file đó, **đừng sửa code**. Có sẵn `.venv/bin/python scripts/recon.py gmaps "<tên POI>"` để dò lại |
| `Bỏ qua bước thực đơn: không có ảnh thực đơn nào` | Quán không có mục "Thực đơn" trên Google Maps. Bình thường, cột `menu` để trống |
| `chỉ tìm được 2/5 bài tiêu cực` | Quán ít bài chê. Bình thường, không phải lỗi |
| Chrome đơ, tool không phản hồi | Đóng hết cửa sổ Chrome của tool rồi chạy lại. Profile không mất |

Chạy test để chắc code không hỏng:

```bash
.venv/bin/python -m pytest tests/ -q
```

---

## Vấn đề đã biết (tính đến 18/8/2026)

- **Bước `gemini1` có lúc trả 0/26 trường.** Tool đọc nhầm câu trả lời của lượt
  trước trong thread thay vì lượt mới. Xảy ra khi thread chat đã rất dài, lịch
  sử nạp chậm. Dấu hiệu: cảnh báo `Gemini không cung cấp: <cả 26 trường>`. Tạm
  thời chạy lại `--only gemini1`; đang chờ sửa.
- **Thread Gemini mới, rỗng thì không cho đúng định dạng.** Thread rỗng khiến
  tính năng tra cứu địa điểm của Gemini luôn kích hoạt và trả về một mẫu cố định
  thay vì 26 trường được yêu cầu — đã thử 5 cách viết prompt khác nhau đều bị ghi
  đè. Thread càng dùng lâu càng ổn định. Nếu mới setup mà chỉ nhận được ~8/26
  trường thì đây là lý do.
- **Chỉ chạy được trên macOS** (đường dẫn Chrome hardcode).

---

## Cấu trúc thư mục

```
config/
  settings.toml      # TẤT CẢ prompt, ngưỡng, bảng phân loại, URL thread Gemini
  selectors.toml     # TẤT CẢ CSS selector của Google Maps / Gemini / TikTok
src/vsf/
  cli.py             # 4 lệnh: run, export, login, doctor
  pipeline.py        # điều phối 5 bước + hai cổng chặn
  schema.py          # ánh xạ sang 73 cột, mọi quy tắc định dạng
  models.py          # POIRecord (data.json) + parser câu trả lời Gemini
  browser.py         # spawn Chrome, quản lý tab theo "slot"
  sites/             # gmaps.py, gemini.py, tiktok.py
tests/               # 171 test, chạy được không cần browser
scripts/recon.py     # dò lại selector khi UI đổi
CLAUDE.md            # ghi chú kỹ thuật + danh sách cạm bẫy đã gặp
```

**Hai quy tắc quan trọng nhất khi sửa tool:**

1. Selector đổi thì sửa `config/selectors.toml`, không hardcode vào code.
2. Prompt đổi thì sửa `config/settings.toml`. Các prompt trong đó đã qua nhiều
   vòng thử — comment ngay phía trên mỗi prompt ghi rõ **cách viết nào đã thất
   bại và vì sao**. Đọc trước khi sửa để khỏi lặp lại.

Thư mục `output*/` không được đẩy lên repo (xem `.gitignore`) — dữ liệu gán nhãn
là của riêng từng người.
