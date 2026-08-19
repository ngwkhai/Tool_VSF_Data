import { useCallback, useEffect, useRef, useState } from "react";
import type { WorkerEvent } from "./types";

/** Tải dữ liệu kèm trạng thái chờ/lỗi và một hàm `reload()` để gọi lại. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    try {
      setError(null);
      setData(await fnRef.current());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fnRef
      .current()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/**
 * Một kết nối SSE dùng chung cho cả ứng dụng.
 *
 * Mỗi trang tự mở EventSource riêng sẽ tạo ra nhiều kết nối tới cùng một luồng,
 * và mỗi lần chuyển trang lại đứt/nối lại — vừa tốn vừa làm mất sự kiện đúng lúc
 * đang cần theo dõi nhất.
 */
const listeners = new Set<(e: WorkerEvent) => void>();
let source: EventSource | null = null;

function ensureSource() {
  if (source) return;
  source = new EventSource("/api/events");
  source.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as WorkerEvent;
      listeners.forEach((fn) => fn(event));
    } catch {
      /* dòng giữ nhịp, không phải sự kiện */
    }
  };
  // EventSource tự kết nối lại khi đứt; không cần xử lý onerror.
}

export function useWorkerEvents(onEvent: (e: WorkerEvent) => void) {
  const ref = useRef(onEvent);
  ref.current = onEvent;

  useEffect(() => {
    ensureSource();
    const fn = (e: WorkerEvent) => ref.current(e);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);
}

/** Gom sự kiện thành nhật ký cuộn, giữ tối đa `keep` dòng gần nhất. */
export function useEventLog(keep = 200) {
  const [log, setLog] = useState<WorkerEvent[]>([]);
  useWorkerEvents((e) => setLog((prev) => [...prev, e].slice(-keep)));
  return log;
}
