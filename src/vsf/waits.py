"""Chờ đợi có điều kiện — không dùng sleep cố định ở bất cứ đâu trong tool."""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def human_delay(low: float = 0.4, high: float = 1.2) -> None:
    """Nghỉ ngắn ngẫu nhiên giữa các thao tác cho giống người dùng thật."""
    time.sleep(random.uniform(low, high))


def wait_until(
    predicate: Callable[[], bool],
    timeout: float,
    poll: float = 0.5,
    what: str = "điều kiện",
) -> None:
    """Chờ tới khi predicate trả về True, hoặc ném TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(poll)
    raise TimeoutError(f"Quá {timeout:.0f}s mà {what} vẫn chưa thoả mãn")


def wait_stable(
    read: Callable[[], T],
    stable_seconds: float,
    timeout: float,
    poll: float = 0.5,
    what: str = "giá trị",
) -> T:
    """Chờ tới khi ``read()`` trả về cùng một giá trị suốt ``stable_seconds``.

    Đây là cách nhận biết Gemini đã stream xong: text ngừng thay đổi.
    Trả về giá trị đã ổn định.
    """
    deadline = time.monotonic() + timeout
    last = read()
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        time.sleep(poll)
        current = read()
        if current != last:
            last = current
            stable_since = time.monotonic()
            continue
        if time.monotonic() - stable_since >= stable_seconds:
            return last

    raise TimeoutError(f"Quá {timeout:.0f}s mà {what} vẫn chưa ổn định")
