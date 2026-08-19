import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { useEventLog, useLoad, useWorkerEvents } from "../hooks";
import { JobTable } from "../components/JobTable";
import { Button, ErrorNote, Empty, LinkButton, Loading, Panel } from "../components/ui";
import type { WorkerEvent } from "../types";

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "", label: "Tất cả" },
  { key: "queued", label: "Chờ" },
  { key: "done", label: "Xong" },
  { key: "failed", label: "Hỏng" },
  { key: "needs_review", label: "Cần xem lại" },
];

/** Nhật ký chạy trực tiếp. Chỉ hiện mốc đáng đọc, không đổ nguyên luồng. */
function LiveLog({ log }: { log: WorkerEvent[] }) {
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
  }, [log.length]);

  const lines = log.filter((e) =>
    ["job_start", "step_ok", "step_failed", "step_skipped", "job_end", "batch_start",
     "batch_end", "batch_stopped", "batch_error", "job_retry"].includes(e.kind),
  );

  if (!lines.length) {
    return (
      <p className="text-ink-faint text-[14px] py-8 text-center">
        Chưa có sự kiện — bấm Chạy để bắt đầu.
      </p>
    );
  }

  const tone: Record<string, string> = {
    step_ok: "text-good-lit",
    step_failed: "text-bad-lit",
    step_skipped: "text-ink-faint",
    job_start: "text-brand-lit",
    job_end: "text-ink",
    job_retry: "text-warn-lit",
    batch_error: "text-bad-lit",
  };

  return (
    <div ref={boxRef} className="h-72 overflow-y-auto font-mono text-[13px] leading-relaxed">
      {lines.map((e, i) => (
        // `anim-fade` chỉ chạy lúc gắn vào DOM, nên dòng mới trượt vào còn dòng
        // cũ đứng yên — không phải cả khung nháy lại mỗi lần có sự kiện.
        <div
          key={i}
          className={`flex gap-2.5 py-0.5 anim-fade ${tone[e.kind] ?? "text-ink-dim"}`}
        >
          <span className="text-ink-faint shrink-0">{(e.ts ?? "").slice(11, 19)}</span>
          <span className="shrink-0 w-28 truncate">{e.kind}</span>
          <span className="truncate">
            {e.poi ?? ""}
            {e.step ? ` · ${e.step}` : ""}
            {e.reason ? ` — ${e.reason}` : ""}
            {e.error ? ` — ${e.error}` : ""}
            {e.status ? ` → ${e.status}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

export function BatchDetail() {
  const { id } = useParams();
  const batchId = Number(id);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const jobs = useLoad(() => api.jobs(batchId, { status: status || undefined }), [batchId, status]);
  const batches = useLoad(() => api.batches(), [batchId]);
  const stats = useLoad(() => api.stats(), []);
  const log = useEventLog();

  // Worker chạy xong một POI thì bảng phải tự cập nhật — người dùng mở trang
  // này chính là để KHÔNG phải bấm nạp lại.
  useWorkerEvents((e) => {
    if (e.kind === "job_end" || e.kind === "batch_end" || e.kind === "batch_stopped") {
      jobs.reload();
      batches.reload();
    }
  });

  const batch = batches.data?.batches.find((b) => b.id === batchId);
  const running = batches.data?.running === batchId;

  const labels = useMemo(() => {
    const map: Record<string, { label: string; severity: "block" | "warn" }> = {};
    stats.data?.known_flags.forEach((f) => (map[f.code] = { label: f.label, severity: f.severity }));
    return map;
  }, [stats.data]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await Promise.all([jobs.reload(), batches.reload()]);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (jobs.loading && !jobs.data) return <Loading />;
  if (jobs.error) return <ErrorNote message={jobs.error} />;

  const queued = batch?.counts.queued ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-ink flex items-center gap-3">
            {batch?.name ?? `Đợt #${batchId}`}
            {running && (
              <span className="inline-flex items-center gap-2 text-[13px] font-normal text-brand-lit">
                <span
                  className="relative w-2 h-2 rounded-full bg-brand-lit text-brand-lit pulse-dot pulse-halo"
                  aria-hidden
                />
                đang chạy
              </span>
            )}
          </h1>
          <p className="font-mono text-[13px] text-ink-faint mt-0.5">{batch?.out_dir}</p>
        </div>
        <div className="flex gap-2">
          {running ? (
            <Button onClick={() => act(() => api.pause(batchId))} disabled={busy}>
              Tạm dừng
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => act(() => api.start(batchId))}
              disabled={busy || !queued}
              title={queued ? `Chạy ${queued} POI đang chờ` : "Không còn POI nào chờ"}
            >
              Chạy {queued ? `(${queued})` : ""}
            </Button>
          )}
          <Button onClick={() => act(() => api.retry(batchId))} disabled={busy}>
            Thử lại job hỏng
          </Button>
          <LinkButton href={api.exportUrl(batchId)}>Tải TSV</LinkButton>
        </div>
      </div>

      {actionError && <ErrorNote message={actionError} />}

      <Panel title="Nhật ký chạy" bodyClass="px-5 py-4">
        <LiveLog log={log} />
      </Panel>

      <Panel
        title={`POI (${jobs.data?.jobs.length ?? 0})`}
        right={
          <div className="flex gap-1">
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setStatus(t.key)}
                className={`px-3 py-1 rounded-md text-[13.5px] transition-all duration-150 active:scale-95 ${
                  status === t.key
                    ? "bg-raised text-ink"
                    : "text-ink-dim hover:text-ink hover:bg-raised/60"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
        bodyClass="p-0"
      >
        {!jobs.data?.jobs.length ? (
          <Empty title="Không có POI nào khớp bộ lọc." />
        ) : (
          <JobTable jobs={jobs.data.jobs} labels={labels} />
        )}
      </Panel>
    </div>
  );
}
