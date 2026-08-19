import { Link } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";
import { ErrorNote, Loading, Meter, Panel, Stat } from "../components/ui";
import type { StepStatus } from "../types";

/* Ghi chú từng bước giờ nằm ở tooltip chứ không in ra thành dòng: sáu dòng giải
   thích cạnh sáu thanh số liệu làm loãng đúng thứ người ta mở trang để xem. */
const STEP_NOTE: Record<string, string> = {
  maps: "Google Maps — giữ hai cổng chặn, hỏng là cả chuỗi dừng",
  gemini1: "Gemini #1 — 26 trường mô tả",
  old_address: "Phường trước sáp nhập 1/7/2025",
  menu: "Gemini #2 — trích thực đơn từ ảnh",
  tiktok: "Tìm và chấm điểm video",
  facebook: "Xác minh Trang rồi lấy Reels",
};

export function Dashboard() {
  const { data, error, loading, reload } = useLoad(() => api.stats());

  if (loading) return <Loading />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return null;

  const s = data.by_status;
  const blanks = data.blank_by_column
    .filter((b) => b.blank > 0 && b.blank < b.total)
    .sort((a, b) => b.blank - a.blank)
    .slice(0, 12);

  return (
    <div className="space-y-5">
      {/* Năm ô hiện lên so le trái sang phải — đúng thứ tự đọc, và đủ để thấy
          trang vừa nạp xong chứ không phải đang đứng hình. */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat label="Tổng POI" value={data.total} delay={0} />
        <Stat label="Xong" value={s.done ?? 0} tone="good" delay={0.05} />
        <Stat label="Đang chờ" value={s.queued ?? 0} delay={0.1} />
        <Stat
          label="Cần xem lại"
          value={s.needs_review ?? 0}
          tone="warn"
          to="/triage?severity=block"
          delay={0.15}
        />
        <Stat
          label="Hỏng"
          value={s.failed ?? 0}
          tone="bad"
          to="/triage?status=failed"
          delay={0.2}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Panel title="Tỉ lệ thành công theo bước">
          <div className="space-y-4">
            {Object.entries(data.steps).map(([step, counts]) => {
              const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
              const ok = counts.ok ?? 0;
              const failed = counts.failed ?? 0;
              const attempted = total - (counts.missing ?? 0);
              const pct = attempted > 0 ? Math.round((ok / attempted) * 100) : 0;
              return (
                <div key={step} className="group">
                  <div className="flex items-baseline justify-between gap-3 mb-1.5">
                    <span
                      className="font-mono text-[14px] text-ink cursor-help decoration-dotted underline-offset-4 group-hover:underline"
                      title={STEP_NOTE[step]}
                    >
                      {step}
                    </span>
                    <span className="tnum text-[14px] text-ink-dim shrink-0">
                      {ok}/{attempted || 0}
                      {failed > 0 && <span className="text-bad-lit ml-2">✗{failed}</span>}
                      <span className="ml-2.5 font-semibold text-ink">{pct}%</span>
                    </span>
                  </div>
                  <Meter
                    value={ok}
                    total={attempted || 1}
                    tone={pct >= 90 ? "bg-good" : pct >= 60 ? "bg-warn" : "bg-bad"}
                  />
                  {(counts.missing ?? 0) > 0 && (
                    <div className="mt-1.5 text-[12px] text-ink-faint">
                      {counts.missing} POI chưa từng chạy bước này
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel
          title="Hàng đợi cần xử lý"
          right={
            <Link
              to="/triage"
              className="text-[13px] text-brand-lit hover:underline underline-offset-4"
            >
              Xem tất cả →
            </Link>
          }
        >
          {data.flags.length === 0 ? (
            <p className="text-ink-faint py-8 text-center text-[14px]">Chưa có cờ nào.</p>
          ) : (
            <ul className="space-y-1">
              {data.flags.map((f) => (
                <li key={f.code}>
                  <Link
                    to={`/triage?flag=${f.code}`}
                    className="flex items-center gap-3 px-2.5 py-2 -mx-2.5 rounded-md
                      transition-all duration-150 hover:bg-raised hover:translate-x-1"
                  >
                    <span
                      className={`w-1 h-7 rounded-full shrink-0 ${
                        f.severity === "block" ? "bg-bad" : "bg-warn"
                      }`}
                    />
                    <span className="flex-1 min-w-0 truncate text-ink text-[14px]">{f.label}</span>
                    <span className="tnum text-[14px] font-medium text-ink-dim">{f.count}</span>
                    <span className="w-24 shrink-0">
                      <Meter
                        value={f.count}
                        total={data.total}
                        tone={f.severity === "block" ? "bg-bad" : "bg-warn"}
                      />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel
        title="Cột hay để trống"
        right={
          <button
            onClick={reload}
            className="text-[13px] text-brand-lit hover:underline underline-offset-4 transition-colors"
          >
            Nạp lại
          </button>
        }
      >
        {blanks.length === 0 ? (
          <p className="text-ink-faint py-6 text-center text-[14px]">
            Không cột nào trống một phần.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-3.5">
            {blanks.map((b) => (
              <div key={b.column}>
                <div className="flex justify-between text-[13px] mb-1.5">
                  <span className="font-mono text-ink truncate">{b.column}</span>
                  <span className="tnum text-ink-dim shrink-0 ml-2">
                    {b.blank}/{b.total}
                  </span>
                </div>
                <Meter value={b.blank} total={b.total} tone="bg-warn" />
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

export type { StepStatus };
