"use client";

import { useEffect, useRef, useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { boardErrorText, fileToB64, type BoardApi, type ExternalCommit, type ExternalPreview, type ExternalRow, type ImportJob } from "../../lib/shopee-decisions/board";
import { kindLabel } from "../../lib/shopee-decisions/model";

/**
 * Thực hiện, owner only (2026-11-16): sync the board with work done outside Juli.
 * "Nhập thẻ đã làm ngoài Juli": xlsx → preview table → Nhập. "Xoá bảng": one confirm step.
 * Labels only, no explanations (owner rule). The host hides this on the reviewer sample shop.
 */

const dm = (iso: string | null): string => {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}` : DASH;
};

const kinds = (r: ExternalRow): string => r.cards.map((c) => kindLabel({ change_kind: c.change_kind }) || c.change_kind).join(", ") || DASH;

type Pane = "none" | "import" | "reset";

const ACTION_LABEL: Record<string, string> = { created: "Đã tạo", exists: "Đã có", refused: "Không nhập được" };

export function BoardActions({ board, onChanged, pollMs = 2000 }: { readonly board: BoardApi; readonly onChanged: () => void; readonly pollMs?: number }) {
  const [pane, setPane] = useState<Pane>("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [preview, setPreview] = useState<ExternalPreview | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const file = useRef<string | null>(null);
  const announced = useRef<string | null>(null);
  const input = useRef<HTMLInputElement | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(boardErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  const open = (p: Pane) => {
    setPane(pane === p ? "none" : p);
    setError(null);
    setDone(null);
    setPreview(null);
    file.current = null;
  };
  const pick = (f: File | undefined) =>
    f &&
    void run(async () => {
      setPreview(null);
      const b64 = await fileToB64(f);
      file.current = b64;
      setPreview(await board.previewImport(b64));
    });
  // F6.2: the last import of the shop (also after a reload); a running one is polled until it ends.
  const settle = (j: ImportJob, fromLoad: boolean) => {
    setJob(j);
    if (j.status === "running" || announced.current === j.job_id) return;
    if (fromLoad && j.status === "done") {
      announced.current = j.job_id; // an old result is read, not announced again
      return;
    }
    announced.current = j.job_id;
    if (j.status === "done" && j.result) setDone(importSummary(j.result));
    else if (j.status === "failed") setError(boardErrorText(j.error));
    onChanged();
  };
  const settleRef = useRef(settle);
  useEffect(() => {
    settleRef.current = settle;
  });
  useEffect(() => {
    let live = true;
    board
      .importStatus()
      .then((j) => live && j && settleRef.current(j, true))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [board]);
  const running = job?.status === "running";
  useEffect(() => {
    if (!running) return;
    let live = true;
    const timer = setTimeout(() => {
      board
        .importStatus()
        .then((j) => live && j && settleRef.current(j, false))
        .catch(() => undefined);
    }, pollMs);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [board, running, job, pollMs]);
  const commit = () =>
    void run(async () => {
      if (!file.current || !preview) return;
      const started = await board.commitImport(file.current, preview.token);
      setPreview(null);
      setDone(null);
      settle(started, false);
    });
  const reset = () =>
    void run(async () => {
      const out = await board.reset();
      setPane("none");
      setDone(`Đã xoá ${fmt(out.withdrawn, 0)} thẻ`);
      onChanged();
    });

  const canImport = !!preview && preview.missing_columns.length === 0 && preview.counts.create > 0;
  return (
    <section aria-label="Đồng bộ bảng" className="sd-board" data-testid="sd-board">
      <div className="sd-board__bar">
        <button aria-expanded={pane === "import"} className="sa-btn" onClick={() => open("import")} type="button">
          Nhập thẻ đã làm ngoài Juli
        </button>
        <button aria-expanded={pane === "reset"} className="sa-btn" onClick={() => open("reset")} type="button">
          Xoá bảng
        </button>
        {running ? (
          <span className="sa-hint" data-testid="sd-board-running" role="status">
            Đang nhập…
          </span>
        ) : null}
        {done ? (
          <span className="sa-hint" data-testid="sd-board-done" role="status">
            {done}
          </span>
        ) : null}
      </div>

      {pane === "reset" ? (
        <div className="sd-board__pane" data-testid="sd-board-reset" role="group" aria-label="Xoá bảng">
          <b>Xoá toàn bộ thẻ trên bảng Thực hiện?</b>
          <button className="sa-btn sa-btn--primary" disabled={busy} onClick={reset} type="button">
            Xoá
          </button>
          <button className="sa-btn" disabled={busy} onClick={() => open("reset")} type="button">
            Huỷ
          </button>
        </div>
      ) : null}

      {pane === "import" ? (
        <div className="sd-board__pane" data-testid="sd-board-import">
          <label className="sa-btn">
            Chọn file .xlsx
            <input
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              aria-label="File .xlsx"
              className="sd-board__file"
              data-testid="sd-board-file"
              disabled={busy}
              onChange={(e) => pick(e.target.files?.[0])}
              ref={input}
              type="file"
            />
          </label>
          {busy && !preview ? (
            <span className="sa-hint" role="status">
              Đang đọc…
            </span>
          ) : null}
          {job?.status === "done" && job.result ? <ImportResult result={job.result} /> : null}
          {preview ? <PreviewTable preview={preview} /> : null}
          {preview ? (
            <button className="sa-btn sa-btn--primary" data-testid="sd-board-commit" disabled={busy || !canImport} onClick={commit} type="button">
              Nhập{preview.counts.create ? ` ${fmt(preview.counts.create, 0)} thẻ` : ""}
            </button>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

const importSummary = (out: ExternalCommit): string =>
  `Đã nhập ${fmt(out.created, 0)} thẻ${out.exists ? ` · ${fmt(out.exists, 0)} đã có` : ""}${out.refused ? ` · ${fmt(out.refused, 0)} không nhập được` : ""}`;

/** The per-card result of the last import: created, already there, or refused with its reason. */
function ImportResult({ result }: { readonly result: ExternalCommit }) {
  return (
    <>
      <p className="sa-hint" data-testid="sd-board-result-counts">
        {importSummary(result)}
      </p>
      <table className="sd-board__table" data-testid="sd-board-result">
        <thead>
          <tr>
            <th>Dòng</th>
            <th>Mã</th>
            <th>Loại</th>
            <th>Kết quả</th>
          </tr>
        </thead>
        <tbody>
          {result.cards.map((c) => (
            <tr data-testid={`sd-board-result-${c.ref}-${c.change_kind}`} key={`${c.ref}-${c.change_kind}-${c.row}`}>
              <td>{c.row}</td>
              <td>{c.ref}</td>
              <td>{kindLabel({ change_kind: c.change_kind }) || c.change_kind}</td>
              <td>
                {ACTION_LABEL[c.action] ?? c.action}
                {c.action === "refused" && (c.message || c.reason) ? `: ${c.message ?? c.reason}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function PreviewTable({ preview: p }: { readonly preview: ExternalPreview }) {
  if (p.missing_columns.length > 0) {
    return (
      <p className="sd-error" data-testid="sd-board-missing" role="alert">
        Thiếu cột: {p.missing_columns.join(", ")}
      </p>
    );
  }
  return (
    <>
      <p className="sa-hint" data-testid="sd-board-counts">
        {fmt(p.counts.rows, 0)} dòng · {fmt(p.counts.create, 0)} thẻ mới · {fmt(p.counts.exists, 0)} đã có · {fmt(p.counts.skipped, 0)} bỏ qua
      </p>
      <table className="sd-board__table" data-testid="sd-board-preview">
        <thead>
          <tr>
            <th>Dòng</th>
            <th>Mã</th>
            <th>Loại</th>
            <th>Trạng thái</th>
            <th>Bắt đầu</th>
            <th>Số ngày</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {p.rows.map((r) => (
            <tr data-testid={`sd-board-row-${r.row}`} key={`r${r.row}`}>
              <td>{r.row}</td>
              <td>{r.ref}</td>
              <td>{kinds(r)}</td>
              <td>{r.status_label}</td>
              <td>{dm(r.started_on)}</td>
              <td>{r.run_days === null ? DASH : fmt(r.run_days, 0)}</td>
              <td>{r.cards.length > 0 && r.cards.every((c) => c.action === "exists") ? "Đã có" : ""}</td>
            </tr>
          ))}
          {p.skipped.map((r) => (
            <tr className="sd-board__skipped" data-testid={`sd-board-skip-${r.row}`} key={`s${r.row}`}>
              <td>{r.row}</td>
              <td>{r.ref || DASH}</td>
              <td>{kinds(r)}</td>
              <td>{r.status_label || DASH}</td>
              <td>{dm(r.started_on)}</td>
              <td>{r.run_days === null ? DASH : fmt(r.run_days, 0)}</td>
              <td>Bỏ qua: {r.reason_label ?? DASH}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
