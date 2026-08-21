import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useConfig, useLoad, useWorkerEvents } from "../hooks";
import { Button, Empty, ErrorNote, LinkButton, Loading, Panel } from "../components/ui";

const FIELD =
  "w-full h-10 px-3 rounded-md border border-line bg-canvas text-ink text-[14px] " +
  "placeholder:text-ink-faint transition-colors focus:border-brand";

const LABEL = "block text-[13px] font-medium text-ink-dim mb-1.5";

function NewBatchForm({ onCreated }: { onCreated: () => void }) {
  const [outDir, setOutDir] = useState("");
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [profile, setProfile] = useState("");
  const config = useConfig();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const count = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#")).length;

  async function submit() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await api.createBatch({
        out_dir: outDir.trim(),
        name: name.trim(),
        text,
        profile: profile || config?.default_profile || "food",
      });
      // Báo lại đã nhận được bao nhiêu place_id/địa chỉ: đó là cách duy nhất để
      // biết ngay rằng cột đã được tách đúng, thay vì phát hiện lúc chạy xong.
      const parts = [`Đã nạp ${res.added} POI (${res.profile}) vào đợt #${res.batch_id}`];
      if (res.with_place_id) parts.push(`${res.with_place_id} có place_id`);
      if (res.with_address) parts.push(`${res.with_address} có địa chỉ`);
      setNote(parts.join(" · ") + ".");
      setText("");
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Nạp danh sách mới">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <label className="block">
          <span className={LABEL}>Thư mục kết quả</span>
          <input
            value={outDir}
            onChange={(e) => setOutDir(e.target.value)}
            placeholder="output_19_8"
            className={`${FIELD} font-mono`}
          />
        </label>
        <label className="block">
          <span className={LABEL}>
            Tên đợt <span className="text-ink-faint font-normal">(không bắt buộc)</span>
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Đợt 19/8"
            className={FIELD}
          />
        </label>
        {/* Bộ dataset chốt CẢ ĐỢT: nó quyết định bộ cột của row.tsv, danh sách
            bước, và chiều của cổng phân loại ngành. Đổi sau khi đã chạy nghĩa là
            xuất lại toàn bộ, nên chọn ngay từ đây. */}
        <label className="block">
          <span className={LABEL}>Bộ dataset</span>
          <select
            value={profile || config?.default_profile || "food"}
            onChange={(e) => setProfile(e.target.value)}
            className={FIELD}
          >
            {Object.entries(config?.profiles ?? {}).map(([key, p]) => (
              <option key={key} value={key}>
                {key} — {p.columns.length} cột ({p.category_l1})
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block">
        <span className={LABEL}>Danh sách POI</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          spellCheck={false}
          placeholder={
            "Dán thẳng từ bảng tính — tên, địa chỉ, place_id ngăn bởi Tab:\n" +
            "Bún Bò Thành Danh\t124 Trần Phú, Nha Trang\tChIJzWzaPZ1ncDER5ZVqZtJM6qY\n\n" +
            "Hoặc chỉ tên, mỗi dòng một quán:\n" +
            "Bánh Canh Cô Tâm\n" +
            "Cà Phê Nhiên"
          }
          className="w-full px-3 py-2.5 rounded-md border border-line bg-canvas text-ink font-mono
            text-[13.5px] leading-relaxed placeholder:text-ink-faint resize-y
            transition-colors focus:border-brand"
        />
      </label>

      <div className="flex items-center gap-3 mt-4">
        <Button variant="primary" onClick={submit} disabled={busy || !outDir.trim() || !count}>
          {busy ? "Đang nạp…" : `Nạp ${count || 0} POI`}
        </Button>
        <span className="text-[13px] text-ink-faint">
          Thứ tự cột: <b className="text-ink-dim">tên · địa chỉ · place_id</b>. Dòng mở đầu bằng{" "}
          <code className="font-mono text-ink-dim">#</code> bị bỏ qua.
        </span>
      </div>

      {note && <p className="mt-3 text-[13.5px] text-good-lit anim-fade">{note}</p>}
      {error && <p className="mt-3 text-[13.5px] text-bad-lit anim-fade">{error}</p>}
    </Panel>
  );
}

export function Batches() {
  const { data, error, loading, reload } = useLoad(() => api.batches());
  const [busy, setBusy] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pausing, setPausing] = useState<number | null>(null);

  // Trang này trước đây nạp ĐÚNG MỘT LẦN, không đăng ký luồng sự kiện. Hệ quả:
  // bấm "Tạm dừng" xong, `reload()` chạy ngay lập tức trong khi worker còn đang
  // giữa một POI (có thể vài phút) nên `running` vẫn là lô đó — và không có gì
  // nạp lại nữa, kể cả sau khi worker đã dừng thật. Nhìn từ ngoài thì nút tạm
  // dừng "không hoạt động". Bám theo sự kiện worker, y hệt trang chi tiết lô.
  useWorkerEvents((e) => {
    if (
      e.kind === "job_end" ||
      e.kind === "batch_end" ||
      e.kind === "batch_stopped" ||
      e.kind === "batch_error"
    ) {
      setPausing(null);
      reload();
    }
  });

  async function act(id: number, fn: () => Promise<unknown>) {
    setBusy(id);
    setActionError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <NewBatchForm onCreated={reload} />

      {actionError && <ErrorNote message={actionError} />}

      <Panel
        title="Các đợt"
        right={
          <Button onClick={() => act(0, () => api.reindex())}>Nạp lại chỉ mục từ đĩa</Button>
        }
        bodyClass="p-0"
      >
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorNote message={error} />
        ) : !data?.batches.length ? (
          <Empty
            title="Chưa có đợt nào."
            hint="Nạp danh sách ở trên, hoặc nạp lại chỉ mục để tìm dữ liệu đã gán nhãn từ trước."
          />
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="text-[12.5px] font-medium text-ink-dim border-b border-line-soft">
                <th className="font-medium px-5 py-3 w-14">#</th>
                <th className="font-medium px-5 py-3">Đợt</th>
                <th className="font-medium px-5 py-3 w-20 text-right">POI</th>
                <th className="font-medium px-5 py-3 w-[26%]">Tiến độ</th>
                <th className="font-medium px-5 py-3 w-[22rem] text-right whitespace-nowrap">
                  Thao tác
                </th>
              </tr>
            </thead>
            <tbody>
              {data.batches.map((b) => {
                const running = data.running === b.id;
                const done = b.counts.done ?? 0;
                const failed = (b.counts.failed ?? 0) + (b.counts.needs_review ?? 0);
                const queued = b.counts.queued ?? 0;
                return (
                  <tr
                    key={b.id}
                    className="border-b border-line-soft/60 hover:bg-raised/50 row-hover"
                  >
                    <td className="px-5 py-3 tnum text-[14px] text-ink-faint">{b.id}</td>
                    <td className="px-5 py-3">
                      <Link
                        to={`/batches/${b.id}`}
                        className="text-[15px] text-brand-lit font-medium hover:underline underline-offset-4"
                      >
                        {b.name}
                      </Link>
                      <span className="ml-2 font-mono text-[12.5px] text-ink-faint">
                        {b.out_dir}
                      </span>
                      {running && (
                        <span className="ml-2 inline-flex items-center gap-1.5 text-[12.5px] text-brand-lit">
                          <span
                            className="relative w-2 h-2 rounded-full bg-brand-lit text-brand-lit pulse-dot pulse-halo"
                            aria-hidden
                          />
                          đang chạy
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3 tnum text-[15px] text-right text-ink">{b.total}</td>
                    <td className="px-5 py-3">
                      <div className="relative flex h-2 rounded-full overflow-hidden bg-raised">
                        {done > 0 && (
                          <span
                            className="bg-good transition-[flex] duration-500"
                            style={{ flex: done }}
                            title={`xong ${done}`}
                          />
                        )}
                        {failed > 0 && (
                          <span
                            className="bg-bad transition-[flex] duration-500"
                            style={{ flex: failed }}
                            title={`lỗi ${failed}`}
                          />
                        )}
                        {queued > 0 && (
                          <span
                            className="bg-idle transition-[flex] duration-500"
                            style={{ flex: queued }}
                            title={`chờ ${queued}`}
                          />
                        )}
                        {/* Đợt đang chạy có dải sáng quét ngang: nhìn từ xa cũng
                            biết máy còn làm việc, không cần đọc chữ. */}
                        {running && (
                          <span className="sweep absolute inset-0 pointer-events-none" aria-hidden />
                        )}
                      </div>
                      <div className="mt-1.5 text-[12.5px] text-ink-faint tnum">
                        {done} xong · {queued} chờ · {failed} cần xem
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex gap-2 justify-end flex-nowrap">
                        {running ? (
                          <Button
                            onClick={() => {
                              // Dừng là cờ HỢP TÁC: worker đọc giữa hai POI.
                              // Phải nói rõ ngay, nếu không người dùng tưởng
                              // bấm hụt rồi bấm lại nhiều lần.
                              setPausing(b.id);
                              act(b.id, () => api.pause(b.id));
                            }}
                            disabled={busy === b.id || pausing === b.id}
                            title="Dừng sau khi POI đang chạy kết thúc"
                          >
                            {pausing === b.id ? "Đang dừng…" : "Tạm dừng"}
                          </Button>
                        ) : (
                          <Button
                            variant="primary"
                            onClick={() => act(b.id, () => api.start(b.id))}
                            disabled={busy === b.id || !queued}
                            title={queued ? "Chạy các POI đang chờ" : "Không còn POI nào chờ"}
                          >
                            Chạy
                          </Button>
                        )}
                        <Button
                          onClick={() => act(b.id, () => api.retry(b.id))}
                          disabled={busy === b.id}
                          title="Đưa các job hỏng về hàng đợi"
                        >
                          Thử lại
                        </Button>
                        <LinkButton href={api.exportUrl(b.id)}>Tải TSV</LinkButton>
                        <Button
                          variant="danger"
                          disabled={busy === b.id || running}
                          title="Bỏ đợt khỏi chỉ mục. Không xoá file nào trên đĩa."
                          onClick={() => {
                            // Hỏi lại trước khi xoá: nút nằm ngay cạnh "Tải TSV",
                            // bấm trượt một ô là mất cả bảng job.
                            if (
                              confirm(
                                `Bỏ đợt "${b.name}" khỏi chỉ mục?\n\n` +
                                  `${b.total} POI sẽ biến mất khỏi giao diện, nhưng data.json ` +
                                  `và row.tsv trong ${b.out_dir} vẫn nguyên vẹn — ` +
                                  `“Nạp lại chỉ mục từ đĩa” sẽ đưa chúng trở lại.`,
                              )
                            ) {
                              act(b.id, () => api.deleteBatch(b.id));
                            }
                          }}
                        >
                          Bỏ
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
