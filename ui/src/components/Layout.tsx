import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useState } from "react";
import { useWorkerEvents } from "../hooks";

/* Biểu tượng vẽ tay bằng SVG — không kéo thêm thư viện icon nào chỉ để có bốn
   hình. Mỗi hình gợi đúng việc của mục: lưới số liệu, chồng đợt, cờ, nhịp tim. */
const ICON: Record<string, ReactNode> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  batches: (
    <>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </>
  ),
  triage: (
    <>
      <path d="M5 21V4" />
      <path d="M5 4h11l-1.5 4L16 12H5" />
    </>
  ),
  doctor: <path d="M3 12h4l2.5-6 4 12L16 12h5" />,
};

const NAV = [
  { to: "/", label: "Tổng quan", icon: "overview", end: true },
  { to: "/batches", label: "Đợt gán nhãn", icon: "batches" },
  { to: "/triage", label: "Cần xử lý", icon: "triage" },
  { to: "/doctor", label: "Môi trường", icon: "doctor" },
];

function NavIcon({ name }: { name: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-[18px] h-[18px] shrink-0"
      aria-hidden
    >
      {ICON[name]}
    </svg>
  );
}

/**
 * Chỉ báo worker: dấu hiệu sống duy nhất của trang.
 *
 * Nghe thẳng luồng sự kiện thay vì hỏi lại server theo chu kỳ — worker chạy
 * hàng giờ, hỏi mỗi vài giây suốt thời gian đó là lãng phí, mà vẫn trễ.
 */
function WorkerBadge() {
  const [state, setState] = useState<{ running: boolean; poi?: string; step?: string }>({
    running: false,
  });

  useWorkerEvents((e) => {
    if (e.kind === "batch_start") setState({ running: true });
    else if (e.kind === "batch_end" || e.kind === "batch_stopped" || e.kind === "batch_error")
      setState({ running: false });
    else if (e.kind === "job_start") setState({ running: true, poi: e.poi });
    else if (e.kind === "step_start")
      setState((s) => ({ running: true, poi: e.poi ?? s.poi, step: e.step }));
  });

  if (!state.running) {
    return (
      <span className="flex items-center gap-2 text-[13px] text-ink-faint">
        <span className="w-2 h-2 rounded-full bg-idle" aria-hidden />
        Worker đang rảnh
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2.5 text-[13px] text-brand-lit min-w-0 anim-fade">
      <span
        className="relative w-2 h-2 rounded-full bg-brand-lit text-brand-lit pulse-dot pulse-halo shrink-0"
        aria-hidden
      />
      <span className="truncate max-w-[26rem]">
        {state.poi ?? "Đang chạy"}
        {state.step && <span className="text-ink-dim"> · {state.step}</span>}
      </span>
    </span>
  );
}

export function Layout({ children }: { children?: ReactNode }) {
  // Đổi trang thì đổi luôn `key` của <main> → nội dung mới hiện lên bằng hiệu
  // ứng, thay vì thay thế đột ngột không rõ đã chuyển hay chưa.
  const { pathname } = useLocation();

  return (
    <div className="min-h-screen flex">
      <nav className="w-[214px] shrink-0 border-r border-line bg-panel flex flex-col">
        <div className="h-14 flex items-center gap-2.5 px-4 border-b border-line-soft">
          <span className="w-7 h-7 rounded-md bg-brand/20 border border-brand/40 flex items-center justify-center text-brand-lit text-[13px] font-bold">
            V
          </span>
          <span className="text-[16px] font-semibold tracking-tight text-ink">VSF Data</span>
          <span className="text-[11px] text-ink-faint font-mono">v2</span>
        </div>
        <ul className="py-3 px-2 space-y-0.5">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2 rounded-md text-[14.5px] transition-all duration-150 ${
                    isActive
                      ? "text-ink bg-raised shadow-[inset_2px_0_0_0_var(--color-brand-lit)]"
                      : "text-ink-dim hover:text-ink hover:bg-raised/60 hover:translate-x-0.5"
                  }`
                }
              >
                <NavIcon name={item.icon} />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 border-b border-line bg-panel/60 backdrop-blur flex items-center justify-end gap-4 px-6">
          <WorkerBadge />
        </header>
        {/* Chặn bề rộng ở 1600px: màn hình siêu rộng mà bảng kéo hết chiều ngang
            thì tên đợt và cột thao tác cách nhau cả gang tay, mắt phải quét
            ngang mới ghép được hai đầu một hàng. */}
        <main key={pathname} className="flex-1 min-w-0 p-6 anim-fade w-full max-w-[1600px]">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  );
}
