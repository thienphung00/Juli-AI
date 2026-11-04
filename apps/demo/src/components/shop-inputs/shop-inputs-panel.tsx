"use client";

import { KolSamplesPanel } from "../shopee-kol/samples-panel";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { saveBlob } from "../../lib/shop-inputs/api";
import {
  GOAL_FIELDS,
  fmtChanges,
  fmtKb,
  fmtValue,
  fmtVnd,
  fmtWhen,
  monthLabel,
} from "../../lib/shop-inputs/format";
import type {
  Affected,
  ApplyResult,
  ChangeSet,
  FieldDiff,
  ImportPreview,
  InputsOverview,
  ShopInputsApi,
  SkuVersions,
  VersionSku,
} from "../../lib/shop-inputs/types";

/**
 * Cài đặt › Thông số shop (P90 step 4), artboard `CaiDatImport.dc.html`: download the
 * pre-filled template, upload it, Kiểm tra (rejected rows), So sánh (old → new), Áp dụng
 * (a reason is required), Phiên bản (per-SKU history with Khôi phục) and Mục tiêu.
 * One component for the seller's Settings and for Ops' Cài đặt shop; the API object
 * decides which backend it talks to.
 */

type Step = "tai" | "kiem" | "diff" | "apply" | "ver" | "mt" | "kol";

const STEPS: readonly [Step, string][] = [
  ["tai", "1 · Mẫu và tải lên"],
  ["kiem", "2 · Kiểm tra"],
  ["diff", "3 · So sánh"],
  ["apply", "4 · Áp dụng"],
  ["ver", "Phiên bản"],
  ["mt", "Mục tiêu"],
];
/** P91 D-9: the 7th step, shown only when the host gives the KOL samples API. */
const KOL_STEP: readonly [Step, string] = ["kol", "Mẫu KOL"];

const SKU_COLUMNS: readonly [string, boolean][] = [
  ["item_id", true],
  ["variation_id", true],
  ["SKU", true],
  ["tên", false],
  ["giá niêm yết", false],
  ["giá vốn", true],
  ["đóng gói", false],
  ["giảm tối đa (%)", false],
  ["tồn kho", false],
  ["ngày nhập lại", false],
  ["nhóm", false],
  ["trạng thái", false],
];

const FALLBACK_REASON = "Khác";
const COLOR = { pink: "#b0386a", pinkBg: "#fdeef4", line: "#f1e6eb", body: "#4a4a55", muted: "#6b6b76", ink: "#1a1a1f" };
const KIND_STYLE: Readonly<Record<string, CSSProperties>> = {
  unknown_sku: { background: "#fff4e0", color: "#8a5a00" },
  cost_ge_price: { background: "#fdecec", color: "#a12b2b" },
  cost_missing: { background: "#f0eef0", color: "#4a4a55" },
  out_of_range: { background: "#fdecec", color: "#a12b2b" },
  bad_date: { background: "#fdecec", color: "#a12b2b" },
  duplicate_sku: { background: "#fff4e0", color: "#8a5a00" },
  invalid_value: { background: "#fdecec", color: "#a12b2b" },
  bad_month: { background: "#fdecec", color: "#a12b2b" },
};

const box: CSSProperties = { background: "#fff", border: `1px solid ${COLOR.line}`, borderRadius: 14, padding: 16 };
const row = (cols: string): CSSProperties => ({
  display: "grid",
  gridTemplateColumns: cols,
  gap: 10,
  alignItems: "center",
  fontSize: 13,
  padding: "8px 0",
  borderTop: `1px solid ${COLOR.line}`,
});
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
const secondary: CSSProperties = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  borderRadius: 10,
  minHeight: 44,
  padding: "0 16px",
  cursor: "pointer",
  background: "#fff",
  color: COLOR.pink,
  border: `1px solid ${COLOR.pink}`,
};

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Không thực hiện được. Bạn thử lại sau ít phút nhé.";
}

function Banner({ affected, why }: { readonly affected: Affected; readonly why: string }) {
  return (
    <div
      data-testid="recalc-banner"
      role="status"
      style={{ display: "flex", gap: 12, alignItems: "center", background: "#eef6ff", border: "1px solid #c9defa", borderRadius: 12, padding: "10px 14px", fontSize: 14, flexWrap: "wrap" }}
    >
      <b style={{ color: "#1d4f91" }}>{affected.total} đề xuất sẽ được tính lại</b>
      <span style={{ color: COLOR.body }}>{why}</span>
    </div>
  );
}

function DiffTable({ diffs }: { readonly diffs: readonly FieldDiff[] }) {
  return (
    <div data-testid="diff-table">
      <div style={{ ...row("1.2fr 1fr 1fr 1fr 2fr"), color: COLOR.muted, fontWeight: 600, borderTop: 0 }}>
        <span>SKU</span>
        <span>Trường</span>
        <span>Cũ</span>
        <span>Mới</span>
        <span>Hệ quả</span>
      </div>
      {diffs.map((d) => (
        <div data-testid="diff-row" key={`${d.scope_ref}-${d.field}`} style={row("1.2fr 1fr 1fr 1fr 2fr")}>
          <span>{d.sku}</span>
          <span>{d.label}</span>
          <span style={{ color: COLOR.muted }}>{fmtValue(d.old, d.unit)}</span>
          <b>{fmtValue(d.new, d.unit)}</b>
          <span style={{ color: COLOR.body }}>{d.effect}</span>
        </div>
      ))}
    </div>
  );
}

export interface ShopInputsPanelProps {
  readonly api: ShopInputsApi;
  /** Upload, apply and restore (a viewer in Ops only reads and downloads). */
  readonly canEdit?: boolean;
  /** Who writes, for the "đã áp dụng" line. */
  readonly writerLabel?: string;
  /** P91: show the "Mẫu KOL" step (flag `NEXT_PUBLIC_P91_KOL`); the sheet travels in the same workbook as the SKU sheet. */
  readonly kolSamples?: boolean;
}

export function ShopInputsPanel({ api, canEdit = true, writerLabel = "Quản lý shop", kolSamples }: ShopInputsPanelProps) {
  const [step, setStep] = useState<Step>("tai");
  const [overview, setOverview] = useState<InputsOverview | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [reasonChoice, setReasonChoice] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [applied, setApplied] = useState<ApplyResult | null>(null);
  const [skus, setSkus] = useState<readonly VersionSku[]>([]);
  const [scope, setScope] = useState<string | null>(null);
  const [history, setHistory] = useState<SkuVersions | null>(null);
  const [confirm, setConfirm] = useState<ChangeSet | null>(null);
  const [restored, setRestored] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const loadOverview = useCallback(() => {
    api
      .overview()
      .then(setOverview)
      .catch(() => setLoadFailed(true));
  }, [api]);
  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const loadSkus = useCallback(() => {
    api
      .versionsIndex()
      .then((list) => {
        setSkus(list);
        setScope((current) => current ?? list[0]?.scope_ref ?? null);
      })
      .catch((e) => setError(errorText(e)));
  }, [api]);
  useEffect(() => {
    if (step === "ver") loadSkus();
  }, [step, loadSkus]);
  useEffect(() => {
    if (step !== "ver" || !scope) return;
    let live = true;
    api
      .versions(scope)
      .then((h) => live && setHistory(h))
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [api, step, scope, restored]);

  const reason = reasonChoice === FALLBACK_REASON ? reasonText.trim() : (reasonChoice ?? "");
  const go = (next: Step) => {
    setError(null);
    setConfirm(null);
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
      loadOverview();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const restore = async () => {
    if (!confirm || !scope) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.restore(scope, confirm.number);
      setRestored(
        `Đã tạo ${result.new_version ?? "bản mới"} sao chép ${confirm.id}. Đang tính lại ${result.affected.total} đề xuất. ${confirm.id} vẫn còn trong danh sách.`,
      );
      setConfirm(null);
      loadOverview();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const counts = preview?.counts;
  const needFile = ["kiem", "diff", "apply", "mt"].includes(step) && !preview;
  const skuName = skus.find((s) => s.scope_ref === scope)?.sku ?? scope ?? "";

  let banner: ReactNode = null;
  if (preview && step === "diff") banner = <Banner affected={preview.affected} why="Chỉ các thẻ của sản phẩm có SKU đổi tính lại, thẻ khác giữ nguyên." />;
  if (preview && step === "apply" && !applied) banner = <Banner affected={preview.affected} why="Chỉ các thẻ của sản phẩm có SKU đổi tính lại, thẻ khác giữ nguyên." />;
  if (preview && step === "mt" && preview.affected.shop_wide)
    banner = <Banner affected={preview.affected} why="Mục tiêu biên và trần chi marketing đổi: thẻ giá, voucher và quảng cáo của cả shop tính lại." />;
  if (step === "ver" && confirm && history)
    banner = <Banner affected={history.restore_affects} why="Chỉ các thẻ của SKU này tính lại." />;

  return (
    <div data-testid="shop-inputs" style={{ display: "flex", flexDirection: "column", gap: 16, color: COLOR.ink }}>
      <p style={{ margin: 0, fontSize: 14, color: COLOR.body, maxWidth: 760 }}>
        Juli không đoán giá vốn của bạn. Tải mẫu đã điền sẵn SKU, điền số, tải lên. Mỗi lần áp dụng là một phiên bản, khôi phục được.
      </p>
      <div aria-label="Các bước" role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {(kolSamples ? [...STEPS, KOL_STEP] : STEPS).map(([id, label]) => (
          <button aria-selected={step === id} key={id} onClick={() => go(id)} role="tab" style={pill(step === id)} type="button">
            {label}
          </button>
        ))}
      </div>
      {banner}
      {error ? (
        <p role="alert" style={{ margin: 0, color: "#a12b2b", fontSize: 14 }}>
          {error}
        </p>
      ) : null}
      {loadFailed ? (
        <p role="alert" style={{ margin: 0, color: "#a12b2b", fontSize: 14 }}>
          Không tải được thông số shop. Vui lòng thử lại.
        </p>
      ) : null}

      {needFile ? (
        <section style={box}>
          <p style={{ margin: 0, fontSize: 14 }}>Chưa có tệp. Tải tệp lên ở bước 1 trước.</p>
          <button onClick={() => go("tai")} style={{ ...secondary, marginTop: 10 }} type="button">
            Về bước 1
          </button>
        </section>
      ) : null}

      {step === "tai" ? (
        <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
            <div style={{ ...box, display: "flex", flexDirection: "column", gap: 8 }}>
              <b>1. Tải mẫu đã điền sẵn</b>
              <span style={{ fontSize: 13, color: COLOR.body }}>
                {overview
                  ? `${overview.catalogue.sku_rows} dòng SKU của ${overview.catalogue.items} sản phẩm, lấy từ Seller Centre. Giá vốn bạn đã nhập được điền lại, ô còn thiếu để trống.`
                  : "Đang tải danh sách SKU…"}
              </span>
              <button onClick={() => void download()} style={primary(false)} type="button">
                {downloaded ? `Đã tải ${downloaded} ✓` : "Tải mẫu .xlsx"}
              </button>
              <span style={{ fontSize: 12, color: COLOR.muted }}>Tệp .xlsx · 2 trang tính: SKU và Mục tiêu</span>
            </div>
            {canEdit ? (
              <div style={{ ...box, display: "flex", flexDirection: "column", gap: 8 }}>
                <b>2. Tải tệp đã điền lên</b>
                <input
                  accept=".xlsx"
                  aria-label="Tệp thông số .xlsx"
                  data-testid="file-input"
                  hidden
                  onChange={(e) => void pick(e.target.files?.[0])}
                  ref={input}
                  type="file"
                />
                {file && preview ? (
                  <div data-testid="file-card" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <b>{file.name}</b>
                    <span style={{ fontSize: 13, color: COLOR.body }}>
                      {fmtKb(file.size)} · trang SKU {preview.counts.sku_rows} dòng · trang Mục tiêu {preview.counts.goal_rows} dòng · đã đọc xong
                    </span>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button onClick={() => go("kiem")} style={primary(false)} type="button">
                        Kiểm tra tệp ›
                      </button>
                      <button onClick={() => input.current?.click()} style={secondary} type="button">
                        Chọn tệp khác
                      </button>
                    </div>
                  </div>
                ) : (
                  <div
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      void pick(e.dataTransfer.files?.[0]);
                    }}
                    style={{ border: `2px dashed ${COLOR.line}`, borderRadius: 12, padding: 18, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}
                  >
                    <span style={{ fontSize: 13, color: COLOR.body }}>Kéo tệp .xlsx vào đây</span>
                    <button disabled={busy} onClick={() => input.current?.click()} style={secondary} type="button">
                      {busy ? "Đang đọc…" : "Chọn tệp"}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div style={box}>
                <b>2. Tải tệp đã điền lên</b>
                <p style={{ margin: "6px 0 0", fontSize: 13, color: COLOR.body }}>Vai trò Xem chỉ tải mẫu và xem phiên bản, không tải tệp lên được.</p>
              </div>
            )}
          </div>
          <div style={box}>
            <b>Trang SKU · {SKU_COLUMNS.length} cột</b>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
              {SKU_COLUMNS.map(([label, required]) => (
                <span
                  key={label}
                  style={{ fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "4px 10px", background: required ? COLOR.pinkBg : "#f0eef0", color: required ? COLOR.pink : COLOR.body }}
                >
                  {label + (required ? " *" : "")}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 12, color: COLOR.muted }}>
              Cột đậm là bắt buộc. Cột trống giữ nguyên giá trị cũ. Không có tên, số điện thoại hay địa chỉ khách trong tệp.
            </div>
          </div>
          {overview && overview.cost_fallback.count > 0 ? (
            <div data-testid="cost-fallback" style={box}>
              <b>{overview.cost_fallback.count} SKU chưa có giá vốn</b>
              <p style={{ margin: "6px 0", fontSize: 13, color: COLOR.body }}>
                Tạm tính giá vốn bằng 1/3 giá niêm yết (biên gộp {String(Math.round(overview.cost_fallback.margin_pct * 10) / 10).replace(".", ",")}%), ghi rõ là giả định. Điền giá vốn thật vào mẫu để thay con số này.
              </p>
              <details>
                <summary style={{ cursor: "pointer", fontSize: 13, color: COLOR.pink }}>Xem các SKU đang dùng giá vốn giả định</summary>
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13 }}>
                  {overview.cost_fallback.skus.map((s) => (
                    <li key={`${s.item_id}:${s.variation_id}`}>
                      {s.sku || s.item_id}
                      {s.assumed_cost !== null ? ` · giả định ${fmtVnd(s.assumed_cost)}` : ""}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          ) : null}
        </section>
      ) : null}

      {step === "kiem" && preview && counts ? (
        <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            <div style={box}>
              <span style={{ fontSize: 12, color: COLOR.muted }}>Hợp lệ</span>
              <div>
                <b data-testid="ok-count">{counts.sku_rows_valid} dòng</b>
              </div>
              <span style={{ fontSize: 12, color: COLOR.body }}>sẵn sàng so sánh</span>
            </div>
            <div style={box}>
              <span style={{ fontSize: 12, color: COLOR.muted }}>Bị từ chối</span>
              <div>
                <b data-testid="bad-count">{counts.sku_rows_rejected + counts.goal_rows_rejected} dòng</b>
              </div>
              <span style={{ fontSize: 12, color: COLOR.body }}>không ghi vào Juli</span>
            </div>
            <div style={box}>
              <span style={{ fontSize: 12, color: COLOR.muted }}>Trang Mục tiêu</span>
              <div>
                <b>{counts.goal_rows} dòng</b>
              </div>
              <span style={{ fontSize: 12, color: COLOR.body }}>
                {preview.warnings.length} cảnh báo, xem tab Mục tiêu
              </span>
            </div>
          </div>
          {preview.rejections.length > 0 ? (
            <div data-testid="rejections" style={box}>
              <div style={{ ...row("0.5fr 1.2fr 1fr 1fr 3fr 1.2fr"), color: COLOR.muted, fontWeight: 600, borderTop: 0 }}>
                <span>Dòng</span>
                <span>SKU</span>
                <span>Cột</span>
                <span>Giá trị</span>
                <span>Vì sao bị từ chối</span>
                <span>Loại</span>
              </div>
              {preview.rejections.map((r) => (
                <div data-testid="rejection-row" key={`${r.sheet}-${r.row}-${r.column}`} style={row("0.5fr 1.2fr 1fr 1fr 3fr 1.2fr")}>
                  <b>{r.row}</b>
                  <span>{r.sku}</span>
                  <span>{r.column}</span>
                  <b>{r.value}</b>
                  <span>{r.reason}</span>
                  <span style={{ ...(KIND_STYLE[r.kind] ?? {}), borderRadius: 999, padding: "3px 10px", fontSize: 12, fontWeight: 600, justifySelf: "start" }}>
                    {r.kind_label}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ margin: 0, fontSize: 14 }}>Không có dòng nào bị từ chối.</p>
          )}
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button disabled={counts.changes === 0} onClick={() => go("diff")} style={primary(counts.changes === 0)} type="button">
              Tiếp tục với {counts.sku_rows_valid} dòng hợp lệ ›
            </button>
            <button
              onClick={() => {
                setFile(null);
                setPreview(null);
                go("tai");
              }}
              style={secondary}
              type="button"
            >
              Sửa tệp và tải lại
            </button>
            <span style={{ fontSize: 12, color: COLOR.muted }}>Dòng lỗi không chặn dòng đúng. Dòng lỗi giữ nguyên giá trị cũ.</span>
          </div>
          {counts.changes === 0 ? <p style={{ margin: 0, fontSize: 13, color: COLOR.body }}>Tệp không có thay đổi hợp lệ nào so với giá trị hiện tại.</p> : null}
        </section>
      ) : null}

      {step === "diff" && preview && counts ? (
        <section style={box}>
          <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: 18 }}>So sánh cũ → mới</h3>
            <span data-testid="diff-summary" style={{ fontSize: 13, color: COLOR.body }}>
              {preview.diffs.length} thay đổi ở {new Set(preview.diffs.map((d) => d.scope_ref)).size} SKU · {counts.sku_rows_unchanged} dòng không đổi
              {preview.goal_diffs.length ? ` · ${preview.goal_diffs.length} thay đổi ở Mục tiêu` : ""}
            </span>
          </div>
          <DiffTable diffs={preview.diffs} />
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
            <button onClick={() => go("apply")} style={primary(false)} type="button">
              Tiếp tục áp dụng ›
            </button>
            <span style={{ fontSize: 12, color: COLOR.muted }}>Chưa có gì thay đổi cho đến khi bạn bấm Áp dụng.</span>
          </div>
        </section>
      ) : null}

      {step === "apply" && preview && counts ? (
        <section style={box}>
          {!applied ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3 style={{ margin: 0, fontSize: 18 }}>Áp dụng thành phiên bản mới</h3>
              <div style={{ fontSize: 14, color: COLOR.body }}>
                {preview.diffs.length + preview.goal_diffs.length} thay đổi ở {new Set(preview.diffs.map((d) => d.scope_ref)).size} SKU từ {file?.name ?? "tệp"}. Bắt buộc ghi lý do, để sau này biết vì sao giá sàn đổi.
              </div>
              <div aria-label="Lý do" role="group" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {(overview?.reasons ?? ["Giá nhập tháng 11", "Kiểm kho cuối tháng", "Sửa sai nhập liệu", FALLBACK_REASON]).map((r) => (
                  <button aria-pressed={reasonChoice === r} key={r} onClick={() => setReasonChoice(r)} style={pill(reasonChoice === r)} type="button">
                    {r}
                  </button>
                ))}
              </div>
              {reasonChoice === FALLBACK_REASON ? (
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
                  Lý do cụ thể
                  <input
                    maxLength={500}
                    onChange={(e) => setReasonText(e.target.value)}
                    style={{ font: "inherit", border: `1px solid ${COLOR.line}`, borderRadius: 8, minHeight: 40, padding: "0 10px" }}
                    value={reasonText}
                  />
                </label>
              ) : null}
              <div style={{ fontSize: 14 }}>
                Lý do ghi lại: <b data-testid="reason-text">{reason || "(chưa chọn)"}</b>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button disabled={!reason || busy || !canEdit} onClick={() => void apply()} style={primary(!reason || busy || !canEdit)} type="button">
                  Áp dụng
                </button>
                <button onClick={() => go("diff")} style={secondary} type="button">
                  Quay lại so sánh
                </button>
                <span style={{ fontSize: 12, color: COLOR.muted }}>{reason ? "" : "Chọn một lý do để áp dụng."}</span>
              </div>
            </div>
          ) : (
            <div data-testid="applied" style={{ display: "flex", flexDirection: "column", gap: 8, background: "#f1faf3", border: "1px solid #c7e8d0", borderRadius: 12, padding: 14 }}>
              <div>
                <b>Đã áp dụng</b>{" "}
                <span style={{ fontSize: 13, color: COLOR.body }}>
                  {writerLabel} · {fmtWhen(applied.applied_at)} · lý do: {applied.reason} · tệp {file?.name ?? ""}
                </span>
              </div>
              <div style={{ fontSize: 13, color: COLOR.body }}>
                Đang tính lại giá sàn, biên lợi nhuận và {applied.affected.total} đề xuất. Thường xong trong vài phút. Thẻ cũ không đổi cho đến khi có thẻ mới.
              </div>
              <div>
                <button onClick={() => go("ver")} style={secondary} type="button">
                  Xem các phiên bản ›
                </button>
              </div>
            </div>
          )}
        </section>
      ) : null}

      {step === "ver" ? (
        <section style={box}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: 18 }}>Phiên bản theo SKU</h3>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {skus.map((s) => (
                <button
                  aria-pressed={scope === s.scope_ref}
                  key={s.scope_ref}
                  onClick={() => {
                    setScope(s.scope_ref);
                    setConfirm(null);
                    setRestored(null);
                  }}
                  style={pill(scope === s.scope_ref)}
                  type="button"
                >
                  {s.sku}
                </button>
              ))}
            </div>
          </div>
          {skus.length === 0 ? <p style={{ margin: "10px 0 0", fontSize: 14 }}>Chưa có phiên bản nào. Áp dụng một tệp để tạo phiên bản đầu tiên.</p> : null}
          {history ? (
            <div data-testid="versions">
              <div style={{ ...row("0.5fr 1.6fr 1.2fr 1.4fr 2fr 1.2fr"), color: COLOR.muted, fontWeight: 600, borderTop: 0 }}>
                <span>Bản</span>
                <span>Khi nào · ai</span>
                <span>Tệp</span>
                <span>Lý do</span>
                <span>Giá trị</span>
                <span />
              </div>
              {history.versions.map((v) => (
                <div
                  data-testid="version-row"
                  key={v.id}
                  style={{ ...row("0.5fr 1.6fr 1.2fr 1.4fr 2fr 1.2fr"), background: v.current ? "#f1faf3" : undefined }}
                >
                  <b>{v.id}</b>
                  <span>
                    {fmtWhen(v.valid_from)}
                    <br />
                    <span style={{ color: COLOR.muted }}>{v.set_by === "team" ? "Đội ngũ Juli" : writerLabel}</span>
                  </span>
                  <span style={{ color: COLOR.body }}>{v.import_file_hash ? `tệp ${v.import_file_hash.slice(0, 8)}` : (v.reason ?? "").startsWith("Khôi phục") ? `khôi phục ${(v.reason ?? "").replace("Khôi phục từ ", "")}` : "nhập tay"}</span>
                  <span>{v.reason ?? ""}</span>
                  <span>{fmtChanges(v.changes)}</span>
                  <span>
                    {v.current ? (
                      <span style={{ fontSize: 12, fontWeight: 600, color: "#1f7a3a" }}>Hiện hành</span>
                    ) : canEdit && !confirm ? (
                      <button aria-label={`Khôi phục ${v.id}`} onClick={() => setConfirm(v)} style={secondary} type="button">
                        Khôi phục
                      </button>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
          {confirm && history ? (
            <div data-testid="restore-confirm" role="alertdialog" aria-label={`Khôi phục ${confirm.id}`} style={{ marginTop: 12, background: COLOR.pinkBg, borderRadius: 12, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              <b>
                Khôi phục {confirm.id} cho {skuName}?
              </b>
              <span style={{ fontSize: 13, color: COLOR.body }}>
                Juli tạo bản mới sao chép {confirm.id}, không xoá bản nào. Giá sàn và biên của {skuName} tính lại, và {history.restore_affects.total} đề xuất liên quan được tính lại.
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button disabled={busy} onClick={() => void restore()} style={primary(busy)} type="button">
                  Khôi phục
                </button>
                <button onClick={() => setConfirm(null)} style={secondary} type="button">
                  Huỷ
                </button>
              </div>
            </div>
          ) : null}
          {restored ? (
            <div data-testid="restored" role="status" style={{ marginTop: 12, background: "#f1faf3", border: "1px solid #c7e8d0", borderRadius: 12, padding: 12, fontSize: 14 }}>
              {restored}
            </div>
          ) : null}
        </section>
      ) : null}

      {step === "kol" && kolSamples ? <KolSamplesPanel api={api} canEdit={canEdit} /> : null}

      {step === "mt" ? <GoalsView overview={overview} preview={preview} onApply={() => go("apply")} /> : null}
    </div>
  );
}

function GoalsView({
  overview,
  preview,
  onApply,
}: {
  readonly overview: InputsOverview | null;
  readonly preview: ImportPreview | null;
  readonly onApply: () => void;
}) {
  const months = new Map<string, Map<string, { neu: unknown; old: unknown }>>();
  for (const m of overview?.months ?? []) {
    months.set(m.month, new Map(Object.entries(m.values).map(([k, v]) => [k, { neu: v, old: v }])));
  }
  for (const d of preview?.goal_diffs ?? []) {
    const cells = months.get(d.scope_ref) ?? new Map<string, { neu: unknown; old: unknown }>();
    cells.set(d.rule_key, { neu: d.new, old: d.old });
    months.set(d.scope_ref, cells);
  }
  const warnings = new Map((preview?.warnings ?? []).map((w) => [w.month, w.message]));
  return (
    <section data-testid="goals" style={box}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: 18 }}>Mục tiêu</h3>
        <span style={{ fontSize: 13, color: COLOR.body }}>Trang Mục tiêu của tệp · mỗi tháng một dòng · hiện hành → mới</span>
      </div>
      <div style={{ ...row("1fr repeat(5, 1.2fr)"), color: COLOR.muted, fontWeight: 600, borderTop: 0 }}>
        <span>Tháng</span>
        {GOAL_FIELDS.map((f) => (
          <span key={f.key}>{f.key === "daily_marketing_cap" ? "Trần ngân sách QC/ngày" : f.label}</span>
        ))}
      </div>
      {months.size === 0 ? <p style={{ margin: "10px 0 0", fontSize: 14 }}>Chưa có mục tiêu tháng nào.</p> : null}
      {[...months.keys()].sort().map((month) => {
        const cells = months.get(month)!;
        return (
          <div data-testid="goal-row" key={month}>
            <div style={row("1fr repeat(5, 1.2fr)")}>
              <b>{monthLabel(month)}</b>
              {GOAL_FIELDS.map((f) => {
                const c = cells.get(f.key);
                if (!c) return <span key={f.key} style={{ color: COLOR.muted }}>(chưa có)</span>;
                const changed = c.neu !== c.old;
                return (
                  <span key={f.key} style={{ display: "flex", flexDirection: "column" }}>
                    <b>{fmtValue(c.neu, f.unit)}</b>
                    <span style={{ fontSize: 11, color: COLOR.muted, textDecoration: changed && c.old !== null ? "line-through" : "none" }}>
                      {!changed ? "không đổi" : c.old === null || c.old === undefined ? "dòng mới" : fmtValue(c.old, f.unit)}
                    </span>
                  </span>
                );
              })}
            </div>
            {warnings.get(month) ? (
              <div role="status" style={{ fontSize: 12, color: "#8a5a00", background: "#fff4e0", borderRadius: 8, padding: "6px 10px", marginBottom: 6 }}>
                Cảnh báo: {warnings.get(month)}
              </div>
            ) : null}
          </div>
        );
      })}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 10, fontSize: 12, color: COLOR.muted }}>
        <span>Biên mục tiêu đưa vào giá sàn vận hành: (giá vốn + đóng gói) ÷ (1 − phí sàn − QC − hoa hồng − biên mục tiêu).</span>
        <span>Kiểm tra chéo: GMV ≈ đơn × AOV, lệch quá 5% thì cảnh báo, không chặn.</span>
      </div>
      {preview && preview.goal_diffs.length > 0 ? (
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
          <button onClick={onApply} style={primary(false)} type="button">
            Áp dụng cùng tệp ›
          </button>
          <span style={{ fontSize: 12, color: COLOR.muted }}>Mục tiêu và SKU cùng một phiên bản, cùng một lý do.</span>
        </div>
      ) : null}
    </section>
  );
}
