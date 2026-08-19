export type JobStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "needs_review"
  | "cancelled";

export type StepStatus = "ok" | "failed" | "skipped" | "pending" | "missing";

export interface Batch {
  id: number;
  name: string;
  out_dir: string;
  created_at: string;
  status: "idle" | "running" | "paused" | "done" | "cancelled";
  note: string;
  counts: Partial<Record<JobStatus, number>>;
  total: number;
}

export interface Job {
  id: number;
  batch_id: number;
  seq: number;
  poi_name: string;
  address_hint: string;
  place_id: string;
  force_food: boolean;
  only_step: string | null;
  status: JobStatus;
  slug: string;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  flags: string[];
  steps: Record<string, StepStatus>;
  updated_at: string;
}

export interface StepRun {
  status?: string;
  reason?: string;
  started_at?: string;
  finished_at?: string;
  duration_s?: number;
  error_code?: string;
  error_type?: string;
  error_message?: string;
  traceback?: string;
}

export interface TikTokCandidate {
  url: string;
  caption?: string;
  author?: string;
  posted_at?: string;
  views?: number | string;
  score?: number;
  score_breakdown?: Record<string, number>;
}

/** Khối `google_maps` của data.json. Chỉ khai báo phần giao diện thật sự đọc;
 *  phần còn lại vẫn đi qua `[key: string]: unknown` để tab "JSON gốc" hiện đủ. */
export interface GoogleMapsBlock {
  photos?: { hero?: string; hero_source?: string; secondary?: string[] };
  gallery_candidates?: { images?: string[]; category_used?: string | null; error?: string };
  [key: string]: unknown;
}

export interface PoiRecord {
  poi_name: string;
  slug: string;
  address_hint: string;
  place_id_hint: string;
  category_l1: string;
  category_l2: string;
  created_at: string;
  updated_at: string;
  steps: Record<string, StepStatus>;
  step_runs: Record<string, StepRun>;
  warnings: Record<string, string[]>;
  flags: string[];
  overrides: Record<string, string>;
  missing_steps: string[];
  google_maps: GoogleMapsBlock;
  gemini_profile: Record<string, unknown>;
  menu: Record<string, unknown>;
  tiktok: TikTokCandidate[];
  facebook: Record<string, unknown>;
}

export interface JobDetail {
  job: Job;
  batch: Batch;
  record: PoiRecord;
  row: Record<string, string>;
  columns: string[];
  steps: string[];
}

export interface FlagStat {
  code: string;
  label: string;
  severity: "block" | "warn";
  count: number;
}

export interface Stats {
  total: number;
  by_status: Partial<Record<JobStatus, number>>;
  flags: FlagStat[];
  known_flags: { code: string; label: string; severity: "block" | "warn" }[];
  steps: Record<string, Partial<Record<StepStatus, number>>>;
  rows_seen: number;
  blank_by_column: { column: string; blank: number; total: number }[];
}

export interface Check {
  label: string;
  ok: boolean;
  detail: string;
  optional: boolean;
}

export interface WorkerEvent {
  kind: string;
  ts?: string;
  step?: string;
  poi?: string;
  job_id?: number;
  batch_id?: number;
  status?: string;
  error?: string;
  error_code?: string;
  reason?: string;
  flags?: string[];
  [key: string]: unknown;
}
