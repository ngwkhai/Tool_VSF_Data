import { Link } from "react-router-dom";
import type { Job } from "../types";
import { FlagChip, StatusPill, StepRibbon } from "./ui";

const STEPS = ["maps", "gemini1", "old_address", "menu", "tiktok", "facebook"];

export function JobTable({
  jobs,
  labels,
  showBatch = false,
}: {
  jobs: Job[];
  /** code -> {label, severity}, từ /api/stats. */
  labels: Record<string, { label: string; severity: "block" | "warn" }>;
  showBatch?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="text-[12.5px] font-medium text-ink-dim border-b border-line-soft">
            <th className="font-medium px-4 py-3 w-14 text-right">STT</th>
            <th className="font-medium px-4 py-3">POI</th>
            <th className="font-medium px-4 py-3 w-36">Trạng thái</th>
            <th className="font-medium px-4 py-3 w-32" title={STEPS.join(" → ")}>
              6 bước
            </th>
            <th className="font-medium px-4 py-3">Cần chú ý</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              className="border-b border-line-soft/60 hover:bg-raised/50 align-top row-hover"
            >
              <td className="px-4 py-3 tnum text-ink-faint text-right text-[14px]">{job.seq}</td>
              <td className="px-4 py-3">
                <Link
                  to={`/jobs/${job.id}`}
                  className="text-[15px] text-brand-lit font-medium hover:underline underline-offset-4"
                >
                  {job.poi_name}
                </Link>
                {showBatch && (
                  <span className="ml-2 font-mono text-[12px] text-ink-faint">
                    đợt #{job.batch_id}
                  </span>
                )}
                {job.place_id && (
                  <span
                    className="ml-2 text-[11.5px] px-1.5 py-0.5 rounded border border-good/40 bg-good/10 text-good-lit"
                    title={`Mở thẳng bằng place_id ${job.place_id} — không qua tìm kiếm`}
                  >
                    ⚓ place_id
                  </span>
                )}
                {job.error_message && (
                  <div
                    className="mt-1 text-[13px] text-bad-lit/90 line-clamp-2"
                    title={job.error_message}
                  >
                    {job.error_message}
                  </div>
                )}
              </td>
              <td className="px-4 py-3">
                <StatusPill status={job.status} />
              </td>
              <td className="px-4 py-3 pt-4">
                <StepRibbon steps={job.steps} order={STEPS} />
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1.5">
                  {job.flags.map((code) => (
                    <FlagChip
                      key={code}
                      label={labels[code]?.label ?? code}
                      severity={labels[code]?.severity ?? "warn"}
                    />
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
