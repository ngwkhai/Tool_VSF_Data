# Tool VSF Data

Tool gán nhãn & tăng cường dữ liệu POI. Nhận **tên một POI**, tự động thu thập
qua 5 bước và ghi ra:

- `output/<slug>/row.tsv` — **output chính thức**, đúng 73 cột của dataset.
- `output/<slug>/data.json` — bản ghi trung gian để checkpoint và tra cứu.

## Luồng nghiệp vụ

`STEPS = ["maps", "gemini1", "old_address", "menu", "tiktok", "facebook"]` — đúng 6 bước.

| Bước | Nguồn | Lấy gì |
|---|---|---|
| `maps` | Google Maps | **Nhãn ngành** (→ `category_l1`/`category_l2`), tên, địa chỉ, lat/long, place_id, SĐT, giờ mở/đóng, URL ảnh đại diện + 3 ảnh phụ, 5 review 4–5★, 5 review 1–2★, ảnh tab Thực đơn |
| `gemini1` | Gemini chat #1 (`bac782da...`) | Prompt **one-shot** (`[gemini] profile_prompt`) → cả 26 trường mô tả POI + quy ước trong MỘT lượt, kèm **địa chỉ Google đã xác nhận** ở bước `maps` để không lấy nhầm quán trùng tên |
| `old_address` | Gemini chat #1 | Tên phường **trước sáp nhập 1/7/2025** → `old_address` |
| `menu` | Gemini chat #2 (`d65843a9...`) | Dán ảnh thực đơn + `menu_prompt` → menu đã trích xuất |
| `tiktok` | TikTok | Hợp tab **Top + Video**, cộng tab **Người dùng** để tìm tài khoản chính chủ. Top 5 ứng viên kèm `score` + `score_breakdown` |
| `facebook` | Facebook | **Xác minh danh tính**: `search/pages` trả địa chỉ Trang → đối chiếu địa chỉ Google. Chỉ khi khớp mới lấy Reels |

**`maps` chạy TRƯỚC `gemini1` là cố ý.** Hai cổng chặn (lấy nhầm quán, không
phải FOOD) đều nằm ở `maps` và đều đặt ngay sau `basic_info` — trước khi cào
giờ/ảnh/đánh giá/thực đơn. Đặt sau thì mỗi POI bị loại vẫn đốt hết lượt Gemini
rồi mới vứt đi. Hệ quả: **`maps` hỏng là dừng cả chuỗi** (`_skip_reason`), vì
mọi bước sau đều phụ thuộc nó.

## Quy tắc quan trọng

- **Selector nằm hết ở `config/selectors.toml`** — không hardcode selector trong
  code. UI Google/TikTok đổi liên tục; vá config chứ không sửa module.
  Dùng `sel()` / `sel_list()` trong `config.py`. `sel_list` cho phép khai báo
  nhiều selector ứng viên, thử lần lượt tới khi khớp.
- **Không dùng `sleep()` cố định.** Dùng `waits.wait_until` / `waits.wait_stable`.
- **Nhận biết Gemini trả lời xong bằng nút đánh giá/sao chép**, không bằng "text
  ngừng đổi". Gemini hay đứng yên nhiều giây giữa chừng (lúc tìm kiếm web, hoặc
  trước khi bung khối JSON lớn) — chỉ dựa vào text sẽ cắt mất phần lớn câu trả
  lời (đã gặp: dừng ở 117 ký tự, thực tế là 12.527).
- **Ảnh đại diện + 3 ảnh phụ: chỉ lưu URL**, không tải file.
- **Ảnh thực đơn: paste thẳng vào Gemini** qua synthetic `ClipboardEvent` trong
  page context — không có file nào chạm đĩa. Xem `paste.py`.
- **Ghi `data.json` sau MỖI bước** (`record.save()`), để bước sau fail không làm
  mất kết quả bước trước. Có `--resume` và `--only`.
- **Không đóng browser khi script kết thúc.** Chrome do tool tự spawn detached
  với profile riêng (`~/.vsf-chrome-profile`), sống qua nhiều lần chạy.
- **Tái dùng tab, không mở tab mới mỗi lần chạy.** `Session` nhận lại tab cũ
  bằng cách so **URL đang mở** với `slot_url_prefixes()`. Đừng quay lại cách gắn
  nhãn `window.__vsf_slot__`: đó là biến JS, bị xoá mỗi lần điều hướng, nên tab
  cũ không bao giờ được nhận ra và số tab cứ thế phình lên.
- Parser Gemini **luôn giữ `_raw`** và gom trường lạ vào `extra` — không bao giờ
  im lặng làm mất dữ liệu. Trường thiếu báo qua `_missing_fields`.
- **Xếp hạng video là tổ hợp 4 tín hiệu có trọng số** (`caption`/`author`/`tag`/
  `address`), trọng số nằm ở `[tiktok]` trong settings. Mỗi ứng viên lưu kèm
  `score_breakdown` để về sau biết được chọn VÌ SAO. Đổi trọng số thì **phải**
  chạy lại `scripts/rescore_tiktok.py` — nó chấm lại toàn bộ `output*/data.json`
  offline, 0 request, và chính nó đã phát hiện cả 3 guard hiện có.
- **Dưới `confidence_threshold` thì `raw_url` để TRỐNG**, không ghi bừa ứng viên
  tốt nhất. Đo trên 119 POI: hơn 1/3 số dòng cũ không có cơ sở nào để tin. Ô
  trống sửa được, dữ liệu sai lặng lẽ thì không.
- **Facebook là bước TĂNG CƯỜNG, không phải cổng chặn.** Chưa đăng nhập hoặc
  không tìm thấy Trang thì cảnh báo rồi đi tiếp — đừng raise, nó là bước cuối.

## Lệnh

```bash
.venv/bin/vsf login      # mở Chrome profile riêng để đăng nhập Google + TikTok
.venv/bin/vsf doctor     # kiểm tra profile, đăng nhập, 2 chat URL
.venv/bin/vsf run "Tên POI"
.venv/bin/vsf run "Tên POI" --only maps      # maps | gemini1 | old_address | menu | tiktok | facebook
.venv/bin/vsf run "Tên POI" --resume         # bỏ qua bước đã ok
.venv/bin/vsf run "Tên POI" --index 3 --out output_12/8   # đợt gán nhãn riêng
.venv/bin/vsf run "Tên POI" --address "223 Nguyễn Thiện Thuật"   # quán trùng tên -> neo địa chỉ
.venv/bin/vsf run "Tên POI" --force-food     # nhãn ngành Google gây hiểu nhầm -> bỏ qua cổng FOOD
.venv/bin/vsf export "Tên POI"               # xuất lại row.tsv từ data.json
.venv/bin/vsf export "Tên POI" --tiktok 2    # đổi link TikTok đã chọn
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/rescore_tiktok.py --threshold   # chấm lại offline, dò ngưỡng
```

## Tầng xuất dữ liệu (`schema.py`)

`COLUMNS` phải khớp **tuyệt đối** thứ tự 73 cột của dataset. Quy ước đã đối chiếu
với dòng dữ liệu đúng do người dùng cung cấp:

| Cột | Quy tắc |
|---|---|
| `lat` / `long` | Làm tròn **4 chữ số** thập phân |
| `place_id` | Lấy từ `!19s` trong URL; không có thì **suy từ cặp FID hex** `!1s0x..:0x..` (base64url của protobuf — xem `place_id_from_fid`) |
| `price_min` / `price_max` | Suy từ **thực đơn**, giá menu luôn tính theo nghìn (`parse_menu_price`) |
| `price_per_person_avg` | Định dạng `100,000` (dấu phẩy ngăn nghìn) |
| `must_try_dishes` | Món trong mục "Đặc biệt" của menu, không có thì các món đắt nhất. Luôn ngăn bằng `, ` dù Gemini trả về kiểu gì |
| `menu` | Mỗi món **một mức giá duy nhất** — `"25 - 28"` → `"25"` (cận dưới). Ảnh menu **chỉ lấy từ mục "Thực đơn"** của Google Maps; quán không có mục đó thì cột này **để trống**, không lùi sang "Thực phẩm và đồ uống" (ảnh khách chụp, dán vào Gemini chỉ sinh menu bịa) |
| `open_time` / `close_time` | "Mở cửa cả ngày" → `0:00` / `23:59`. Ca gãy (`11:00–14:00, 17:00–21:00`) → mở ca đầu, đóng ca cuối. Xem `gmaps.parse_day_hours` |
| `name_en` | Chỉ nhận **tên tiếng Anh thật**. Tên Việt bỏ dấu ("Ca phe Hoa Moc Lan") **không phải** tên tiếng Anh → để trống (`english_name`) |
| `category_l1` | `FOOD` cho mọi POI đồ ăn. Nhãn ngành Google khớp `[category] non_food_markers` → `OTHER`, và dòng xuất ra là **stub CHỈ có `name` + `category_l1`**, mọi cột khác để trống (kể cả `status`/`labeled_by`/`last_updated`) |
| `category_l2` | Tự điền, luôn là **một trong 5 nhãn** ở `[category] l2_values`. Nhãn Gemini chỉ được nhận khi khớp danh sách (so khớp bỏ dấu, trả về cách viết chuẩn trong config); không khớp thì suy từ nhãn ngành Google → tên quán → `l2_fallback`. Giá trị lạ **không bao giờ** ra tới cột, nhưng vẫn còn nguyên trong `data.json` |
| `seating_capacity` | Luôn **để trống** — người gán nhãn tự điền |
| `confidence_level` | Luôn lấy `[dataset] confidence_level` (hiện là `Cao`), **bỏ qua** mức Gemini tự chấm |
| `old_address` | Địa chỉ trước sáp nhập 1/7/2025. Ưu tiên đọc phường cũ **có sẵn trong địa chỉ Google**; không có mới hỏi Gemini, và câu trả lời phải nằm trong `[nha_trang] old_wards` |
| `ward` | Tên phường **sau sáp nhập 2025** — tra `[ward_map]` trong settings; Google vẫn trả tên cũ. Địa chỉ gốc giữ ở `old_address` |
| `city` | Chuẩn hoá `Khánh Hòa` → `Khánh Hoà` (dataset viết `oà`) |
| `cover_image_url` / `gallery_urls` | Để **trống** — ảnh chỉ điền vào `raw_*` |
| `positive/negative_comments` | Mỗi bình luận là **một đoạn văn riêng biệt**, ngăn bởi **một** dòng mới, không bọc nháy kép — `csv.DictWriter` tự quote cả field theo RFC4180 vì nó chứa newline. Xuống dòng **bên trong** một bình luận gốc (review nhiều đoạn) bị gộp thành khoảng trắng — chỉ ranh giới giữa hai bình luận mới xuống dòng. **Tối đa 5** mỗi bên, cắt trần ngay tại tầng xuất (`quoted_comments`) vì bài không có nội dung bị bỏ qua. Ít hơn 5 là bình thường |

## Môi trường

- venv tại `.venv` (Python 3.12). Cài: `uv pip install -e .`
- Dùng **Chrome thật**, tool tự spawn detached với profile riêng
  `~/.vsf-chrome-profile` trên cổng CDP 9222 → không cần `playwright install`.
- Chrome của tool chạy với `--disable-extensions`: Playwright ném
  "Assertion error" rồi rớt kết nối CDP khi vấp service worker của extension.
- Cố định `--window-size=1600,1000`: Google Maps đổi bố cục theo bề rộng, cửa sổ
  hẹp thì mất tab và mất ảnh phụ.

## Cạm bẫy đã gặp (đừng vấp lại)

| Chỗ | Bẫy |
|---|---|
| Google Maps SPA | Chỉ nhận **click thật**. `element.click()` trong `page.evaluate()` im lặng không làm gì — luôn dùng `locator.click()`. |
| Ảnh gallery | Không phải `<img src>` mà là CSS `background-image` trong `a[data-photo-index]`, nạp lười theo cuộn. |
| Mục ảnh gallery | Nhãn nằm ở `aria-label` (nhà hàng lớn) **hoặc** innerText (quán nhỏ), lại render lười → phải đọc cả hai và chờ. |
| Ảnh phụ `img.DaSXdd` | Lẫn ảnh Street View và trùng ảnh đại diện → lọc cả hai. |
| Bảng giờ mở cửa | Mặc định thu gọn (1 nút). Click `div.OqCZI` để bung ra 7; click lúc đang mở thì đóng lại. |
| Nút mở gallery | Chỉ có ở tab *Tổng quan* — sau khi lấy review phải quay lại tab đó. |
| Lịch sử chat Gemini | Nạp sau ô nhập ~3s. Đo `response_count` sớm sẽ ra 0 rồi đọc nhầm lượt cũ. |
| Giới hạn đính kèm Gemini | Tối đa **10 ảnh**/lượt, dư bị bỏ lặng lẽ → `max_menu_images = 10`. |
| Thread Gemini trôi schema | Trả lời văn xuôi thay vì 26 trường → pipeline tự gửi `reformat_prompt`. Bình thường chỉ cần 1 lượt (`profile_prompt` one-shot); `fill_missing_prompt` chỉ còn là lưới an toàn cuối cùng, hiếm khi kích hoạt. |
| Card TikTok | `[data-e2e='search_top-item']` chỉ bọc thumbnail; caption/tác giả ở **thẻ cha** (`xpath=..`). |
| Ngày đăng TikTok | Giải mã từ video ID: `int(id) >> 32` = Unix timestamp. |
| Tên POI dài | TikTok không ra kết quả với `"... . Vn - Ms.Smile (…)"`. Thử tên đầy đủ trước, rồi tên rút gọn (`simplify`). |
| Gemini chèn trích dẫn | Tiêu đề nguồn ("Laodong.vn", "Khu du lịch Bửu Long -") xuất hiện thành dòng riêng, trông y hệt câu trả lời ngắn. Lọc theo hình dạng chuỗi **không đủ** — phải đối chiếu whitelist. |
| Bảng con trong TOML | `old_wards` từng lọt vào `[dataset]` khiến `settings()["old_wards"]` rỗng và whitelist bị vô hiệu **trong im lặng**. `[category]` cũng phải nằm RIÊNG ở cuối file vì có `[[category.l2_hints]]` bên trong. Kiểm tra bằng `settings()` sau khi thêm khoá mới. |
| Nhãn ngành Google | **Hai bố cục.** Quán ăn/cà phê/bảo tàng dùng `button.DkEaL`; **khách sạn KHÔNG có `DkEaL`** — nhãn là text thường `span.mgr77e` kèm dấu chấm giữa ở đầu (`"·Khách sạn 3 sao"`). Thiếu biến thể thứ hai là mất cổng chặn ở đúng ca cần nó nhất. `button[jsaction*='pane.wfvdle']` khớp 59–83 phần tử và trả về chip gợi ý — **đừng dùng**. |
| So khớp từ khoá | Khớp **chuỗi con** cho dương tính giả rất khó thấy: `"pub"` trong `"gastropub"`, `"bar"` trong `"barbecue"`, `"spa"` trong `"spaghetti"` (biến quán mì Ý thành dòng stub). Luôn dùng ranh giới từ — xem `schema._has_keyword`. |
| Nguồn suy `category_l2` | Nhãn ngành Google xét **riêng và trước** tên quán. Gộp hai nguồn vào một chuỗi thì thứ tự khai báo hint quyết định thay vì độ tin cậy của nguồn (đã gặp: "ZAVOD restaurant & gastropub" ra `Quán Bar`). |
| **Trùng tên giữa các tỉnh/trong cùng thành phố** | "Bánh Canh Ghẹ …" có ở cả Nha Trang lẫn Hà Nội; "Greek Cuisine" và "Greek Kitchen" trùng gần tên nhưng khác quán, khác địa chỉ, trong cùng Nha Trang. Truy vấn **luôn ghép `search_region`**, thêm `--address` thì ghép cả phần đường vào truy vấn (`search_query`). `step_maps` giờ **CHẶN HẲN** (raise, không chỉ warn) nếu `name_match`/`address_match` dưới ngưỡng — trước đây chỉ cảnh báo nên "Greek Cuisine" từng bị ghi "ok" với dữ liệu của "Greek Kitchen" (khớp đúng 0.5, sát ngưỡng cũ, lọt qua trong im lặng vì so sánh `<` không `<=`). |
| Tab chất đống | Nhận diện tab qua biến JS trên `window` là vô dụng — navigation xoá sạch. Nhận qua URL. `close_stray_tabs()` dọn tab trắng + tab trùng slot, nhưng **không đụng** tab lạ của người dùng. |
| Trang chi tiết video TikTok | **HTTP 403.** Không mở được `/@handle/video/<id>` → không có ảnh bìa, phụ đề, bình luận. Lưới video trang profile cũng hỏng ("Đã xảy ra lỗi"). Chỉ TRANG TÌM KIẾM là dùng được. Đây là lý do hướng VLM/OCR bị loại. |
| Ảnh trong card TikTok | `img.src` là **placeholder GIF 1×1**; mọi ảnh http trên trang chỉ là avatar 100×100. Nhưng **`img.alt` giữ caption ĐẦY ĐỦ** (phần tử caption hiển thị bị CSS cắt cụt) — đọc alt trước, thường có cả địa chỉ đường. |
| Khung hình video TikTok | Không bắt được. `<video>` có `crossOrigin="use-credentials"` mà CDN trả `access-control-allow-origin: null` → CORS trượt → `readyState` kẹt ở 0 vĩnh viễn. Không phải DRM (`ftypisom` hợp lệ), không phải CSP (`default-src` có `blob:`). Gọi `play()` thì **treo cả renderer**. |
| `search-card-user-unique-id` | Hiện **nickname**, KHÔNG phải handle. Muốn handle thì lấy từ `href` (`/@<handle>/video/<id>`). So nhầm ở đây từng dẫn tới kết luận sai rằng tài khoản chính chủ vắng mặt trong tab Videos. |
| Cuộn để lấy thêm kết quả TikTok | Vô ích: 24 → 24 sau 4 lần `scrollTo`. Mở rộng bể ứng viên phải bằng cách **đổi tab** (Top + Video), không phải cuộn sâu hơn. |
| Card tab Người dùng TikTok | Đi ngược từ `[data-e2e='follow-back']` lên cha là hỏng — walk-up chạm container chung nên 20 card gộp thành 1. Duyệt thẳng `a[href^="/@"]`, bỏ link chỉ có 1 dòng text. |
| idf dùng sai chỗ | idf của caption chỉ hợp để **phân biệt caption**, KHÔNG hợp để **so tên với handle**: chính chủ đăng cả 5 video thì tên quán có ở mọi caption, idf tụt về 0 và bộ lọc "từ đặc trưng" ném đi đúng cái tên cần khớp (đã gặp: "chớm brew&bloom" ra 0.0 dù cả 5 ứng viên đều của `@chớm`). |
| Xác minh Trang Facebook | `gmaps.address_match` lấy **đoạn trước dấu phẩy đầu tiên** làm tên đường, mà Google hay đặt **Plus code** ở đó (`65VV+G77, 19 Đ. Lê Thánh Tôn, ...`). Không lọc thì đem Plus code đi so → luôn 0 → Trang ĐÚNG bị loại trong im lặng. Dùng `facebook.street_segment()`. |
| Reels của Trang Facebook | **Đừng dùng `search/videos?q=<tên quán>`**: tìm theo từ khoá trả về video của bất kỳ ai nhắc tên đó, nên xác minh Trang xong cũng KHÔNG bảo đảm gì cho video (đã gặp: Trang "mo:sa coffee" xác minh đúng nhưng ra Reel của "Góc Của Mây"). Phải lấy từ tab video của chính Trang: `profile.php?id=<ref>&sk=videos`. |
| URL Facebook | Nhồi tham số dài **trông như dữ liệu cookie** → công cụ trích xuất có thể chặn output. Cắt query string trước khi log. NHƯNG link Trang là `profile.php?id=<id>` — id nằm TRONG query string, đừng cắt bừa. |
| `page.url` của Playwright | **Bị cũ** — không phản ánh `history.replaceState` của Google Maps. Luôn dùng `gmaps.current_url(page)` (`location.href`), nếu không mất sạch lat/long/place_id. |
