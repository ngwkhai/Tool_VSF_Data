---
name: poi-recon
description: Dò lại selector cho tool VSF Data khi Google Maps / Gemini / TikTok đổi giao diện và một bước của `vsf run` bắt đầu fail. Dùng khi thấy lỗi kiểu "không tìm thấy", "Timeout waiting for selector", trả về 0 phần tử, hoặc trường nào đó bỗng rỗng trong data.json.
---

# Dò lại selector khi UI đổi

Tool này scrape 3 site không có API ổn định. Selector **sẽ** vỡ. Quy trình dưới
đây đưa thời gian sửa từ "viết lại module" xuống "vá vài dòng config".

## Nguyên tắc bất di bất dịch

1. **Chỉ sửa `config/selectors.toml`.** Nếu thấy mình đang sửa file trong
   `src/vsf/sites/`, dừng lại — trừ khi bản thân *luồng thao tác* đổi (ví dụ
   Google thêm một bước click mới), chứ không phải chỉ đổi tên class.
2. **Google Maps chỉ nhận click thật.** Luôn dùng `locator.click()` của
   Playwright. `element.click()` trong `page.evaluate()` **không ăn** — đã kiểm
   chứng, nó im lặng không làm gì.
3. **Đừng tin class băm ngẫu nhiên.** TikTok đổi tên class mỗi bản build. Ưu
   tiên `data-e2e`, `role`, `aria-label`. Cần đi lên thẻ cha thì dùng
   `locator("xpath=..")` chứ đừng bắt theo class.
4. **Kích thước cửa sổ ảnh hưởng bố cục Google Maps.** Cửa sổ hẹp thì mất tab và
   mất ảnh phụ. Tool cố định `--window-size=1600,1000` trong `browser.py` —
   đừng recon ở cửa sổ khác kích thước rồi kết luận sai.

## Quy trình

### 1. Tái hiện lỗi, xác định bước hỏng

```bash
.venv/bin/vsf run "Bánh Canh Trần Văn Ơn" --only maps    # gemini1 | maps | menu | tiktok
```

Đọc `output/<slug>/data.json`, xem `steps` và `warnings` để biết chính xác bước nào.

### 2. Chạy script recon

```bash
.venv/bin/python scripts/recon.py gmaps  "Bánh Canh Trần Văn Ơn"
.venv/bin/python scripts/recon.py tiktok "Bánh Canh Trần Văn Ơn"
```

Script in ra số phần tử khớp của từng selector đang dùng. `n=0` chính là selector
đã vỡ.

### 3. Tìm selector mới

Thêm ứng viên vào dict trong `scripts/recon.py` rồi chạy lại. Khi cần soi tay,
mở cửa sổ Chrome của tool (đang chạy sẵn ở cổng 9222) và dùng DevTools.

Với Gemini, dò nhanh bằng JS trong DevTools console:

```js
[...document.querySelectorAll('input-container button')]
  .map(b => b.getAttribute('aria-label'))
```

Lưu ý: **nút gửi của Gemini chỉ tồn tại khi ô nhập đã có text** — gõ vài chữ vào
rồi mới đi tìm nó.

### 4. Vá config và xác minh

Sửa `config/selectors.toml`, cập nhật comment `# [verified] ...` và dòng ghi ngày
recon ở đầu file. Rồi:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/vsf run "Bánh Canh Trần Văn Ơn" --only <bước vừa sửa>
```

Sửa xong phải **chạy thật** và xem `data.json`, không kết luận từ việc selector
đếm ra khác 0.

## Những chỗ đã từng vỡ / dễ vỡ

| Chỗ | Bẫy |
|---|---|
| Ảnh gallery Google Maps | **Không phải `<img src>`** mà là CSS `background-image` trên `div[role='img']` trong `a[data-photo-index]`, lại nạp lười theo cuộn. |
| Ảnh phụ `img.DaSXdd` | Lẫn ảnh Street View (`googleapis.com/v1/thumbnail`) và trùng cả ảnh đại diện → phải lọc cả hai. |
| Bảng giờ mở cửa | Mặc định thu gọn, chỉ có 1 nút. Click `div.OqCZI` để bung ra 7 nút. Click lúc đang mở thì nó đóng lại → phải kiểm tra số nút trước. |
| Nút sắp xếp review | Nhãn là lựa chọn hiện tại (`"Phù hợp nhất"`), **không** phải chữ "Sắp xếp". Class `HQzyZ`. |
| Mục ảnh "Thực đơn" | Nhiều quán nhỏ **không có**. Xem `MENU_CATEGORY_PREFERENCE` trong `gmaps.py` để chỉnh chuỗi fallback. |
| Nút mở gallery ảnh | Chỉ có ở tab *Tổng quan*. Sau khi lấy review phải quay lại tab đó trước. |
| Card TikTok | `[data-e2e='search_top-item']` chỉ bọc thumbnail; caption và tác giả nằm ở **thẻ cha**. |
| Kết quả TikTok | Nạp chậm hơn 7 giây. Phải `wait_for_selector`, đừng chờ cứng. |
