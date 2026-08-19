# Tool VSF Data

Tool gán nhãn & tăng cường dữ liệu POI (quán ăn, quán cà phê…) ở Nha Trang.

Bạn đưa vào **tên một quán**. Tool tự mở Chrome, chạy qua 6 bước (Google Maps →
Gemini → TikTok → Facebook), rồi ghi ra một dòng dữ liệu đúng 73 cột của dataset:

```bash
.venv/bin/vsf run "Bánh Canh Trần Văn Ơn"
```

```
output/banh-canh-tran-van-on/
├── row.tsv      ← kết quả chính, 73 cột, dán thẳng vào dataset
└── data.json    ← dữ liệu thô từng bước, để chạy tiếp và tra lại khi nghi ngờ
```

---

## 1. Cần chuẩn bị gì

| | |
|---|---|
| Máy | **macOS** — đường dẫn Chrome đang cố định trong `src/vsf/browser.py:25` |
| Python | 3.11 trở lên |
| Chrome | Google Chrome **thật**, cài sẵn |
| Tài khoản | Google (bắt buộc, để dùng Gemini) · TikTok (nên có) · Facebook (không bắt buộc) |

Tool mở một cửa sổ Chrome **riêng** với profile riêng (`~/.vsf-chrome-profile`).
Nó không đụng vào Chrome cá nhân của bạn: không chung cookie, không thấy tab của bạn.

---

## 2. Cài đặt — làm một lần duy nhất

### Bước 1 · Cài code

```bash
git clone <URL-repo> Tool_VSF_Data
cd Tool_VSF_Data

python3 -m venv .venv
.venv/bin/pip install -e .

.venv/bin/vsf --help        # thấy danh sách lệnh là được
```

Có `uv` thì nhanh hơn: `uv venv && uv pip install -e .`

### Bước 2 · Đăng nhập

```bash
.venv/bin/vsf login
```

Lệnh này mở cửa sổ Chrome của tool. Trong **đúng cửa sổ đó**, tự tay đăng nhập:

- <https://gemini.google.com> — tài khoản Google *(bắt buộc)*
- <https://www.tiktok.com> — tài khoản TikTok *(nên có)*
- <https://www.facebook.com> — tài khoản Facebook *(không bắt buộc)*

Đăng nhập xong cứ để cửa sổ đó đấy. Profile được lưu nên chỉ phải làm một lần.

### Bước 3 · Tạo 2 cuộc trò chuyện Gemini của riêng bạn

Tool cần **hai thread Gemini riêng biệt**, dùng đi dùng lại:

| Thread | Việc |
|---|---|
| #1 | Hỏi 26 trường mô tả POI + tên phường trước sáp nhập 1/7/2025 |
| #2 | Nhận ảnh thực đơn dán vào, trả về menu |

Vào <https://gemini.google.com>, tạo 2 cuộc trò chuyện mới, gửi mỗi cái vài câu
bất kỳ để nó có URL cố định. URL trông thế này:

```
https://gemini.google.com/app/bac782da2aaa6656
                              └── phần này là ID thread
```

### Bước 4 · Sửa `config/settings.toml`

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

### Bước 5 · Kiểm tra

```bash
.venv/bin/vsf doctor
```

Bốn dòng **bắt buộc** phải đạt: Chrome + cổng CDP · Gemini chat #1 · Gemini chat
#2 · TikTok truy cập được. Hai dòng còn lại (đăng nhập TikTok, đăng nhập Facebook)
hỏng cũng chạy được, chỉ mất phần tăng cường.

---

## 3. Chạy tool

### Cách 1 · Giao diện — dễ nhất cho người mới

Cài thêm một lần (cần **Node.js**):

```bash
.venv/bin/pip install -e ".[ui]"        # có uv thì: uv pip install -e ".[ui]"
cd ui && npm install && npm run build && cd ..
```

Mở giao diện:

```bash
.venv/bin/vsf ui          # http://127.0.0.1:8000
```

Trong giao diện:

1. **Đợt gán nhãn** → dán danh sách quán vào ô, đặt tên thư mục kết quả → *Nạp*.
2. Bấm **Chạy**. Tiến độ hiện ngay tại chỗ, không phải nhìn terminal.
3. **Cần xử lý** → xem POI nào có vấn đề và vì sao.
4. Bấm vào một POI → xem 6 bước, sửa tay 73 cột, chọn ảnh, đổi link TikTok.

Danh sách dán vào ô có thể là **3 cột copy thẳng từ bảng tính**:

```
Bún Bò Thành Danh	124 Trần Phú, Nha Trang	ChIJzWzaPZ1ncDER5ZVqZtJM6qY
```

hoặc chỉ mỗi tên, mỗi dòng một quán.

### Cách 2 · Dòng lệnh

```bash
# Một quán
.venv/bin/vsf run "Cà Phê Nhiên"

# Quán trùng tên với quán khác → đưa thêm địa chỉ để neo cho đúng
.venv/bin/vsf run "Greek Cuisine" --address "172/2 Bạch Đằng"

# Đánh số thứ tự + tách thư mục theo đợt
.venv/bin/vsf run "Cà Phê Nhiên" --index 3 --out output_20_8

# Chạy lại, bỏ qua bước đã xong
.venv/bin/vsf run "Cà Phê Nhiên" --resume

# Chạy lại đúng một bước
.venv/bin/vsf run "Cà Phê Nhiên" --only maps
#   6 bước: maps | gemini1 | old_address | menu | tiktok | facebook

# Xuất lại row.tsv từ data.json đã có (không mở Chrome)
.venv/bin/vsf export "Cà Phê Nhiên"
.venv/bin/vsf export "Cà Phê Nhiên" --tiktok 2     # đổi sang ứng viên TikTok khác
```

Chạy cả một danh sách:

```bash
.venv/bin/vsf batch add danh_sach.csv --out output_19_8 --name "Đợt 19/8"
.venv/bin/vsf batch run --batch 3        # chạy tuần tự cả lô
.venv/bin/vsf batch status               # xem tiến độ
.venv/bin/vsf batch export --batch 3     # gộp row.tsv cả đợt
```

---

## 4. Sáu lưu ý đáng nhớ

1. **Đừng đóng cửa sổ Chrome của tool** giữa các lần chạy. Nó cố ý sống lâu để
   lần sau vào thẳng, không phải mở lại và đăng nhập lại.
2. **Có `place_id` thì luôn đưa vào.** Đó là cái neo chắc nhất — tool mở thẳng
   đúng quán, bỏ qua hẳn khâu tìm kiếm và cả lớp lỗi "Google trả nhầm quán".
3. **Bước `maps` hỏng là dừng cả chuỗi.** Nó chạy đầu tiên và giữ hai cổng chặn,
   nên 5 bước sau đều phụ thuộc nó.
4. **Ô trống không phải lỗi.** Dưới ngưỡng tin cậy thì tool để trống thay vì ghi
   bừa — ô trống sửa được, còn dữ liệu sai lặng lẽ thì không.
5. **Chạy lại không xoá phần bạn sửa tay.** Sửa trong giao diện được lưu riêng
   và áp lên cuối cùng lúc xuất file.
6. **`data.json` mới là gốc.** Cơ sở dữ liệu ở `state/vsf.db` chỉ là chỉ mục,
   xoá lúc nào cũng được rồi dựng lại bằng `vsf batch reindex`.

---

## 5. Khi có gì đó hỏng

| Thấy gì | Làm gì |
|---|---|
| `Không tìm thấy Chrome tại /Applications/...` | Chưa cài Chrome, hoặc không phải máy macOS. Sửa `CHROME_BIN` ở `src/vsf/browser.py:25` |
| `Chưa đăng nhập Google trong profile của tool` | Chạy `vsf login` rồi đăng nhập lại trong đúng cửa sổ đó |
| `CÓ THỂ LẤY NHẦM QUÁN: hỏi 'X' nhưng Google trả về 'Y'` | Đúng như báo. Chạy lại kèm `--address "<số nhà + tên đường>"`, hoặc tra `place_id` rồi đưa vào |
| `KHÔNG PHẢI FOOD: ... -> category_l1=OTHER` | Tool cho rằng đây không phải quán ăn. Đúng thì bỏ POI này; sai (vd quán ăn trong khách sạn) thì chạy lại với `--force-food` |
| `Timeout waiting for selector` / một trường bỗng rỗng | Google hoặc TikTok đổi giao diện. Selector nằm hết ở `config/selectors.toml` — sửa file đó, **đừng sửa code**. Dò lại bằng `.venv/bin/python scripts/recon.py gmaps "<tên POI>"` |
| `Bỏ qua bước thực đơn: không có ảnh thực đơn nào` | Quán không có mục "Thực đơn" trên Google Maps. Bình thường, cột `menu` để trống |
| `chỉ tìm được 2/5 bài tiêu cực` | Quán ít bài chê. Bình thường, không phải lỗi |
| Thread Gemini mới toanh chỉ trả về ~8/26 trường | Thread rỗng khiến Gemini luôn bật tính năng tra địa điểm và trả mẫu cố định. Dùng thêm vài lượt là ổn định lại |
| Chrome đơ, tool không phản hồi | Đóng hết cửa sổ Chrome **của tool** rồi chạy lại. Profile không mất |

Kiểm tra code còn lành:

```bash
.venv/bin/python -m pytest tests/ -q      # 282 test, không cần browser
```

---

## 6. Đọc thêm

| File | Nội dung |
|---|---|
| `config/settings.toml` | Toàn bộ prompt, ngưỡng, bảng phân loại, URL thread Gemini |
| `config/selectors.toml` | Toàn bộ CSS selector của Google Maps / Gemini / TikTok / Facebook |
| `CLAUDE.md` | Ghi chú kỹ thuật, quy ước 73 cột, và danh sách cạm bẫy đã vấp |

**Hai quy tắc quan trọng nhất khi sửa tool:**

1. Selector đổi thì sửa `config/selectors.toml`, đừng viết thẳng vào code.
2. Prompt đổi thì sửa `config/settings.toml`. Comment ngay phía trên mỗi prompt
   ghi rõ **cách viết nào đã thất bại và vì sao** — đọc trước khi sửa để khỏi
   lặp lại.

Thư mục `output*/` không đẩy lên repo (xem `.gitignore`) — dữ liệu gán nhãn là
của riêng từng người.
