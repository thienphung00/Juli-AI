"use client";

import { useEffect, useRef, useState } from "react";

import { saveBlob } from "../../lib/shop-inputs/api";
import type { ApplyResult, ImportPreview, InputsOverview, SampleShipment, ShopInputsApi } from "../../lib/shop-inputs/types";
import { vnd } from "../../lib/shopee-analytics/format";

const SHEET = "Mẫu KOL";
const dmy = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const shipText = (list: readonly SampleShipment[]): string => (list.length === 0 ? "chưa gửi" : list.map((x) => `${x.qty} mẫu ngày ${dmy(x.sent_on)}, ship ${vnd(x.ship_fee)}`).join("; "));

/**
 * Cài đặt › Thông số shop › Mẫu KOL (`CaiDatMauKOL.dc.html`): the 7th step beside the SKU sheet. Same way of
 * working, on the SAME workbook, template, preview and apply routes as the SKU sheet (the sheet "Mẫu KOL" is its third sheet): download the template, upload it, Kiểm tra (bad rows do not block the good ones), So sánh cũ → mới
 * with what it changes (chi phí mẫu, ROI, hoàn vốn, cards recalculated), Áp dụng with a reason. Sample cost =
 * số lượng × (giá vốn + đóng gói) + phí ship; there is no KOL booking fee.
 */

type Step = 1 | 2 | 3 | 4;
const STEPS: readonly (readonly [Step, string])[] = [
  [1, "Mẫu và tải lên"],
  [2, "Kiểm tra"],
  [3, "So sánh"],
  [4, "Áp dụng"],
];
const DEFAULT_REASONS = ["Sửa số lượng mẫu thực tế đã gửi", "Cập nhật phí ship mới", "Thêm mẫu vừa gửi", "Khác"];

function message(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Không thực hiện được. Bạn thử lại sau ít phút nhé.";
}

export function KolSamplesPanel({ api, canEdit = true }: { readonly api: ShopInputsApi; readonly canEdit?: boolean }) {
  const [step, setStep] = useState<Step>(1);
  const [overview, setOverview] = useState<InputsOverview | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [applied, setApplied] = useState<ApplyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    let live = true;
    api.overview().then(
      (o) => live && setOverview(o),
      (e: unknown) => live && setError(message(e)),
    );
    return () => {
      live = false;
    };
  }, [api]);

  const download = async () => {
    setError(null);
    try {
      const t = await api.template();
      saveBlob(t.blob, t.filename);
    } catch (e) {
      setError(message(e));
    }
  };
  const upload = async (f: File) => {
    setBusy(true);
    setError(null);
    try {
      const p = await api.preview(f);
      setFile(f);
      setPreview(p);
      setApplied(null);
      setStep(2);
    } catch (e) {
      setError(message(e));
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
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const reasons = overview?.reasons.length ? overview.reasons : DEFAULT_REASONS;
  const shipments = (overview?.samples.items ?? []).flatMap((pair) => pair.shipments.map((sh) => ({ pair, sh })));
  const rejections = (preview?.rejections ?? []).filter((r) => r.sheet === SHEET);
  const counts = preview?.counts;
  const needFile = step > 1 && !preview;
  return (
    <div className="ks" data-testid="kol-samples">
      <div>
        <div className="sa-eyebrow">CÀI ĐẶT · THÔNG SỐ SHOP · MẪU KOL</div>
        <h2 className="sa-h1">Sheet “Mẫu KOL” trong file mẫu</h2>
        <p className="sa-hint">Cùng file .xlsx với giá vốn và đóng gói, thêm một sheet. Cùng cách làm: tải mẫu, tải lên, kiểm tra, so sánh cũ và mới, áp dụng với lý do. Đây là bước thứ bảy của Thông số shop.</p>
      </div>
      <div aria-label="Bước" className="sb-tabs" role="tablist">
        {STEPS.map(([n, label]) => (
          <button aria-selected={step === n} className={`sb-pill ${step === n ? "sb-pill--on" : ""}`} key={n} onClick={() => setStep(n)} role="tab" type="button">
            {label}
          </button>
        ))}
      </div>
      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
      {needFile ? (
        <p className="sa-hint" data-testid="ks-needfile">
          Chưa có tệp. Tải tệp lên ở bước 1 trước.
        </p>
      ) : null}

      {step === 1 ? (
        <section className="sa-card" data-testid="ks-step1">
          <div className="sa-card__head">
            <h3 className="sa-h2">Sheet “Mẫu KOL”</h3>
            <button className="sa-btn sa-btn--s" onClick={() => void download()} type="button">
              Tải file mẫu (điền sẵn KOL và sản phẩm đang có)
            </button>
            {canEdit ? (
              <>
                <button className="sa-btn sa-btn--primary sa-btn--s" disabled={busy} onClick={() => input.current?.click()} type="button">
                  Tải tệp lên
                </button>
                <input accept=".xlsx" aria-label="Tệp Mẫu KOL" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} ref={input} type="file" />
              </>
            ) : null}
            {overview ? (
              <span className="sa-hint" data-testid="ks-count">
                {overview.samples.shipments} lần gửi mẫu · {overview.samples.pairs} cặp KOL × sản phẩm đã ghi
              </span>
            ) : null}
          </div>
          <div className="ks-table" role="table">
            <div className="ks-row ks-row--head" role="row">
              {["KOL (tay cầm)", "Sản phẩm (mã SP hoặc SKU)", "Số lượng mẫu", "Ngày gửi", "Phí ship gửi mẫu", "Giá vốn dùng"].map((h) => (
                <span key={h} role="columnheader">
                  {h}
                </span>
              ))}
            </div>
            {shipments.map(({ pair, sh }, i) => (
              <div className="ks-row" key={i} role="row">
                <b role="cell">{sh.handle}</b>
                <span role="cell">{pair.sku}</span>
                <span role="cell">{sh.qty}</span>
                <span role="cell">{dmy(sh.sent_on)}</span>
                <span role="cell">{vnd(sh.ship_fee)}</span>
                <span role="cell">{pair.cost_label}</span>
              </div>
            ))}
          </div>
          <p className="sa-hint">Chi phí mẫu = số lượng × (giá vốn + đóng gói của sản phẩm) + phí ship. Giá vốn lấy từ sheet sản phẩm. Không có cột phí book KOL: phí này không tính vào chi phí mẫu. Bỏ trống một sản phẩm của KOL nghĩa là chưa gửi mẫu.</p>
        </section>
      ) : null}

      {step === 2 && preview && counts ? (
        <section className="sa-card" data-testid="ks-step2">
          <h3 className="sa-h2">
            Kiểm tra: {counts.sample_rows_valid} dòng hợp lệ, {counts.sample_rows_rejected} dòng lỗi
          </h3>
          {rejections.map((c, i) => (
            <div className="ks-check ks-check--bad" key={i}>
              <b>{c.row}</b>
              <span>{c.sku}</span>
              <span>{c.column}</span>
              <span>{c.reason}</span>
            </div>
          ))}
          {rejections.length === 0 ? <div className="ks-check ks-check--ok">Mọi dòng của trang Mẫu KOL hợp lệ.</div> : null}
          <p className="sa-hint">Dòng lỗi không chặn các dòng hợp lệ (“Tiếp tục với {counts.sample_rows_valid} dòng hợp lệ”), như sheet giá vốn. Một KOL × sản phẩm có dòng lỗi thì giữ nguyên các lần gửi cũ.</p>
          <button className="sa-btn sa-btn--primary" onClick={() => setStep(3)} type="button">
            Tiếp tục với {counts.sample_rows_valid} dòng hợp lệ
          </button>
        </section>
      ) : null}

      {step === 3 && preview && counts ? (
        <section className="sa-card" data-testid="ks-step3">
          <h3 className="sa-h2">So sánh cũ → mới và hệ quả</h3>
          {preview.sample_diffs.length === 0 ? <p className="sa-hint">Trang Mẫu KOL không đổi gì so với số liệu hiện tại ({counts.sample_rows_unchanged} dòng giữ nguyên).</p> : null}
          {preview.sample_diffs.map((d) => (
            <div className="ks-diff" key={d.scope_ref}>
              <div>
                <b>{d.handle}</b> <span>{d.sku}</span> <span className={`sa-chip sa-chip--${d.tag === "Mới" ? "up" : "info"}`}>{d.tag}</span>
              </div>
              <div className="ks-diff__cells">
                <div>
                  <span className="sa-hint">Các lần gửi</span>
                  <span>
                    <span className="sd-muted">{shipText(d.old)}</span> → <b>{shipText(d.new)}</b>
                  </span>
                </div>
              </div>
              <div className="sa-hint">{d.effect}</div>
            </div>
          ))}
          {counts.skus_changed > 0 || counts.months_changed > 0 ? (
            <p className="sa-hint" data-testid="ks-other">
              Cùng tệp này còn đổi {counts.skus_changed} SKU và {counts.months_changed} tháng mục tiêu; Áp dụng sẽ áp dụng cả những thay đổi đó (xem ở các bước Thông số shop).
            </p>
          ) : null}
          <b data-testid="ks-cards">
            {preview.affected.total} thẻ đề xuất đang mở ({preview.affected.proposals} đề xuất, {preview.affected.action_cards} thẻ hành động) sẽ được tính lại sau khi áp dụng.
          </b>
          <button className="sa-btn sa-btn--primary" onClick={() => setStep(4)} type="button">
            Tiếp tục
          </button>
        </section>
      ) : null}

      {step === 4 && preview ? (
        <section className="sa-card" data-testid="ks-step4">
          <h3 className="sa-h2">Áp dụng với lý do</h3>
          <p className="sa-hint">
            Mỗi KOL × sản phẩm có thay đổi tạo một phiên bản mới của quy tắc Mẫu KOL. Chọn một lý do; mọi số trong Phân tích › KOL và các thẻ Gửi mẫu tính lại.
          </p>
          <div className="sb-tabs" role="radiogroup" aria-label="Lý do">
            {reasons.map((r) => (
              <button aria-checked={reason === r} className={`sb-pill ${reason === r ? "sb-pill--on" : ""}`} key={r} onClick={() => setReason(r)} role="radio" type="button">
                {r}
              </button>
            ))}
          </div>
          <button className="sa-btn sa-btn--primary" data-testid="ks-apply" disabled={!canEdit || !reason || !!applied || busy} onClick={() => void apply()} type="button">
            Áp dụng
          </button>
          {applied ? (
            <p className="sd-ack-line" data-testid="ks-applied" role="status">
              <b>Đã áp dụng Mẫu KOL.</b> {applied.samples_changed} cặp KOL × sản phẩm đổi, {applied.versions_written} phiên bản được ghi, {applied.affected.total} thẻ đề xuất được tính lại. Khôi phục một phiên bản tạo phiên bản mới sao chép nó, như sheet giá vốn.
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
