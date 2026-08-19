import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { JobStatus, StepStatus } from "../types";

/* ---------------------------------------------------------------- Panel --- */

export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClass = "p-5",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section
      className={`bg-panel border border-line rounded-lg overflow-hidden flex flex-col anim-rise ${className}`}
    >
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 px-5 h-12 border-b border-line-soft shrink-0">
          <h2 className="text-[14px] font-semibold tracking-wide text-ink">{title}</h2>
          {right}
        </header>
      )}
      <div className={`${bodyClass} min-h-0`}>{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------- Stat tile --- */

export function Stat({
  label,
  value,
  tone = "ink",
  hint,
  to,
  delay = 0,
}: {
  label: string;
  value: ReactNode;
  tone?: "ink" | "good" | "bad" | "warn" | "brand";
  hint?: string;
  to?: string;
  /** Giây trễ của hiệu ứng hiện lên — xếp so le một hàng ô thì truyền 0, .05, .1… */
  delay?: number;
}) {
  const tones = {
    ink: "text-ink",
    good: "text-good-lit",
    bad: "text-bad-lit",
    warn: "text-warn-lit",
    brand: "text-brand-lit",
  } as const;

  const body = (
    <>
      <div className={`text-[38px] leading-none font-semibold tnum ${tones[tone]}`}>{value}</div>
      <div className="mt-2.5 text-[13px] font-medium text-ink-dim">{label}</div>
      {hint && <div className="mt-1 text-[12px] text-ink-faint">{hint}</div>}
    </>
  );

  const shell = "bg-panel border border-line rounded-lg px-5 py-4 block anim-rise";
  const style = { animationDelay: `${delay}s` };
  return to ? (
    <Link to={to} className={`${shell} lift hover:border-brand`} style={style}>
      {body}
    </Link>
  ) : (
    <div className={shell} style={style}>
      {body}
    </div>
  );
}

/* ---------------------------------------------------------- Status pills --- */

const JOB_TONE: Record<JobStatus, [string, string]> = {
  done: ["Xong", "text-good-lit border-good/50 bg-good/12"],
  running: ["Đang chạy", "text-brand-lit border-brand/50 bg-brand/12"],
  queued: ["Chờ", "text-ink-dim border-line bg-raised"],
  failed: ["Hỏng", "text-bad-lit border-bad/50 bg-bad/12"],
  needs_review: ["Cần xem lại", "text-warn-lit border-warn/50 bg-warn/12"],
  cancelled: ["Đã huỷ", "text-ink-faint border-line bg-raised"],
};

export function StatusPill({ status }: { status: JobStatus }) {
  const [label, tone] = JOB_TONE[status] ?? [status, "text-ink-dim border-line bg-raised"];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[12.5px] font-medium whitespace-nowrap ${tone}`}
    >
      {status === "running" && (
        <span className="relative w-2 h-2 rounded-full bg-brand-lit text-brand-lit pulse-dot pulse-halo" aria-hidden />
      )}
      {label}
    </span>
  );
}

export function FlagChip({
  label,
  severity,
  onClick,
  active,
}: {
  label: string;
  severity: "block" | "warn";
  onClick?: () => void;
  active?: boolean;
}) {
  const tone =
    severity === "block"
      ? "text-bad-lit border-bad/50 bg-bad/12"
      : "text-warn-lit border-warn/40 bg-warn/10";
  const ring = active ? "ring-1 ring-brand-lit" : "";
  const cls = `inline-block px-2 py-0.5 rounded-md border text-[12px] whitespace-nowrap ${tone} ${ring}`;
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      className={`${cls} transition-all hover:brightness-125 active:scale-95`}
    >
      {label}
    </button>
  ) : (
    <span className={cls}>{label}</span>
  );
}

/* ------------------------------------------------------- Dải 6 bước --------
 *
 * Thứ tự các bước MANG THÔNG TIN, không phải trang trí: `maps` chạy đầu và giữ
 * hai cổng chặn, nên `maps` hỏng là mọi ô bên phải chuyển hết sang "bỏ qua".
 * Nhìn dải này là đọc ngay được câu chuyện của một POI mà không cần mở ra.
 */

const STEP_TONE: Record<StepStatus, string> = {
  ok: "bg-good",
  failed: "bg-bad",
  skipped: "bg-idle",
  pending: "bg-raised",
  missing: "bg-raised",
};

const STEP_WORD: Record<StepStatus, string> = {
  ok: "xong",
  failed: "hỏng",
  skipped: "bỏ qua",
  pending: "chờ",
  missing: "chưa chạy",
};

export function StepRibbon({
  steps,
  order,
  size = "sm",
}: {
  steps: Record<string, StepStatus>;
  order: string[];
  size?: "sm" | "lg";
}) {
  const h = size === "lg" ? "h-3" : "h-2";
  const w = size === "lg" ? "w-10" : "w-5";
  return (
    <div className="inline-flex gap-px group" role="img" aria-label="Tiến độ 6 bước">
      {order.map((step) => {
        const state = (steps[step] ?? "missing") as StepStatus;
        return (
          <span
            key={step}
            title={`${step}: ${STEP_WORD[state]}`}
            className={`${h} ${w} first:rounded-l last:rounded-r ${STEP_TONE[state]}
              transition-transform duration-150 hover:scale-y-150`}
          />
        );
      })}
    </div>
  );
}

/* --------------------------------------------------------------- Misc ----- */

export function Button({
  children,
  onClick,
  variant = "ghost",
  disabled,
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
}) {
  const tones = {
    primary: "bg-brand hover:bg-brand-lit text-white border-brand",
    ghost: "bg-raised hover:bg-line text-ink border-line",
    danger: "bg-transparent hover:bg-bad/15 text-bad-lit border-bad/40",
  } as const;
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`px-3.5 h-9 rounded-md border text-[13.5px] font-medium whitespace-nowrap
        transition-all duration-150 active:scale-[0.97]
        disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100 ${tones[variant]}`}
    >
      {children}
    </button>
  );
}

/** Nút link kiểu <a> — trông y hệt Button ghost, dùng cho tải file. */
export function LinkButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="px-3.5 h-9 inline-flex items-center rounded-md border border-line bg-raised
        hover:bg-line text-ink text-[13.5px] font-medium whitespace-nowrap
        transition-all duration-150 active:scale-[0.97]"
    >
      {children}
    </a>
  );
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="py-14 text-center anim-fade">
      <p className="text-[15px] text-ink-dim">{title}</p>
      {hint && <p className="mt-2 text-[13px] text-ink-faint max-w-xl mx-auto">{hint}</p>}
    </div>
  );
}

export function Loading() {
  return (
    <div className="py-14 flex items-center justify-center gap-3 text-ink-faint anim-fade">
      <span className="w-4 h-4 rounded-full border-2 border-line border-t-brand-lit anim-spin" />
      <span className="text-[14px]">Đang tải…</span>
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="m-4 px-4 py-3 rounded-md border border-bad/40 bg-bad/10 text-bad-lit text-[13.5px] anim-rise">
      {message}
    </div>
  );
}

/** Thanh tỉ lệ ngang, dùng cho "ok theo bước" và "ô trống theo cột". */
export function Meter({
  value,
  total,
  tone = "bg-good",
}: {
  value: number;
  total: number;
  tone?: string;
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="h-2 rounded-full bg-raised overflow-hidden" title={`${value}/${total}`}>
      {/* Thanh bò từ 0 tới đích khi số liệu về, nên thay đổi giữa hai lần nạp là
          thấy được chứ không phải nhớ lại con số cũ. */}
      <div
        className={`h-full rounded-full ${tone} transition-[width] duration-500 ease-out`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
