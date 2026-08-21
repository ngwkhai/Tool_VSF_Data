import type { AppConfig, Batch, Check, Job, JobDetail, Stats } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    // FastAPI trả lỗi ở khoá `detail`. Hiện đúng câu đó cho người dùng thay vì
    // "Request failed" — các thông báo bên server đã nói rõ phải làm gì tiếp.
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : message;
    } catch {
      /* thân phản hồi không phải JSON */
    }
    throw new Error(message);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = (path: string, body?: unknown) =>
  call(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  batches: () => call<{ batches: Batch[]; running: number | null }>("/batches"),

  createBatch: (payload: { out_dir: string; name: string; text: string; profile: string }) =>
    call<{
      batch_id: number;
      added: number;
      profile: string;
      with_place_id: number;
      with_address: number;
    }>("/batches", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  start: (id: number, resume = true) => post(`/batches/${id}/start`, { resume, limit: null }),
  pause: (id: number) => post(`/batches/${id}/pause`),
  cancel: (id: number) => post(`/batches/${id}/cancel`),
  retry: (id: number, everything = false) => post(`/batches/${id}/retry?everything=${everything}`),
  deleteBatch: (id: number) =>
    call<{ removed_jobs: number }>(`/batches/${id}`, { method: "DELETE" }),

  jobs: (batchId: number, params: { status?: string; flag?: string } = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][],
    );
    return call<{ jobs: Job[] }>(`/batches/${batchId}/jobs?${q}`);
  },

  allJobs: (params: { status?: string; flag?: string; severity?: string } = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][],
    );
    return call<{ jobs: Job[] }>(`/jobs?${q}`);
  },

  job: (id: number, tiktok = 0) => call<JobDetail>(`/jobs/${id}?tiktok=${tiktok}`),

  // `null` cho một cột = bỏ phần sửa tay của cột đó (khác `""` = ép cột rỗng).
  saveOverrides: (id: number, overrides: Record<string, string | null>) =>
    call<{ ok: boolean; overrides: Record<string, string> }>(`/jobs/${id}/row`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),

  clearOverrides: (id: number) => call(`/jobs/${id}/row`, { method: "DELETE" }),

  pickTikTok: (id: number, index: number) => post(`/jobs/${id}/tiktok`, { index }),

  rerun: (id: number, payload: { only?: string | null; force_food?: boolean }) =>
    post(`/jobs/${id}/rerun`, { only: payload.only ?? null, force_food: !!payload.force_food }),

  stats: () => call<Stats>("/stats"),
  config: () => call<AppConfig>("/config"),
  reindex: () => post("/reindex"),
  doctor: () => call<{ checks: Check[]; healthy: boolean; degraded: string[] }>("/doctor"),
  exportUrl: (id: number) => `/api/export/${id}.tsv`,
};
