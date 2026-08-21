# Tool VSF Data

Tool gán nhãn & tăng cường dữ liệu POI. Nhận **tên một POI**, tự động thu thập
qua 6 bước và ghi ra:

- `output/<slug>/row.tsv` — **output chính thức**, đúng bộ cột của dataset.
- `output/<slug>/data.json` — bản ghi trung gian để checkpoint và tra cứu.

## Hai profile

Tool chạy **hai bộ dataset** trên cùng một codebase. Profile của một POI nằm ở
`POIRecord.profile`, được ghi vào `data.json`, nên `vsf export` và
`vsf batch reindex` đọc lại được mà không cần cờ.

| Profile | POI | Cột | Bước thứ 4 | `category_l1` | Config |
|---|---|---|---|---|---|
| `food` | đồ ăn | 73 | `menu` — dán ảnh thực đơn vào Gemini #2 | `FOOD` | `config/profile_food.toml` |
| `accom` | lưu trú | 72 | `rooms` — Gemini #2 tra bảng giá phòng trên web | `ACCOM` | `config/profile_accom.toml` |

**Bản ghi cũ không có khoá `profile` rơi về `food`** — 141 POI đã gán nhãn từ
trước vẫn xuất ra đúng 73 cột như cũ, không cần migration.

**Mọi thứ phụ thuộc dataset phải đi qua `vsf/profiles/`.** Cố ý KHÔNG có
`schema.COLUMNS` cấp module: một hằng số như vậy sẽ là bộ cột của FOOD, và mọi
chỗ lỡ dùng nó cho bản ghi ACCOM sẽ âm thầm cắt còn 73 cột sai tên thay vì báo
lỗi. Lấy cột bằng `profiles.get_profile(record.profile).COLUMNS`, lấy bước bằng
`profiles.steps_for(record)`.

Diff cột: ACCOM **bỏ** 11 cột món ăn (`cuisine_type`, `must_try_dishes`, `menu`,
`price_per_person_avg`, `seating_capacity`, `dietary_options`,
`reservation_required`, `dress_code`, `alcohol_served`, và
`cover_image_url`/`gallery_urls` vốn luôn để trống), **thêm** 10 cột phòng ốc
vào đúng chỗ khối cũ (vị trí 7–17). `view_type` có ở cả hai.

## Luồng nghiệp vụ

`STEPS` khác nhau theo profile, chỉ lệch đúng bước thứ tư:

- food: `["maps", "gemini1", "old_address", "menu", "tiktok", "facebook"]`
- accom: `["maps", "gemini1", "old_address", "rooms", "tiktok", "facebook"]`

| Bước | Nguồn | Lấy gì |
|---|---|---|
| `maps` | Google Maps | **Nhãn ngành** (→ `category_l1`/`category_l2`/`star_rating`), tên, địa chỉ, lat/long, place_id, SĐT, giờ mở/đóng, URL ảnh đại diện + 3 ảnh phụ, 5 review 4–5★, 5 review 1–2★, ảnh tab Thực đơn (**chỉ profile food**) |
| `gemini1` | Gemini chat #1 (`bac782da...`) | Prompt **one-shot** (`[gemini] profile_prompt`) → cả bộ trường mô tả POI + quy ước trong MỘT lượt (food 26 trường, accom 28), kèm **địa chỉ Google đã xác nhận** ở bước `maps` để không lấy nhầm quán trùng tên |
| `old_address` | Gemini chat #1 | Tên phường **trước sáp nhập 1/7/2025** → `old_address` |
| `menu` (food) | Gemini chat #2 (`d65843a9...`) | Dán ảnh thực đơn + `menu_prompt` → menu đã trích xuất |
| `rooms` (accom) | Gemini chat #2 (cùng thread) | `room_price_prompt` → bảng giá phòng JSON. **Không có ảnh**: Google Maps không có mục "Thực đơn" cho khách sạn, nguồn duy nhất là Gemini tự tra web |
| `tiktok` | TikTok | Hợp tab **Top + Video**, cộng tab **Người dùng** để tìm tài khoản chính chủ. Top 5 ứng viên kèm `score` + `score_breakdown` |
| `facebook` | Facebook | **Xác minh danh tính**: `search/pages` trả địa chỉ Trang → đối chiếu địa chỉ Google. Chỉ khi khớp mới lấy Reels |

**`maps` chạy TRƯỚC `gemini1` là cố ý.** Hai cổng chặn (lấy nhầm quán, sai nhóm
ngành) đều nằm ở `maps` và đều đặt ngay sau `basic_info` — trước khi cào
giờ/ảnh/đánh giá/thực đơn. Đặt sau thì mỗi POI bị loại vẫn đốt hết lượt Gemini
rồi mới vứt đi. Hệ quả: **`maps` hỏng là dừng cả chuỗi** (`_skip_reason`), vì
mọi bước sau đều phụ thuộc nó.

**Chiều của cổng phân loại ngược nhau giữa hai profile** (`[category].mode`):

- food dùng **danh sách đen** (`mode = "blacklist"`): vốn từ nhãn ngành đồ ăn
  của Google là MỞ (nhà hàng chay / quán ăn nhanh / tiệm bánh / quán hải sản…),
  không liệt kê hết được, nên chỉ liệt kê được cái KHÔNG phải.
- accom dùng **danh sách trắng** (`mode = "whitelist"`): vốn từ lưu trú thì ĐÓNG
  và nhỏ (khách sạn / nhà nghỉ / resort / homestay / hostel / villa / căn hộ
  dịch vụ). Ở đây blacklist mới là cái bất khả thi.
- Cả hai **fail-open khi nhãn rỗng**: đọc không ra nhãn là lỗi selector, không
  phải tín hiệu phân loại.

Mã cờ vẫn là `not_food` ở cả hai profile — nó đã nằm trong `data.json` và
`flags_json` của 141 POI cũ, đổi mã là hàng đợi triage mất sạch lịch sử. Chỉ
nhãn hiển thị đổi thành "Sai nhóm ngành".

## Quy tắc quan trọng

- **Selector nằm hết ở `config/selectors.toml`** — không hardcode selector trong
  code. UI Google/TikTok đổi liên tục; vá config chứ không sửa module.
  Dùng `sel()` / `sel_list()` trong `config.py`. `sel_list` cho phép khai báo
  nhiều selector ứng viên, thử lần lượt tới khi khớp.
- **Config tách 3 file.** `settings.toml` giữ phần DÙNG CHUNG (browser, batch,
  gmaps, tiktok, facebook, ward_map, nha_trang, và URL + timeout của Gemini);
  `profile_food.toml` / `profile_accom.toml` giữ phần phụ thuộc dataset
  (`[dataset]`, `[category]`, toàn bộ prompt). `profile_settings(name)` gộp
  **nông theo section**, file profile thắng. Tách file thay vì lồng
  `[profiles.food.*]` là cố ý: mỗi file giữ được bảng PHẲNG, tránh đúng cái bẫy
  bảng con lọt nhầm bảng khác đã ghi bên dưới. Gộp SÂU cũng sai — nó sẽ trộn
  `markers` của hai profile, mà một bên là danh sách trắng, một bên danh sách
  đen, hợp nhất lại thì cổng chặn vô nghĩa.
- **Cột có bộ giá trị đóng khai bằng `[category] <cột>_values`.** Mọi khoá
  kết thúc bằng `_values` tự thành một ô cùng tên trong prompt Gemini
  (`pipeline._vocab_clauses`) và là whitelist cho `schema.normalize_vocab` ở
  tầng xuất. Một nguồn sự thật, hai đầu cùng đổi — thêm cột thì chỉ sửa config.
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
.venv/bin/vsf run "Tên POI" --only maps      # maps | gemini1 | old_address | menu(food) / rooms(accom) | tiktok | facebook
.venv/bin/vsf run "Tên POI" --resume         # bỏ qua bước đã ok
.venv/bin/vsf run "Tên POI" --index 3 --out output_12/8   # đợt gán nhãn riêng
.venv/bin/vsf run "Tên POI" --address "223 Nguyễn Thiện Thuật"   # quán trùng tên -> neo địa chỉ
.venv/bin/vsf run "Tên POI" --profile accom  # POI lưu trú (72 cột); mặc định là food
.venv/bin/vsf run "Tên POI" --force-category # nhãn ngành Google gây hiểu nhầm -> bỏ qua cổng phân loại
                                             # (--force-food vẫn là bí danh của cờ này)
.venv/bin/vsf export "Tên POI"               # xuất lại row.tsv từ data.json
.venv/bin/vsf export "Tên POI" --tiktok 2    # đổi link TikTok đã chọn
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/rescore_tiktok.py --threshold   # chấm lại offline, dò ngưỡng
```

### Chạy lô + giao diện quản lý (v2)

```bash
.venv/bin/vsf batch reindex                  # nạp mọi output*/ đã có vào chỉ mục
.venv/bin/vsf batch add ds.csv --out output_19_8 --name "Đợt 19/8"
.venv/bin/vsf batch add ks.csv --out output_accom_1 --profile accom   # đợt lưu trú
.venv/bin/vsf batch run --batch 3            # chạy tuần tự, một Session cho cả lô
.venv/bin/vsf batch status                   # tiến độ các đợt
.venv/bin/vsf batch status --flag tiktok_below_threshold   # hàng đợi triage
.venv/bin/vsf batch retry --batch 3          # đưa job hỏng về hàng đợi
.venv/bin/vsf batch export --batch 3         # gộp row.tsv cả đợt
.venv/bin/vsf ui                             # giao diện tại http://127.0.0.1:8000
```

Giao diện cần cài thêm: `uv pip install -e ".[ui]"` rồi `cd ui && npm install && npm run build`.
Core CLI vẫn chỉ 3 dependency — FastAPI/uvicorn nằm ở nhóm tuỳ chọn `[ui]`.

Đầu vào `batch add` nhận ba dạng, tự nhận biết:

1. **Bảng không có tiêu đề** — `tên <TAB> địa chỉ <TAB> place_id`. Dạng dán thẳng
   ra được từ bảng tính, và là dạng nên dùng.
2. CSV có cột `name` (kèm được `address`, `place_id`, `index`, `force_food`,
   `only`, `profile`). `profile` ở dòng lẻ thắng cờ `--profile` của cả đợt.
3. Text thuần, mỗi dòng một tên.

**`place_id` là neo mạnh nhất.** Có nó thì `gmaps.open_place` mở THẲNG đúng địa
điểm (`/maps/place/?q=place_id:…`), bỏ qua hẳn khâu tìm kiếm — và cùng với nó là
cả lớp lỗi "Google trả nhầm quán trùng tên". Khi đó `_reject_wrong_place` **không
chặn**: cổng đó tồn tại để đoán xem Google có trả đúng quán không, mà mở bằng
place_id là đã biết chắc. Vẫn chặn thì tên người dùng gõ khác tên Google đăng ký
(chuyện thường: "Bún Cá Sứa NhaTrang") sẽ loại oan đúng POI đã bỏ công tra id.
Tên lệch nhiều vẫn được `warn` để rà lại.

`place_id` được bóc theo **hình dạng chuỗi, không theo vị trí cột** — địa chỉ đầy
dấu phẩy nên số ô thay đổi tuỳ nguồn dán. Yêu cầu có cả chữ hoa lẫn chữ thường,
nếu không một tên viết liền không dấu ("BUNBOTUNGHOANGCHINHANH2") cũng lọt và bị
cắt khỏi tên. Ngăn ô bằng tab **hoặc từ 2 dấu cách trở lên** — một dấu cách đơn
không tính, vì tên quán và địa chỉ đều đầy dấu cách đơn.

`address_hint` và `place_id` nằm trong `store._STICKY`: giá trị rỗng **không bao
giờ** ghi đè giá trị đã có. Thiếu chốt này thì chạy `vsf batch reindex` một lần
(reindex đọc từ đĩa, không biết place_id) là bay sạch id vừa nạp — hỏng trong im
lặng, chỉ lộ ra ở lần chạy sau khi Google trả nhầm quán.

## Chế độ lô & giao diện (`batch/`, `server/`, `ui/`)

**`data.json` vẫn là nguồn sự thật duy nhất.** SQLite ở `state/vsf.db` chỉ là
tầng **điều phối + chỉ mục**: xoá lúc nào cũng được, `vsf batch reindex` dựng lại
toàn bộ từ đĩa. Đừng bao giờ để một dữ kiện POI chỉ tồn tại trong DB.

| Chỗ | Vai trò |
|---|---|
| `pipeline.run_record()` | Lõi chạy MỘT POI trên Session **đã mở sẵn** + `on_event`. `run()` chỉ là wrapper mở Session — `vsf run` không đổi hành vi |
| `errors.py` | `WrongPlaceError` (kế thừa `RuntimeError` để không phá code cũ) + hằng số `FLAG_*` |
| `POIRecord.flags` | Cờ triage máy đọc được, gom theo bước **y hệt `warnings`** để chạy lại bước là xoá đúng cờ cũ. `warnings` để người đọc, `flags` để lọc |
| `POIRecord.step_runs` | Thời lượng + `error_code` + **traceback** mỗi bước (trước đây traceback bị vứt) |
| `POIRecord.overrides` | Sửa tay theo tên cột, `build_row()` áp **CUỐI CÙNG** → chạy lại bước không xoá chỗ đã sửa |
| `PATCH /jobs/{id}/row` | `null` cho một cột = **xoá** override của cột đó; `""` = **ép cột rỗng**. Gộp hai thứ lại thì nút "về mặc định" của một cột chỉ khoá được cột ở giá trị trống chứ không trả nó về cho pipeline tính |
| `errors.flags_from_warnings()` | Bắc cầu cờ từ câu cảnh báo tiếng Việt của 141 POI cũ. Chỉ dùng khi `flags` rỗng, **không** ghi ngược vào data.json |
| `batch/outcome.py` | `derive_status()` — worker và reindex **phải** dùng chung, lệch nhau là reindex âm thầm đổi trạng thái vừa chạy xong |
| `batch.profile` / `job.profile` | Cột SQLite, mặc định `'food'`, có trong `_MIGRATIONS`. `job.profile` nằm trong `_STICKY` (giá trị rỗng không ghi đè) vì nó có default NON-rỗng — thiếu chốt này thì một lần upsert quên truyền là cả đợt lưu trú quay về bộ 73 cột |
| `batch/export.py` | Đọc `profile` từ `data.json` cạnh `row.tsv` để chọn bộ cột. Thư mục **trộn hai profile** → `ValueError`, không cắt cụt cột trong im lặng |
| `server/runner.py` | Đúng MỘT lô chạy tại một thời điểm; `start()` ném 409 nếu đã có lô đang chạy |

Quy tắc riêng:

- **Mọi field mới của `POIRecord` bắt buộc có default.** Nạp bằng `cls(**data)`
  nên thiếu default là vỡ toàn bộ bản ghi cũ.
- **Không đổi kiểu `steps: dict[str, str]`** — `_skip_reason`, `merge_rows.py`,
  `rescore_tiktok.py` đều so `== "ok"`.
- **Bước chưa từng chạy ≠ chưa xong.** `facebook` vắng mặt ở 139 bản ghi cũ; coi
  đó là "còn dang dở" sẽ đẩy cả trăm POI đã xong ngược về hàng đợi.
  `derive_status` chỉ xét bước CÓ trong `record.steps`, phần thiếu báo riêng qua
  `missing_steps()`.
- **`wrong_place` / `not_food` → `needs_review`, KHÔNG retry.** Chạy lại chỉ đốt
  thêm một vòng Gemini để nhận đúng kết luận cũ.
- **`derive_status` dò bước hỏng trên `record.steps`, không trên `STEPS`.** Bước
  hỏng nằm ngoài danh sách hiện tại (đổi profile, đổi tên bước) vẫn phải lộ ra là
  `failed` chứ không biến mất thành `done`.
- **`reindex` được phép sửa `batch.profile`, `get_or_create_batch` thì không.**
  Reindex đọc từ data.json tức là từ nguồn sự thật; còn `batch add` lần hai vào
  cùng thư mục là thêm POI, không phải đổi bộ cột của đợt đang chạy dở.
- **Giao diện KHÔNG giữ danh sách cột/bước của riêng nó.** Lấy từ
  `GET /api/jobs/{id}` (theo profile bản ghi) hoặc `GET /api/config`
  (`profiles.<tên>`). `JobTable` từng chép cứng 6 tên bước: mọi job lưu trú hiện
  một ô `menu` không bao giờ chạy và thiếu hẳn ô `rooms`.
- Tạm dừng/huỷ là **cờ hợp tác**, đọc giữa hai POI — không cắt giữa một lượt Gemini.
- Chạy lô nên đặt `[browser] bring_to_front = false`, nếu không cửa sổ giật suốt đêm.

## Tầng xuất dữ liệu (`schema.py` + `profiles/`)

`schema.py` giữ phần **không phụ thuộc dataset** (định dạng số, tách địa chỉ,
chuẩn hoá phường, chọn video, áp override, `classify_l1`/`normalize_l2` nhận
`cfg` của profile). `COLUMNS` và `build_row` thật nằm ở `profiles/food.py` /
`profiles/accom.py`; `schema.build_row` chỉ là **bộ điều phối** theo
`record.profile`, giữ nguyên chữ ký cũ để `export_row` và `server/api` không đổi.

`COLUMNS` của mỗi profile phải khớp **tuyệt đối** thứ tự cột của dataset tương
ứng (food 73, accom 72). Quy ước đã đối chiếu với dòng dữ liệu đúng do người dùng
cung cấp:

| Cột | Quy tắc |
|---|---|
| `lat` / `long` | Làm tròn **4 chữ số** thập phân |
| `place_id` | Lấy từ `!19s` trong URL; không có thì **suy từ cặp FID hex** `!1s0x..:0x..` (base64url của protobuf — xem `place_id_from_fid`) |
| `price_min` / `price_max` | Suy từ **bảng giá** — `menu` với food, `room_price` với accom. Giá luôn tính theo NGHÌN (`menu_prices` nhân 1000 khi đọc lại, nên prompt phải ép Gemini trả số nghìn; trả đầy đủ VNĐ là sai gấp 1000 lần) |
| `price_level` | Ngưỡng ở `[category] price_levels` CỦA PROFILE — food `[150k, 500k]` cho một BỮA ĂN, accom `[700k, 2tr]` cho một ĐÊM. Dùng chung thang giá thì mọi khách sạn đều thành `luxury`. Accom xét theo phòng RẺ NHẤT (`price_min`), đó là mức khách gặp trước |
| `price_per_person_avg` | Định dạng `100,000` (dấu phẩy ngăn nghìn) |
| `must_try_dishes` | Món trong mục "Đặc biệt" của menu, không có thì các món đắt nhất. Luôn ngăn bằng `, ` dù Gemini trả về kiểu gì |
| `menu` | Mỗi món **một mức giá duy nhất** — `"25 - 28"` → `"25"` (cận dưới). Ảnh menu **chỉ lấy từ mục "Thực đơn"** của Google Maps; quán không có mục đó thì cột này **để trống**, không lùi sang "Thực phẩm và đồ uống" (ảnh khách chụp, dán vào Gemini chỉ sinh menu bịa) |
| `open_time` / `close_time` | "Mở cửa cả ngày" → `0:00` / `23:59`. Ca gãy (`11:00–14:00, 17:00–21:00`) → mở ca đầu, đóng ca cuối. Xem `gmaps.parse_day_hours` |
| `name_en` | Chỉ nhận **tên tiếng Anh thật**. Tên Việt bỏ dấu ("Ca phe Hoa Moc Lan") **không phải** tên tiếng Anh → để trống (`english_name`) |
| `category_l1` | `[category] l1_default` của profile (`FOOD` / `ACCOM`). Nhãn ngành Google không đúng nhóm (theo `markers` + `mode`) → `OTHER`, và dòng xuất ra là **stub CHỈ có `name` + `category_l1`**, mọi cột khác để trống (kể cả `status`/`labeled_by`/`last_updated`) |
| `category_l2` | Tự điền, luôn là **một trong 5 nhãn** ở `[category] l2_values` của profile (food: Nhà hàng / Quán ăn / Quán cà phê / Quán Bar / Ăn vỉa hè; accom: Resort / Khách sạn / Villa / Homestay / Nhà nghỉ). Nhãn Gemini chỉ được nhận khi khớp danh sách (so khớp bỏ dấu, trả về cách viết chuẩn trong config); không khớp thì suy từ nhãn ngành Google → tên quán → `l2_fallback`. Giá trị lạ **không bao giờ** ra tới cột, nhưng vẫn còn nguyên trong `data.json`. Hint xét **theo thứ tự, khớp trước thắng** — accom để `Resort` trước `Khách sạn` để "Khách sạn & Resort ABC" về nhóm resort |
| `tags` / `suitable_for` / `not_suitable_for` / `view_type` (accom) | **Bộ giá trị ĐÓNG** do người gán nhãn chốt, khai ở `[category] tags_values` / `suitable_for_values` / `not_suitable_for_values` / `view_type_values`. Cùng cơ chế `matched_intents`: `schema.normalize_vocab` quét nhãn hợp lệ RA KHỎI chuỗi Gemini trả về (nhãn dài xét trước rồi xoá phần đã khớp, so khớp bỏ dấu + ranh giới từ), nên miễn nhiễm với mọi kiểu ngăn cách — phẩy, chấm phẩy, gạch chéo. Nhãn Gemini tự nghĩ **không bao giờ** ra tới cột, vẫn còn nguyên trong `data.json` |
| `seating_capacity` | Luôn **để trống** — người gán nhãn tự điền |
| `confidence_level` | Luôn lấy `[dataset] confidence_level` (hiện là `Cao`), **bỏ qua** mức Gemini tự chấm |
| `old_address` | Địa chỉ trước sáp nhập 1/7/2025. Ưu tiên đọc phường cũ **có sẵn trong địa chỉ Google**; không có mới hỏi Gemini, và câu trả lời phải nằm trong `[nha_trang] old_wards` |
| `ward` | Tên phường **sau sáp nhập 2025** — tra `[ward_map]` trong settings; Google vẫn trả tên cũ. Địa chỉ gốc giữ ở `old_address` |
| `city` | Chuẩn hoá `Khánh Hòa` → `Khánh Hoà` (dataset viết `oà`) |
| `cover_image_url` / `gallery_urls` | (chỉ food) Để **trống** — ảnh chỉ điền vào `raw_*`. Dataset accom bỏ hẳn hai cột này |
| `star_rating` (accom) | Đọc từ **nhãn ngành Google** (`"·Khách sạn 4 sao"` → `"4 sao"`), Gemini chỉ là dự phòng — nhãn Google lấy từ hồ sơ cơ sở lưu trú chứ không phải suy đoán. Homestay/villa không xếp hạng sao thì **để trống** |
| `room_price` (accom) | JSON `[{loai_phong, ten, gia}]`, `gia` theo NGHÌN đồng, mỗi phòng **một mức giá duy nhất** (`"900 - 1200"` → `"900"`). Nguồn là Gemini tra web, KHÔNG phải ảnh — Google Maps không có mục "Thực đơn" cho khách sạn |
| `check_in_time` / `check_out_time` (accom) | Giờ nhận/trả phòng, do Gemini trả. **Khác** `open_time`/`close_time` — hai cột đó là giờ mở cửa toà nhà (lễ tân), vẫn cào từ Google Maps và thường ra `0:00`/`23:59` |
| `raw_cover_image_url` / `raw_gallery_urls` | Bể ứng viên là **10 ảnh đầu mục "Tất cả"** (`gallery_candidates`, `[gmaps] gallery_candidate_count`); cột chỉ nhận **3** (`GALLERY_URLS_COUNT`). Ảnh **đầu tiên** của mục "Tất cả" CHÍNH LÀ ảnh đại diện → bị loại khỏi ảnh phụ, nên mặc định là ứng viên **#1–#3**. Tick khác đi ở tab **Ảnh** thì lựa chọn vào `overrides["raw_gallery_urls"]` (áp cuối cùng, cào lại `maps` không xoá). Bản ghi cũ chưa có bể ứng viên: vá riêng bằng `vsf photos`, đừng chạy lại cả bước `maps` |
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
| Bảng con trong TOML | `old_wards` từng lọt vào `[dataset]` khiến `settings()["old_wards"]` rỗng và whitelist bị vô hiệu **trong im lặng**. `[category]` cũng phải nằm RIÊNG ở cuối file vì có `[[category.l2_hints]]` bên trong. Kiểm tra bằng `profile_settings("food")` / `("accom")` sau khi thêm khoá mới. |
| Nhãn ngành Google trong `non_food_markers` | Danh sách đen của profile food mở đầu bằng đúng `"khách sạn", "nhà nghỉ", "resort", "homestay", "villa", "hostel"`. Chạy POI lưu trú bằng profile food thì **100% bị cổng chặn**, gắn cờ `not_food`, và `derive_status` đẩy thẳng vào `needs_review` — không POI nào ra được dòng dữ liệu. Nhớ `--profile accom`. |
| `schema.COLUMNS` cấp module | Đã BỎ hẳn. Một hằng số như vậy luôn là bộ cột của một profile; dùng nhầm cho profile kia thì `{col: row.get(col, "")}` cắt cụt/đổi tên cột **không báo lỗi**. ImportError ồn ào còn hơn file TSV lệch cột. |
| `price_level_for` | Bắt truyền ngưỡng tường minh, không có default. Thang giá một bữa ăn (150k/500k) áp cho một đêm khách sạn thì mọi POI đều `luxury` — và không ai nhìn cột đó mà nhận ra. |
| Thư mục output trộn hai profile | `batch export` ném `ValueError` chứ không gộp. Hai bộ cột khác nhau không có file TSV chung; lấy bộ này áp cho bộ kia là mất dữ liệu trong im lặng. Một `out_dir` = một đợt = một profile. |
| Nút sắp xếp đánh giá | Trang **khách sạn có HAI** `button.HQzyZ`: nút đầu lọc NGUỒN (Tất cả / Google / Tripadvisor — menu 3 mục), nút sau mới là sắp xếp. Quán ăn chỉ có một. Lấy `.first` là mở nhầm menu nguồn rồi chờ mục thứ 4 vĩnh viễn → Timeout, hỏng cả bước `maps`. Chọn theo NHÃN (`[gmaps] sort_option_labels`), đừng theo vị trí. |
| Số sao trong thẻ đánh giá | Trang khách sạn gộp nhiều nguồn và hiện điểm dạng **text `"5/5"`**, KHÔNG có `span[role='img'][aria-label*='sao']`. Không đọc được sao thì thẻ bị loại và **cả hai cột bình luận rỗng trong im lặng** dù quán có 867 đánh giá. `_parse_reviews` có nhánh lùi đọc `N/5` từ text. |
| Giờ mở cửa khách sạn | Trang khách sạn **không có bảng giờ 7 ngày** → `by_day` rỗng, `open_time`/`close_time` để trống kèm cờ `hours_incomplete`. Cố ý không mặc định `0:00`/`23:59`: lễ tân 24/7 là phổ biến nhưng không phải luôn đúng với homestay/nhà nghỉ. |
| Tên khách sạn có đuôi địa danh | `name_match` so từng TỪ, mà tên Google đăng ký thường ngắn hơn tên marketing ("Lucky Sun Hotel" vs "Lucky Sun Hotel Nha Trang Beach" → 50%, dưới ngưỡng 0.6 → chặn). Với POI lưu trú nên **luôn nạp kèm `place_id`**, nó vô hiệu cổng này. |
| Thread Gemini theo profile | Mỗi profile có thể khai `[gemini] profile_chat_url`/`menu_chat_url` riêng; `browser.gemini_slots()` cấp **slot tab riêng cho từng thread**. Dùng chung một slot cho hai thread thì `open_chat` thấy tab đã ở đúng tiền tố `gemini.google.com` rồi bỏ qua điều hướng, và **prompt bay sang nhầm thread**. |
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
| `vsf ui` chạy nền khi sửa code | **Không có `--reload`**: tiến trình giữ nguyên module đã import lúc khởi động, trong khi `ui/dist` lại đọc từ đĩa mỗi request. Nên giao diện thì mới mà `build_row` vẫn là bản cũ — đã gặp: tab Ảnh hiện đúng bể 10 ảnh nhưng tick sẵn ảnh lấy từ `photos.secondary` (logic tiền-`gallery_candidates`), trông y hệt một bug chọn sai. Sửa `.py` xong là **khởi động lại server**, và kiểm bằng API chứ đừng kiểm bằng mắt trên trang. |
