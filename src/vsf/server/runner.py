"""Chạy worker của lô trong thread nền và phát sự kiện cho giao diện.

Vì sao đúng MỘT lô tại một thời điểm, cưỡng chế ở đây:

* `config._OUTPUT_OVERRIDE` là biến global TOÀN TIẾN TRÌNH. Hai lô song song
  trong cùng tiến trình sẽ ghi đè thư mục output của nhau, và POI của lô này rơi
  vào thư mục của lô kia — hỏng âm thầm, rất khó lần ra.
* Sâu hơn: hai thread chat Gemini là URL cố định dùng chung. Song song là hai POI
  cùng gửi prompt vào một cuộc hội thoại.

Nên `start()` từ chối khi đã có lô đang chạy, thay vì xếp hàng chờ — người dùng
cần biết ngay là yêu cầu không được thực hiện.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from ..batch import store, worker


class Broker:
    """Phát sự kiện tới các client SSE đang mở.

    Mỗi client một hàng đợi CÓ GIỚI HẠN: một tab trình duyệt bị treo không được
    phép làm phình bộ nhớ vô hạn. Hàng đầy thì bỏ sự kiện cũ nhất — giao diện
    theo dõi tiến độ thà mất một dòng log còn hơn kéo sập tiến trình.
    """

    def __init__(self, maxsize: int = 500) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except queue.Empty:  # pragma: no cover - đua giữa các thread
                    pass


class BatchRunner:
    """Chủ sở hữu thread worker. Đúng một lô chạy tại một thời điểm."""

    def __init__(self) -> None:
        self.broker = Broker()
        self._thread: threading.Thread | None = None
        self._batch_id: int | None = None
        self._lock = threading.Lock()

    @property
    def running_batch(self) -> int | None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._batch_id
            return None

    def start(self, batch_id: int, *, resume: bool = True, limit: int | None = None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError(
                    f"Lô #{self._batch_id} đang chạy. Chờ xong hoặc tạm dừng trước đã — "
                    "hai lô song song sẽ giẫm lên nhau ở thư mục output và ở thread chat Gemini."
                )
            # Cờ dừng còn treo từ lần trước sẽ khiến worker thoát ngay vòng đầu.
            if store.batch_status(batch_id) in ("paused", "cancelled"):
                store.set_batch_status(batch_id, "idle")

            self._batch_id = batch_id
            self._thread = threading.Thread(
                target=self._run,
                args=(batch_id, resume, limit),
                name=f"vsf-batch-{batch_id}",
                daemon=True,
            )
            self._thread.start()

    def _run(self, batch_id: int, resume: bool, limit: int | None) -> None:
        try:
            worker.run_batch(
                batch_id, resume=resume, limit=limit, on_event=self.broker.publish
            )
        except Exception as exc:
            # Lỗi ngoài vòng lặp POI (mất kết nối CDP, Chrome bị đóng): worker đã
            # đánh dấu job hiện tại, ở đây chỉ cần cho giao diện biết lô đã chết.
            store.set_batch_status(batch_id, "idle")
            self.broker.publish(
                {"kind": "batch_error", "batch_id": batch_id, "error": str(exc)}
            )

    def pause(self, batch_id: int) -> None:
        """Dừng HỢP TÁC: worker đọc cờ giữa hai POI rồi tự thoát.

        Không giết thread: đang dở một lượt Gemini mà cắt là vứt lượt đó đi mà
        chẳng cứu được thời gian nào.
        """
        store.set_batch_status(batch_id, "paused")
        self.broker.publish({"kind": "batch_pausing", "batch_id": batch_id})

    def cancel(self, batch_id: int) -> None:
        store.set_batch_status(batch_id, "cancelled")
        self.broker.publish({"kind": "batch_cancelling", "batch_id": batch_id})


RUNNER = BatchRunner()
