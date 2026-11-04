"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { saveBlob } from "../../lib/shop-inputs/api";
import { fmtVnd, fmtWhen } from "../../lib/shop-inputs/format";
import type { PlannedApplied, PlannedChangesApi, PlannedImport, PlannedOverview, PlannedPreview, PlannedRow, RowAction } from "../../lib/planned-changes/types";

/**
 * Cài đặt › Đề xuất kế hoạch (P91 D-13): the shop lists the listing changes it plans or has made in an
 * .xlsx (title, first line of the description, cover image, variation table, hide, relist), uploads it,
 * reads which rows are refused and the card each valid row becomes, and applies it with a reason. A row
 * marked "hoàn thành" is recorded as done on its date. Every apply is a numbered version. One component
 * for the seller's Settings and for Ops' Cài đặt shop; the API object decides the backend.
 */

type Step = "tai" | "kiem" | "apply" | "ver";

const STEPS: readonly [Step, string][] = [
  ["tai", "1 · Mẫu và tải lên"],
  ["kiem", "2 · Kiểm tra"],
  ["apply", "3 · Áp dụng"],
  ["ver", "Các lần nhập"],
];

const COLOR = { pink: "#b0386a", pinkBg: "#fdeef4", line: "#f1e6eb", body: "#4a4a55", muted: "#6b6b76", ink: "#1a1a1f", red: "#a12b2b", amber: "#8a5a00" };
const box: CSSProperties = { background: "#fff", border: `1px solid ${COLOR.line}`, borderRadius: 14, padding: 16 };
const pill = (on: boolean): CSSProperties => ({
  font: "inherit",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 999,
  minHeight: 40,
  padding: "0 14px",
  cursor: "pointer",
  border: `1px solid ${on ? COLOR.pink : COLOR.line}`,
  background: on ? COLOR.pinkBg : "#fff",
  color: on ? COLOR.pink : COLOR.body,
});
const primary = (off: boolean): CSSProperties => ({
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  borderRadius: 10,
  minHeight: 44,
  padding: "0 18px",
  border: 0,
  cursor: off ? "not-allowed" : "pointer",
  background: off ? "#e6dfe3" : COLOR.pink,
  color: off ? COLOR.muted : "#fff",
});
const secondary: CSSProperties = { ...primary(false), background: "#fff", color: COLOR.pink, border: `1px solid ${COLOR.pink}` };
const chip = (bg: string, fg: string): CSSProperties => ({ background: bg, color: fg, borderRadius: 999, padding: "2px 10px", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" });

const ACTION: Readonly<Record<RowAction, { label: string; style: CSSProperties }>> = {
  create: { label: "Tạo thẻ mới", style: chip("#e8f7ee", "#14532d") },
  advance: { label: "Cập nhật tiến độ", style: chip("#eef6ff", "#1d4f91") },
  unchanged: { label: "Không đổi", style: chip("#f0eef0", COLOR.body) },
  rejected: { label: "Từ chối", style: chip("#fdecec", COLOR.red) },
};

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Không thực hiện được. Bạn thử lại sau ít phút nhé.";
}

function RowView({ r }: { readonly r: PlannedRow }) {
  const action = ACTION[r.action];
  return (
    <div data-testid="planned-row" style={{ borderTop: `1px solid ${COLOR.line}`, padding: "10px 0", display: "grid", gap: 4 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <b>{r.ref || `Dòng ${r.row}`}</b>
        <span style={action.style}>{action.label}</span>
        <span style={{ color: COLOR.body }}>{r.change_label}</span>
        <span style={{ color: COLOR.muted }}>sản phẩm {r.item_id}</span>
        <span style={{ color: COLOR.muted }}>
          {r.decision_label} · {r.status_label}
          {r.date ? ` · ${r.date}` : ""}
          {r.window_days ? ` · đo ${r.window_days} ngày` : ""}
          {r.cost ? ` · chi phí ${fmtVnd(r.cost)}` : ""}
        </span>
        {r.depends_on.length > 0 ? <span style={{ color: COLOR.muted }}>sau {r.depends_on.join(", ")}</span> : null}
      </div>
      {r.after ? <div style={{ fontSize: 13, color: COLOR.body, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{r.after.slice(0, 240)}</div> : null}
      {r.card ? (
        <div data-testid="planned-card" style={{ fontSize: 13, color: COLOR.muted }}>
          {r.card.estimated && r.card.dprofit_p50 !== null
            ? `Dự kiến lợi nhuận/tháng: ${fmtVnd(r.card.dprofit_p10 ?? 0)} … ${fmtVnd(r.card.dprofit_p90 ?? 0)} (giữa ${fmtVnd(r.card.dprofit_p50)})`
            : "Không ước tính"}
        </div>
      ) : null}
      {r.problems.map((p) => (
        <div key={`${p.kind}-${p.column}`} role="alert" style={{ color: COLOR.red, fontSize: 13 }}>
          {p.label}
          {p.detail ? `: ${p.detail}` : ""}
        </div>
      ))}
      {r.warnings.map((w) => (
        <div key={`${w.kind}-${w.column}`} style={{ color: COLOR.amber, fontSize: 13 }}>
          Lưu ý · {w.label}
          {w.detail ? ` (${w.detail})` : ""}
        </div>
      ))}
    </div>
  );
}

export interface PlannedChangesPanelProps {
  readonly api: PlannedChangesApi;
  /** Upload and apply (a viewer in Ops only reads and downloads). */
  readonly canEdit?: boolean;
}

export function PlannedChangesPanel({ api, canEdit = true }: PlannedChangesPanelProps) {
  const [step, setStep] = useState<Step>("tai");
  const [overview, setOverview] = useState<PlannedOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PlannedPreview | null>(null);
  const [reasonChoice, setReasonChoice] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [applied, setApplied] = useState<PlannedApplied | null>(null);
  const [imports, setImports] = useState<readonly PlannedImport[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.overview().then(setOverview).catch((e) => setError(errorText(e)));
  }, [api]);
  const loadImports = useCallback(() => {
    api.versions().then(setImports).catch((e) => setError(errorText(e)));
  }, [api]);
  useEffect(() => {
    if (step === "ver") loadImports();
  }, [step, loadImports]);

  const reason = reasonChoice === "Khác" ? reasonText.trim() : (reasonChoice ?? "");
  const go = (next: Step) => {
    setError(null);
    setStep(next);
  };

  const download = async () => {
    setError(null);
    try {
      const t = await api.template();
      saveBlob(t.blob, t.filename);
      setDownloaded(t.filename);
    } catch (e) {
      setError(errorText(e));
    }
  };
  const pick = async (picked: File | undefined) => {
    if (!picked) return;
    setError(null);
    setBusy(true);
    setApplied(null);
    setReasonChoice(null);
    try {
      const result = await api.preview(picked);
      setFile(picked);
      setPreview(result);
      if (result.missing_columns.length === 0) setStep("kiem");
    } catch (e) {
      setFile(null);
      setPreview(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!file || !preview || !reason) return;
    setBusy(true);
    setError(null);
    try {
      setApplied(await api.apply(file, reason, preview.file_hash));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const counts = preview?.counts;
  const writable = (counts?.create ?? 0) + (counts?.advance ?? 0);
  return (
    <div data-testid="planned-changes" style={{ display: "flex", flexDirection: "column", gap: 16, color: COLOR.ink }}>
      <p style={{ margin: 0, fontSize: 14, color: COLOR.body, maxWidth: 760 }}>
        Liệt kê các thay đổi tên, mô tả, ảnh bìa, phân loại, ẩn hoặc nhập hàng lại của sản phẩm trong một tệp. Mỗi dòng hợp lệ thành một thẻ (có mã JC); dòng
        &ldquo;hoàn thành&rdquo; được ghi nhận vào đúng ngày đã làm. Mỗi lần áp dụng là một phiên bản.
      </p>
      <div aria-label="Các bước" role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {STEPS.map(([id, label]) => (
          <button aria-selected={step === id} key={id} onClick={() => go(id)} role="tab" style={pill(step === id)} type="button">
            {label}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" style={{ margin: 0, color: COLOR.red, fontSize: 14 }}>
          {error}
        </p>
      ) : null}

      {step === "tai" ? (
        <section style={box}>
          <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>Mẫu và tải lên</h3>
          <p style={{ margin: "0 0 8px", fontSize: 13, color: COLOR.body }}>
            Các cột: {overview ? overview.columns.map((c) => c.label).join(" · ") : "…"}. Cửa sổ đo tối thiểu {overview?.min_window_days ?? 3} ngày; tên sản phẩm
            tối đa {overview?.max_title_chars ?? 100} ký tự.
          </p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <button onClick={() => void download()} style={secondary} type="button">
              Tải mẫu .xlsx
            </button>
            {downloaded ? <span style={{ fontSize: 13, color: COLOR.muted }}>Đã tải {downloaded}</span> : null}
            <input accept=".xlsx" aria-label="Chọn tệp kế hoạch" hidden onChange={(e) => void pick(e.target.files?.[0])} ref={input} type="file" />
            <button disabled={!canEdit || busy} onClick={() => input.current?.click()} style={primary(!canEdit || busy)} type="button">
              {busy ? "Đang kiểm tra…" : "Chọn tệp để kiểm tra"}
            </button>
          </div>
          {preview && preview.missing_columns.length > 0 ? (
            <p role="alert" style={{ color: COLOR.red, fontSize: 14 }}>
              Tệp thiếu cột: {preview.missing_columns.join(", ")}.
            </p>
          ) : null}
        </section>
      ) : null}

      {step === "kiem" || step === "apply" ? (
        !preview ? (
          <section style={box}>
            <p style={{ margin: 0, fontSize: 14 }}>Chưa có tệp. Tải tệp lên ở bước 1 trước.</p>
            <button onClick={() => go("tai")} style={{ ...secondary, marginTop: 10 }} type="button">
              Về bước 1
            </button>
          </section>
        ) : null
      ) : null}

      {step === "kiem" && preview ? (
        <section data-testid="planned-check" style={box}>
          <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>
            {counts?.rows ?? 0} dòng · {counts?.create ?? 0} thẻ mới · {counts?.advance ?? 0} cập nhật · {counts?.unchanged ?? 0} không đổi ·{" "}
            <span style={{ color: COLOR.red }}>{counts?.rejected ?? 0} từ chối</span>
            {counts?.warnings ? <span style={{ color: COLOR.amber }}> · {counts.warnings} lưu ý</span> : null}
          </h3>
          {preview.rows.map((r) => (
            <RowView key={`${r.row}-${r.ref}`} r={r} />
          ))}
          <div style={{ marginTop: 12 }}>
            <button disabled={writable === 0} onClick={() => go("apply")} style={primary(writable === 0)} type="button">
              Tiếp: áp dụng
            </button>
          </div>
        </section>
      ) : null}

      {step === "apply" && preview ? (
        <section style={box}>
          <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>Áp dụng</h3>
          {applied ? (
            <div data-testid="planned-applied" role="status">
              <p style={{ margin: 0, fontSize: 14 }}>
                Đã áp dụng (lần nhập {applied.number}): {applied.created} thẻ mới, {applied.advanced} cập nhật, {applied.executed} ghi nhận đã làm, {applied.rejected} dòng từ chối.
              </p>
              <ul style={{ fontSize: 13, color: COLOR.body }}>
                {applied.rows.map((r) => (
                  <li key={r.ref}>
                    {r.ref} → {r.code ?? "—"} ({r.action}
                    {r.executed_on ? `, đã làm ${r.executed_on}` : ""})
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <>
              <p style={{ margin: "0 0 8px", fontSize: 13, color: COLOR.body }}>
                {writable} dòng sẽ được ghi, {counts?.rejected ?? 0} dòng từ chối không ghi gì. Lý do là bắt buộc.
              </p>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {(overview?.reasons ?? []).map((r) => (
                  <button aria-pressed={reasonChoice === r} key={r} onClick={() => setReasonChoice(r)} style={pill(reasonChoice === r)} type="button">
                    {r}
                  </button>
                ))}
              </div>
              {reasonChoice === "Khác" ? (
                <input aria-label="Lý do" maxLength={500} onChange={(e) => setReasonText(e.target.value)} placeholder="Lý do áp dụng" style={{ marginTop: 8, width: "100%", minHeight: 40 }} value={reasonText} />
              ) : null}
              <div style={{ marginTop: 12 }}>
                <button disabled={!canEdit || busy || !reason || writable === 0} onClick={() => void apply()} style={primary(!canEdit || busy || !reason || writable === 0)} type="button">
                  {busy ? "Đang áp dụng…" : "Áp dụng"}
                </button>
              </div>
            </>
          )}
        </section>
      ) : null}

      {step === "ver" ? (
        <section data-testid="planned-versions" style={box}>
          <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>Các lần nhập</h3>
          {imports.length === 0 ? <p style={{ margin: 0, fontSize: 14 }}>Chưa có lần nhập nào.</p> : null}
          {imports.map((v) => (
            <div key={v.number} style={{ borderTop: `1px solid ${COLOR.line}`, padding: "8px 0", fontSize: 13 }}>
              <b>Lần {v.number}</b> · {fmtWhen(v.applied_at)} · {v.set_by === "seller" ? "Quản lý shop" : "Đội ngũ Juli"} · {v.reason}
              <span style={{ color: COLOR.muted }}>
                {" "}
                · {v.counts.create ?? 0} thẻ mới · {v.counts.advance ?? 0} cập nhật · {v.counts.executed ?? 0} đã làm · {v.counts.rejected ?? 0} từ chối
              </span>
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
