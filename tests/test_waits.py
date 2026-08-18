"""Test cơ chế chờ — chạy được không cần browser."""

import pytest

from vsf.waits import wait_stable, wait_until


def test_wait_stable_returns_value_once_it_stops_changing():
    seq = iter(["a", "ab", "abc", "abc", "abc", "abc", "abc", "abc"])
    last = ["abc"]

    def read():
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]

    assert wait_stable(read, stable_seconds=0.3, timeout=5, poll=0.1) == "abc"


def test_wait_stable_keeps_waiting_while_value_still_changes():
    # Giả lập Gemini stream: đọc sớm sẽ ra câu trả lời cụt.
    chunks = ["tags:", "tags: a", "tags: a, b", "tags: a, b, c"]
    state = {"i": 0}

    def read():
        value = chunks[min(state["i"], len(chunks) - 1)]
        state["i"] += 1
        return value

    assert wait_stable(read, stable_seconds=0.25, timeout=5, poll=0.05) == chunks[-1]


def test_wait_stable_times_out_if_value_never_settles():
    state = {"n": 0}

    def read():
        state["n"] += 1
        return state["n"]

    with pytest.raises(TimeoutError):
        wait_stable(read, stable_seconds=0.5, timeout=1.0, poll=0.05)


def test_wait_stable_treats_sentinel_like_any_other_value():
    # gemini.read() trả sentinel khi chưa đọc được. Nó phải "ổn định" được để
    # ask() phát hiện và báo lỗi rõ ràng, thay vì ghi nhận kết quả rỗng.
    sentinel = "\x00__vsf_pending__"
    assert wait_stable(lambda: sentinel, stable_seconds=0.2, timeout=2, poll=0.05) is sentinel


def test_wait_until_passes_and_times_out():
    state = {"n": 0}

    def ready():
        state["n"] += 1
        return state["n"] > 3

    wait_until(ready, timeout=2, poll=0.05)

    with pytest.raises(TimeoutError):
        wait_until(lambda: False, timeout=0.5, poll=0.1, what="điều không bao giờ xảy ra")
