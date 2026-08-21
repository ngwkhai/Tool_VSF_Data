import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AppConfig, WorkerEvent } from "./types";

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

/**
 * Cấu hình profile, tải MỘT lần cho cả ứng dụng.
 *
 * Danh sách bước và danh sách cột khác nhau giữa hai profile, nên client không
 * được giữ bản sao của riêng nó — trước đây `JobTable` chép cứng 6 tên bước và
 * mọi job lưu trú hiện sai ô `menu` trong khi thiếu hẳn `rooms`. Đây là nguồn
 * duy nhất, và nó đến từ server.
 */
let configPromise: Promise<AppConfig> | null = null;

export function useConfig(): AppConfig | null {
  const [config, setConfig] = useState<AppConfig | null>(null);
  useEffect(() => {
    let alive = true;
    configPromise ??= api.config();
    configPromise
      .then((c) => alive && setConfig(c))
      .catch(() => {
        // Cấu hình hỏng không được làm trắng cả trang: nơi gọi tự lùi về thứ tự
        // bước đọc được từ chính bản ghi.
        configPromise = null;
      });
    return () => {
      alive = false;
    };
  }, []);
  return config;
}

/** Thứ tự bước của một profile; chưa tải xong thì trả null để nơi gọi tự lùi. */
export function useStepOrder(profile: string | undefined): string[] | null {
  const config = useConfig();
  if (!config) return null;
  return config.profiles[profile ?? config.default_profile]?.steps ?? null;
}
