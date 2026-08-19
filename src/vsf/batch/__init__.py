"""Chế độ chạy lô: hàng đợi, worker tuần tự, gộp xuất, dựng lại chỉ mục.

Nguyên tắc bất di bất dịch: **`data.json` vẫn là nguồn sự thật duy nhất cho dữ
liệu POI.** SQLite ở đây chỉ là tầng điều phối + chỉ mục để trả lời nhanh các câu
hỏi "POI nào đang chờ / hỏng / cần người xem lại" mà không phải mở 121 file.
Xoá `state/vsf.db` bất cứ lúc nào rồi chạy `vsf batch reindex` là dựng lại được
toàn bộ từ đĩa — không mất gì.
"""
