import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";
import { JobTable } from "../components/JobTable";
import { Empty, ErrorNote, Loading, Panel } from "../components/ui";

export function Triage() {
  const [params, setParams] = useSearchParams();
  const flag = params.get("flag") ?? "";
  const severity = params.get("severity") ?? "";
  const status = params.get("status") ?? "";

  const stats = useLoad(() => api.stats(), []);
  const jobs = useLoad(
    () =>
      api.allJobs({
        flag: flag || undefined,
        severity: severity || undefined,
        status: status || undefined,
      }),
    [flag, severity, status],
  );

  const labels = useMemo(() => {
    const map: Record<string, { label: string; severity: "block" | "warn" }> = {};
    stats.data?.known_flags.forEach((f) => (map[f.code] = { label: f.label, severity: f.severity }));
    return map;
  }, [stats.data]);

  function setFilter(next: Record<string, string>) {
    const merged = new URLSearchParams();
    Object.entries(next).forEach(([k, v]) => v && merged.set(k, v));
    setParams(merged);
  }

  const present = stats.data?.flags ?? [];
  const blocking = present.filter((f) => f.severity === "block");
  const warning = present.filter((f) => f.severity === "warn");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Cần người xử lý</h1>
        <p className="text-[14px] text-ink-dim mt-1 max-w-3xl">
          <span className="text-bad-lit font-medium">Cờ đỏ</span> — chạy lại không sửa được, phải
          có người quyết định. <span className="text-warn-lit font-medium">Cờ vàng</span> — dùng
          được nhưng còn ô trống hoặc giá trị đáng ngờ.
        </p>
      </div>

      <Panel title="Lọc">
        <div className="space-y-4">
          <FilterRow
            title="Chặn"
            tone="bad"
            items={blocking}
            active={flag}
            onPick={(code) => setFilter(code === flag ? {} : { flag: code })}
          />
          <FilterRow
            title="Cảnh báo"
            tone="warn"
            items={warning}
            active={flag}
            onPick={(code) => setFilter(code === flag ? {} : { flag: code })}
          />
          <div className="pt-3 border-t border-line-soft flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-medium text-ink-dim w-24 shrink-0">Trạng thái</span>
            {[
              { key: "needs_review", label: "Cần xem lại" },
              { key: "failed", label: "Hỏng" },
              { key: "queued", label: "Chờ" },
            ].map((s) => (
              <button
                key={s.key}
                onClick={() => setFilter(status === s.key ? {} : { status: s.key })}
                className={`px-3 py-1 rounded-md border text-[13.5px] transition-all duration-150 active:scale-95 ${
                  status === s.key
                    ? "border-brand-lit text-brand-lit bg-brand/12"
                    : "border-line text-ink-dim hover:text-ink hover:border-ink-faint"
                }`}
              >
                {s.label}
              </button>
            ))}
            {(flag || status || severity) && (
              <button
                onClick={() => setFilter({})}
                className="ml-auto text-[13.5px] text-brand-lit hover:underline underline-offset-4"
              >
                Bỏ bộ lọc
              </button>
            )}
          </div>
        </div>
      </Panel>

      <Panel
        title={`Kết quả (${jobs.data?.jobs.length ?? 0})`}
        right={flag && <span className="text-[13px] text-ink-faint">{labels[flag]?.label ?? flag}</span>}
        bodyClass="p-0"
      >
        {jobs.loading && !jobs.data ? (
          <Loading />
        ) : jobs.error ? (
          <ErrorNote message={jobs.error} />
        ) : !jobs.data?.jobs.length ? (
          <Empty title="Không POI nào khớp bộ lọc." hint="Chọn một cờ ở trên, hoặc bỏ bộ lọc." />
        ) : (
          <JobTable jobs={jobs.data.jobs} labels={labels} showBatch />
        )}
      </Panel>
    </div>
  );
}

function FilterRow({
  title,
  tone,
  items,
  active,
  onPick,
}: {
  title: string;
  tone: "bad" | "warn";
  items: { code: string; label: string; count: number }[];
  active: string;
  onPick: (code: string) => void;
}) {
  if (!items.length) return null;
  const colors =
    tone === "bad"
      ? "border-bad/40 text-bad-lit hover:bg-bad/10"
      : "border-warn/35 text-warn-lit hover:bg-warn/10";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[13px] font-medium text-ink-dim w-24 shrink-0">{title}</span>
      {items.map((f) => (
        <button
          key={f.code}
          onClick={() => onPick(f.code)}
          className={`px-3 py-1 rounded-md border text-[13.5px] transition-all duration-150 active:scale-95 ${colors} ${
            active === f.code ? "ring-1 ring-brand-lit" : ""
          }`}
        >
          {f.label}
          <span className="ml-2 tnum text-ink-dim">{f.count}</span>
        </button>
      ))}
    </div>
  );
}
