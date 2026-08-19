import { useState } from "react";
import { api } from "../api";
import { Button, Empty, ErrorNote, Panel } from "../components/ui";
import type { Check } from "../types";

export function Doctor() {
  const [result, setResult] = useState<{ checks: Check[]; healthy: boolean; degraded: string[] } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.doctor());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Môi trường</h1>
        <p className="text-[14px] text-ink-dim mt-1">
          Kiểm tra Chrome, hai thread chat Gemini, TikTok và Facebook. Mất khoảng 15 giây vì phải
          mở và điều hướng thật.
        </p>
      </div>

      <Panel
        title="Kiểm tra"
        right={
          <Button variant="primary" onClick={run} disabled={busy}>
            {busy ? "Đang kiểm tra…" : "Chạy kiểm tra"}
          </Button>
        }
      >
        {error && <ErrorNote message={error} />}

        {busy && (
          <div className="py-10 flex items-center justify-center gap-3 text-ink-dim">
            <span className="w-5 h-5 rounded-full border-2 border-line border-t-brand-lit anim-spin" />
            <span className="text-[14px]">Đang mở Chrome và điều hướng…</span>
          </div>
        )}

        {!result && !error && !busy && (
          <Empty
            title="Chưa chạy kiểm tra."
            hint="Thao tác này sẽ mở cửa sổ Chrome của tool."
          />
        )}

        {result && !busy && (
          <>
            <ul className="divide-y divide-line-soft">
              {result.checks.map((c, i) => (
                <li
                  key={c.label}
                  className="flex items-center gap-3 py-3 anim-rise"
                  style={{ animationDelay: `${i * 0.04}s` }}
                >
                  <span
                    className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                      c.ok ? "bg-good-lit" : c.optional ? "bg-warn-lit" : "bg-bad-lit"
                    }`}
                  />
                  <span className="flex-1 text-[14.5px] text-ink">
                    {c.label}
                    {c.optional && (
                      <span className="ml-2 text-[12.5px] text-ink-faint">tuỳ chọn</span>
                    )}
                  </span>
                  <span
                    className={`text-[13.5px] text-right ${
                      c.ok ? "text-ink-dim" : c.optional ? "text-warn-lit" : "text-bad-lit"
                    }`}
                  >
                    {c.detail}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-5 pt-4 border-t border-line-soft text-[14px]">
              {result.healthy ? (
                <p className="text-good-lit">Mọi mục bắt buộc đều đạt — chạy lô được.</p>
              ) : (
                <p className="text-bad-lit">
                  Có mục bắt buộc chưa đạt. Chạy <code className="font-mono">vsf login</code> trong
                  terminal để đăng nhập rồi kiểm tra lại.
                </p>
              )}
              {result.degraded.length > 0 && (
                <p className="mt-1.5 text-ink-dim">
                  Chạy được nhưng thiếu phần tăng cường: {result.degraded.join(", ")}.
                </p>
              )}
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
