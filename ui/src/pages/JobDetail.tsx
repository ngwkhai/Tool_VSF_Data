import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";
import {
  Button,
  Empty,
  ErrorNote,
  FlagChip,
  Loading,
  Panel,
  StatusPill,
  StepRibbon,
} from "../components/ui";
import type { JobDetail as Detail, StepRun, TikTokCandidate } from "../types";

type Tab = "steps" | "row" | "photos" | "tiktok" | "raw";

const TABS: { key: Tab; label: string }[] = [
  { key: "steps", label: "Các bước" },
  { key: "row", label: "73 cột" },
  { key: "photos", label: "Ảnh" },
  { key: "tiktok", label: "TikTok" },
  { key: "raw", label: "JSON gốc" },
];

export function JobDetail() {
  const { id } = useParams();
  const jobId = Number(id);
  const [tab, setTab] = useState<Tab>("steps");
  const { data, error, loading, reload } = useLoad(() => api.job(jobId), [jobId]);
  const stats = useLoad(() => api.stats(), []);

  const labels = useMemo(() => {
    const map: Record<string, { label: string; severity: "block" | "warn" }> = {};
    stats.data?.known_flags.forEach((f) => (map[f.code] = { label: f.label, severity: f.severity }));
    return map;
  }, [stats.data]);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return null;

  const { job, record, batch } = data;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[13px] text-ink-faint mb-1.5">
            <Link
              to={`/batches/${batch.id}`}
              className="hover:text-brand-lit transition-colors"
            >
              {batch.name}
            </Link>
            <span>/</span>
            <span className="font-mono">{record.slug}</span>
            {record.place_id_hint && (
              <span
                className="px-1.5 py-0.5 rounded border border-good/40 bg-good/10 text-good-lit"
                title={record.place_id_hint}
              >
                ⚓ mở thẳng bằng place_id
              </span>
            )}
          </div>
          <h1 className="text-2xl font-semibold text-ink">{record.poi_name}</h1>
          <div className="flex items-center gap-3 mt-3 flex-wrap">
            <StatusPill status={job.status} />
            <StepRibbon steps={record.steps} order={data.steps} size="lg" />
            {record.flags.map((code) => (
              <FlagChip
                key={code}
                label={labels[code]?.label ?? code}
                severity={labels[code]?.severity ?? "warn"}
              />
            ))}
          </div>
        </div>
        <RerunControls jobId={jobId} steps={data.steps} onDone={reload} />
      </div>

      {record.missing_steps.length > 0 && (
        <div className="px-4 py-2.5 rounded-md border border-line bg-panel text-[13.5px] text-ink-dim">
          Chưa từng chạy bước:{" "}
          <span className="font-mono text-ink">{record.missing_steps.join(", ")}</span>
        </div>
      )}

      <div className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2.5 text-[14.5px] border-b-2 -mb-px transition-all duration-150 ${
              tab === t.key
                ? "border-brand-lit text-ink"
                : "border-transparent text-ink-dim hover:text-ink hover:border-line"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* `key` đổi theo tab → nội dung tab mới hiện lên bằng hiệu ứng, thay vì
          nhảy phát một khiến không rõ đã đổi tab hay chưa. */}
      <div key={tab} className="anim-fade">
        {tab === "steps" && <StepsTab detail={data} />}
        {tab === "row" && <RowTab detail={data} onSaved={reload} />}
        {tab === "photos" && <PhotosTab detail={data} onSaved={reload} />}
        {tab === "tiktok" && <TikTokTab detail={data} onPicked={reload} />}
        {tab === "raw" && <RawTab detail={data} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Chạy lại --- */

function RerunControls({
  jobId,
  steps,
  onDone,
}: {
  jobId: number;
  steps: string[];
  onDone: () => void;
}) {
  const [step, setStep] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function rerun() {
    setBusy(true);
    try {
      await api.rerun(jobId, { only: step || null });
      setNote("Đã xếp lại hàng đợi. Mở đợt và bấm Chạy.");
      onDone();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shrink-0 text-right">
      <div className="flex items-center gap-2">
        <select
          value={step}
          onChange={(e) => setStep(e.target.value)}
          className="h-9 px-2.5 rounded-md border border-line bg-canvas text-ink text-[13.5px]
            transition-colors focus:border-brand"
        >
          <option value="">Cả 6 bước</option>
          {steps.map((s) => (
            <option key={s} value={s}>
              Chỉ {s}
            </option>
          ))}
        </select>
        <Button variant="primary" onClick={rerun} disabled={busy}>
          Xếp lại hàng đợi
        </Button>
      </div>
      {note && <p className="mt-2 text-[13px] text-ink-dim max-w-xs anim-fade">{note}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- Bước ---- */

function StepsTab({ detail }: { detail: Detail }) {
  const { record } = detail;
  return (
    <div className="space-y-3">
      {detail.steps.map((step, i) => {
        const status = record.steps[step] ?? "missing";
        const run: StepRun = record.step_runs[step] ?? {};
        const warnings = record.warnings[step] ?? [];
        const tone =
          status === "ok"
            ? "border-l-good"
            : status === "failed"
              ? "border-l-bad"
              : "border-l-idle";
        return (
          <div
            key={step}
            style={{ animationDelay: `${i * 0.04}s` }}
            className={`bg-panel border border-line border-l-[3px] ${tone} rounded-lg px-5 py-4
              anim-rise transition-colors hover:border-line/80 hover:bg-panel/80`}
          >
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <span className="font-mono text-[15px] font-medium text-ink">{step}</span>
              <span className="flex items-center gap-3 text-[13px] text-ink-dim">
                {run.duration_s !== undefined && <span className="tnum">{run.duration_s}s</span>}
                {run.finished_at && (
                  <span className="tnum text-ink-faint">{run.finished_at.slice(11, 19)}</span>
                )}
                <span
                  className={
                    status === "ok"
                      ? "text-good-lit"
                      : status === "failed"
                        ? "text-bad-lit"
                        : "text-ink-faint"
                  }
                >
                  {status}
                </span>
              </span>
            </div>

            {run.reason && <p className="mt-2 text-[13.5px] text-ink-faint">Bỏ qua: {run.reason}</p>}

            {run.error_message && (
              <p className="mt-2.5 text-[13.5px] text-bad-lit">
                <span className="font-mono text-[12.5px] text-ink-faint mr-2">
                  {run.error_code ?? run.error_type}
                </span>
                {run.error_message}
              </p>
            )}

            {warnings.length > 0 && (
              <ul className="mt-2.5 space-y-1.5">
                {warnings.map((w, j) => (
                  <li key={j} className="text-[13.5px] text-warn-lit/90 flex gap-2">
                    <span className="text-ink-faint shrink-0">!</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            )}

            {run.traceback && (
              <details className="mt-3">
                <summary className="cursor-pointer text-[13px] text-ink-dim hover:text-ink transition-colors">
                  Traceback
                </summary>
                <pre className="mt-2 p-3 rounded-md bg-canvas border border-line overflow-x-auto text-[12.5px] text-ink-dim leading-relaxed anim-fade">
                  {run.traceback}
                </pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------- 73 cột ----- */

function RowTab({ detail, onSaved }: { detail: Detail; onSaved: () => void }) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const overrides = detail.record.overrides;

  const dirty = Object.keys(edits).length > 0;

  async function save() {
    setBusy(true);
    setNote(null);
    try {
      await api.saveOverrides(detail.job.id, edits);
      setEdits({});
      setNote("Đã lưu và xuất lại row.tsv.");
      onSaved();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function clearAll() {
    setBusy(true);
    try {
      await api.clearOverrides(detail.job.id);
      setEdits({});
      setNote("Đã xoá toàn bộ sửa tay, quay về giá trị pipeline sinh ra.");
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title={`73 cột — ${Object.keys(overrides).length} ô đã sửa tay`}
      right={
        <div className="flex items-center gap-2.5">
          {note && <span className="text-[13px] text-ink-dim anim-fade">{note}</span>}
          {Object.keys(overrides).length > 0 && (
            <Button variant="danger" onClick={clearAll} disabled={busy}>
              Xoá sửa tay
            </Button>
          )}
          <Button variant="primary" onClick={save} disabled={busy || !dirty}>
            Lưu {dirty ? `(${Object.keys(edits).length})` : ""}
          </Button>
        </div>
      }
      bodyClass="p-0"
    >
      <div className="max-h-[70vh] overflow-y-auto">
        <table className="w-full text-left">
          <tbody>
            {detail.columns.map((col) => {
              const isOverridden = col in overrides;
              const value = edits[col] ?? detail.row[col] ?? "";
              const edited = col in edits;
              return (
                <tr
                  key={col}
                  className="border-b border-line-soft/50 hover:bg-raised/40 align-top transition-colors"
                >
                  <td className="px-5 py-2 w-60 shrink-0">
                    <span className="font-mono text-[13px] text-ink-dim">{col}</span>
                    {isOverridden && (
                      <span
                        className="ml-1.5 text-[12px] text-brand-lit"
                        title="Giá trị này do bạn sửa tay"
                      >
                        ✎
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-2">
                    <textarea
                      rows={value.length > 90 ? 3 : 1}
                      value={value}
                      spellCheck={false}
                      onChange={(e) => setEdits((prev) => ({ ...prev, [col]: e.target.value }))}
                      className={`w-full px-2 py-1.5 rounded-md border bg-canvas text-[13.5px] font-mono
                        resize-y transition-colors
                        ${
                          edited
                            ? "border-brand-lit text-ink"
                            : isOverridden
                              ? "border-brand/40 text-ink"
                              : "border-line-soft text-ink-dim focus:text-ink focus:border-brand"
                        }`}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/* ---------------------------------------------------------------- Ảnh ----- */

// Đúng bằng schema.GALLERY_URLS_COUNT. Quy ước của DATASET (3 ảnh phụ), không
// phải tham số cào — bể ứng viên vẫn là 10 ảnh.
const GALLERY_LIMIT = 3;

// Google gắn hậu tố kích thước sau dấu "=" (…=w1080-h1080-p-k-no). So ảnh theo
// phần trước dấu "=", y hệt `_photo_base` bên schema.py: cùng một ảnh ở hai kích
// cỡ khác nhau phải được coi là MỘT, nếu không ảnh đại diện sẽ lọt vào lưới
// gallery dưới dạng "ảnh khác" và người tick không thấy nó trùng.
const photoBase = (url: string) => url.split("=")[0];

// Bể ứng viên lưu URL cỡ 1080 (đúng cỡ dataset cần). Lưới thumbnail mà tải cả
// 11 ảnh cỡ đó là ~1,9 MB mỗi POI chỉ để hiện mấy ô 200px — xin bản nhỏ để XEM,
// còn URL đem đi lưu vẫn là cái gốc. Cùng dạng hậu tố với gmaps.upgrade_image_url.
const thumb = (url: string) =>
  url.includes("googleusercontent.com") ? `${photoBase(url)}=w400-h400-p-k-no` : url;

// Cột raw_gallery_urls là danh sách phẳng ngăn bởi ", " — cùng quy ước với
// `", ".join(gallery)` bên schema.build_row.
const splitGallery = (value: string) =>
  value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

function PhotosTab({ detail, onSaved }: { detail: Detail; onSaved: () => void }) {
  const maps = detail.record.google_maps ?? {};
  const hero = maps.photos?.hero ?? "";
  const heroFromGallery = maps.photos?.hero_source === "gallery_first";
  const candidates = maps.gallery_candidates?.images ?? [];
  const galleryError = maps.gallery_candidates?.error;
  const overridden = "raw_gallery_urls" in detail.record.overrides;

  // Nguồn sự thật của "đang chọn cái gì" là chính cột đã xuất ra — nó đã gồm cả
  // mặc định (3 ảnh đầu) lẫn phần sửa tay, nên không phải dựng lại logic đó ở đây.
  const saved = useMemo(
    () => splitGallery(detail.row.raw_gallery_urls ?? ""),
    [detail.row.raw_gallery_urls],
  );
  const [picked, setPicked] = useState<string[]>(saved);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // Chỉ chạy khi CHUỖI cột đổi (useMemo giữ nguyên mảng khi chuỗi không đổi),
  // nên một lần reload vì việc khác không thổi bay mấy ô vừa tick.
  useEffect(() => setPicked(saved), [saved]);

  const dirty = picked.join(", ") !== saved.join(", ");
  const heroBase = hero ? photoBase(hero) : "";

  async function commit(value: string | null, message: string) {
    setBusy(true);
    setNote(null);
    try {
      await api.saveOverrides(detail.job.id, { raw_gallery_urls: value });
      setNote(message);
      onSaved();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function toggle(url: string) {
    setPicked((prev) => {
      if (prev.includes(url)) return prev.filter((u) => u !== url);
      // Chặn ở đúng 3: thứ tự tick chính là thứ tự trong cột, nên tick thêm cái
      // thứ 4 mà tự động đẩy cái cũ ra sẽ đổi cả thứ tự sau lưng người dùng.
      if (prev.length >= GALLERY_LIMIT) return prev;
      return [...prev, url];
    });
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Ảnh đại diện"
        right={
          heroFromGallery && (
            <span className="text-[13px] text-warn-lit">
              dựng lại từ ảnh đầu mục “Tất cả” — nên xem lại bằng mắt
            </span>
          )
        }
      >
        {hero ? (
          <div className="flex gap-4 items-start">
            <img
              src={thumb(hero)}
              alt="Ảnh đại diện"
              loading="lazy"
              referrerPolicy="no-referrer"
              className="w-44 h-44 object-cover rounded-lg border border-line shrink-0
                transition-transform duration-200 hover:scale-[1.03]"
            />
            <a
              href={hero}
              target="_blank"
              rel="noreferrer"
              className="font-mono text-[12.5px] text-brand-lit hover:underline break-all"
            >
              {hero}
            </a>
          </div>
        ) : (
          <Empty
            title="Chưa có ảnh đại diện."
            hint="Chạy lại bước maps, hoặc vá riêng khối ảnh bằng `vsf photos`."
          />
        )}
      </Panel>

      <Panel
        title={`Ảnh phụ — ${picked.length}/${GALLERY_LIMIT} đã chọn trong ${candidates.length} ứng viên`}
        right={
          <div className="flex items-center gap-2.5">
            {note && <span className="text-[13px] text-ink-dim anim-fade">{note}</span>}
            {overridden && (
              <Button
                variant="danger"
                disabled={busy}
                onClick={() => commit(null, "Đã bỏ tick tay, quay về 3 ảnh đầu.")}
              >
                Về mặc định
              </Button>
            )}
            <Button
              variant="primary"
              disabled={busy || !dirty || !picked.length}
              onClick={() => commit(picked.join(", "), "Đã lưu và xuất lại row.tsv.")}
            >
              Lưu {dirty ? `(${picked.length})` : ""}
            </Button>
          </div>
        }
        bodyClass="p-0"
      >
        <p className="px-5 py-2.5 text-[13px] text-ink-faint border-b border-line-soft">
          Không tick gì thì cột lấy {GALLERY_LIMIT} ảnh đầu. Số trên ô là thứ tự trong cột.
        </p>

        {candidates.length === 0 ? (
          <div className="p-5">
            <Empty
              title="Chưa có bể ứng viên ảnh."
              hint={
                galleryError ??
                "Bản ghi này cào từ trước khi có bể 10 ảnh. Vá riêng khối ảnh bằng `vsf photos \"<tên POI>\" --out <thư mục>`, hoặc chạy lại bước maps."
              }
            />
          </div>
        ) : (
          <div className="p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            {candidates.map((url, i) => {
              const order = picked.indexOf(url);
              const active = order >= 0;
              // Ảnh đầu mục "Tất cả" chính là ảnh đại diện. Cho tick nó thì cột
              // ảnh phụ lặp lại đúng raw_cover_image_url — đây là bất biến mà
              // build_row đã giữ, giao diện không được phép phá qua overrides.
              const isHero = !!heroBase && photoBase(url) === heroBase;
              const full = !active && picked.length >= GALLERY_LIMIT;
              const disabled = isHero || full;
              return (
                <button
                  key={url}
                  type="button"
                  onClick={() => !disabled && toggle(url)}
                  disabled={disabled}
                  style={{ animationDelay: `${i * 0.03}s` }}
                  title={
                    isHero
                      ? "Đây là ảnh đại diện, không dùng lại làm ảnh phụ"
                      : full
                        ? `Đã đủ ${GALLERY_LIMIT} ảnh — bỏ tick một ảnh trước`
                        : url
                  }
                  // Chỉ làm mờ ô THẬT SỰ không dùng được (ảnh đại diện). Ô chỉ
                  // vướng "đã đủ 3" vẫn phải hiện rõ: cả điểm của bể 10 ảnh là
                  // để nhìn hết rồi mới đổi ý, mờ 6/10 ô là chặn đúng việc đó.
                  className={`group relative block rounded-lg overflow-hidden border anim-rise
                    transition-all duration-200 ${
                      active
                        ? "border-brand-lit ring-2 ring-brand/50"
                        : isHero
                          ? "border-line opacity-40 cursor-not-allowed"
                          : full
                            ? "border-line cursor-not-allowed"
                            : "border-line hover:border-brand/60 hover:-translate-y-1 hover:shadow-[0_8px_24px_-10px_rgba(0,0,0,0.8)]"
                    }`}
                >
                  <img
                    src={thumb(url)}
                    alt={`Ứng viên ${i}`}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="w-full aspect-square object-cover transition-transform duration-300
                      group-hover:scale-105"
                  />
                  <span className="absolute top-1.5 left-1.5 px-1.5 rounded bg-canvas/85 text-[11.5px] font-mono text-ink-faint tnum">
                    {i}
                  </span>
                  {isHero && (
                    <span className="absolute top-1.5 right-1.5 px-1.5 rounded bg-canvas/85 text-[11.5px] text-ink-dim">
                      đại diện
                    </span>
                  )}
                  {active && (
                    <span className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-brand text-white text-[12.5px] font-semibold flex items-center justify-center tnum anim-fade">
                      {order + 1}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {picked.length > 0 && picked.length < GALLERY_LIMIT && (
          <p className="px-5 pb-4 text-[13px] text-warn-lit">
            Dataset quy ước {GALLERY_LIMIT} ảnh phụ — mới chọn {picked.length}.
          </p>
        )}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------- TikTok ----- */

function TikTokTab({ detail, onPicked }: { detail: Detail; onPicked: () => void }) {
  const [busy, setBusy] = useState(false);
  const candidates = detail.record.tiktok ?? [];
  const chosen = detail.row.raw_url;

  if (!candidates.length) {
    return (
      <Panel title="Ứng viên TikTok">
        <Empty
          title="Không có ứng viên nào."
          hint="Bước tiktok chưa chạy, hoặc tìm kiếm không ra kết quả cho tên POI này."
        />
      </Panel>
    );
  }

  async function pick(index: number) {
    setBusy(true);
    try {
      await api.pickTikTok(detail.job.id, index);
      onPicked();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`Ứng viên TikTok (${candidates.length})`} bodyClass="p-0">
      <ul className="divide-y divide-line-soft">
        {candidates.map((c: TikTokCandidate, i: number) => {
          const active = chosen && c.url === chosen;
          return (
            <li
              key={c.url}
              style={{ animationDelay: `${i * 0.04}s` }}
              className={`px-5 py-4 anim-rise transition-colors ${
                active ? "bg-brand/8" : "hover:bg-raised/40"
              }`}
            >
              <div className="flex items-start gap-4">
                <span className="tnum text-[14px] text-ink-faint w-5 shrink-0 pt-0.5">{i}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[15px] font-medium text-ink">{c.author ?? "—"}</span>
                    {c.posted_at && (
                      <span className="text-[13px] text-ink-faint tnum">
                        {c.posted_at.slice(0, 10)}
                      </span>
                    )}
                    {active && (
                      <span className="text-[12px] px-2 py-0.5 rounded-md border border-brand/50 bg-brand/12 text-brand-lit">
                        đang chọn
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[13.5px] text-ink-dim line-clamp-2">{c.caption}</p>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1.5 inline-block font-mono text-[12.5px] text-brand-lit hover:underline truncate max-w-full"
                  >
                    {c.url}
                  </a>
                </div>

                <div className="shrink-0 text-right w-48">
                  <div className="tnum text-[20px] font-semibold text-ink">
                    {c.score?.toFixed(2) ?? "—"}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1 justify-end">
                    {Object.entries(c.score_breakdown ?? {}).map(([k, v]) => (
                      <span
                        key={k}
                        title={`${k}: ${v}`}
                        className={`px-1.5 rounded text-[11.5px] font-mono border ${
                          v > 0
                            ? "border-good/40 text-good-lit bg-good/10"
                            : "border-line text-ink-faint"
                        }`}
                      >
                        {k.slice(0, 4)} {v}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3">
                    <Button onClick={() => pick(i)} disabled={busy || !!active}>
                      {active ? "Đang dùng" : "Chọn cái này"}
                    </Button>
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

/* ---------------------------------------------------------------- JSON ---- */

function RawTab({ detail }: { detail: Detail }) {
  const blocks: [string, unknown][] = [
    ["google_maps", detail.record.google_maps],
    ["gemini_profile", detail.record.gemini_profile],
    ["menu", detail.record.menu],
    ["facebook", detail.record.facebook],
  ];
  return (
    <div className="space-y-4">
      {blocks.map(([key, value]) => (
        <Panel key={key} title={key} bodyClass="p-0">
          <pre className="p-4 max-h-96 overflow-auto text-[12.5px] leading-relaxed text-ink-dim">
            {JSON.stringify(value, null, 2)}
          </pre>
        </Panel>
      ))}
    </div>
  );
}
