"use client";

import { useEffect, useId, useRef, useState } from "react";

import { REASON_NOTE_MAX } from "../../lib/quyet-dinh/reasons";

/**
 * The two sheets of a Shopee card: "Bỏ qua" with the ADR-107 decision-5 reasons (one quick choice,
 * optional - no choice is recorded as `unspecified`) and "Yêu cầu chỉnh" (a note, required; the
 * slider values being viewed travel with it). Same overlay look as the TikTok reason dialog.
 */

export const DISMISS_REASONS: readonly (readonly [string, string])[] = [
  ["not_needed", "Sản phẩm này không cần thay đổi"],
  ["wrong_analysis", "Phân tích/gợi ý sai"],
  ["not_understood", "Không hiểu gợi ý (cần tìm hiểu thêm)"],
  ["already_done", "Tôi đã làm việc này rồi"],
  ["later", "Để sau"],
];

function useEscape(open: boolean, onCancel: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);
}

export function DismissDialog({ open, busy, error, onCancel, onSubmit }: { readonly open: boolean; readonly busy: boolean; readonly error: string | null; readonly onCancel: () => void; readonly onSubmit: (choice: { readonly reasonCode: string | null; readonly note: string | null }) => void }) {
  const id = useId();
  const [picked, setPicked] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const first = useRef<HTMLInputElement | null>(null);
  useEscape(open, onCancel);
  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="qv-overlay" data-testid="sd-dismiss-dialog">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className="qv-dialog" role="dialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          Bỏ qua thẻ này?
        </h3>
        <p className="qv-dialog__body">Thẻ rời khỏi Đề xuất.</p>
        <fieldset className="qv-reasons">
          <legend>
            Vì sao? <span>(không bắt buộc)</span>
          </legend>
          {DISMISS_REASONS.map(([code, label], index) => (
            <label className="qv-reason" key={code}>
              <input checked={picked === code} name={`${id}-reason`} onChange={() => setPicked(code)} ref={index === 0 ? first : undefined} type="radio" value={code} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <label className="qv-dialog__note">
          Ghi chú thêm (không bắt buộc)
          <input maxLength={REASON_NOTE_MAX} onChange={(event) => setNote(event.target.value)} type="text" value={note} />
        </label>
        {error ? (
          <p className="qv-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" disabled={busy} onClick={() => onSubmit({ reasonCode: picked, note: note.trim() || null })} type="button">
            Bỏ qua thẻ
          </button>
        </div>
      </div>
    </div>
  );
}

export function RequestChangeDialog({ open, busy, error, viewing, onCancel, onSubmit }: { readonly open: boolean; readonly busy: boolean; readonly error: string | null; readonly viewing: string; readonly onCancel: () => void; readonly onSubmit: (note: string) => void }) {
  const id = useId();
  const [note, setNote] = useState("");
  useEscape(open, onCancel);
  if (!open) return null;
  return (
    <div className="qv-overlay" data-testid="sd-request-dialog">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className="qv-dialog" role="dialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          Yêu cầu chỉnh thẻ này
        </h3>
        <p className="qv-dialog__body">Các giá trị bạn đang xem được gửi kèm.</p>
        {viewing ? (
          <p className="sd-viewing" data-testid="sd-request-viewing">
            Giá trị đang xem: {viewing}
          </p>
        ) : null}
        <label className="qv-dialog__note">
          Bạn muốn chỉnh gì?
          <textarea maxLength={1500} onChange={(event) => setNote(event.target.value)} rows={3} value={note} />
        </label>
        {error ? (
          <p className="qv-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" disabled={busy || note.trim() === ""} onClick={() => onSubmit(note.trim())} type="button">
            Gửi yêu cầu
          </button>
        </div>
      </div>
    </div>
  );
}

/** Why Ops takes a card off the list ("Gỡ thẻ"); codes match `WITHDRAW_REASONS` in the backend. */
export const WITHDRAW_REASONS: readonly (readonly [string, string])[] = [
  ["not_fit", "Không phù hợp"],
  ["duplicate", "Trùng thẻ khác"],
  ["done_outside", "Đã làm ngoài Juli"],
  ["other", "Khác"],
];

/** In-page confirmation for "Gỡ thẻ" (one card or a selection): a reason select, an optional note. */
export function WithdrawDialog({ open, count, label, busy, error, onCancel, onSubmit }: { readonly open: boolean; readonly count: number; readonly label: string; readonly busy: boolean; readonly error: string | null; readonly onCancel: () => void; readonly onSubmit: (choice: { readonly reasonCode: string; readonly note: string | null }) => void }) {
  const id = useId();
  const [reason, setReason] = useState("not_fit");
  const [note, setNote] = useState("");
  useEscape(open, onCancel);
  if (!open) return null;
  return (
    <div className="qv-overlay" data-testid="sd-withdraw-dialog">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className="qv-dialog" role="dialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          {count > 1 ? `Gỡ ${count} thẻ đã chọn?` : `Gỡ thẻ ${label}?`}
        </h3>
        <p className="qv-dialog__body">Thẻ đóng lại (đã gỡ) và rời khỏi Đề xuất; thẻ kế tiếp của sản phẩm lên thay. Việc này được ghi lại cùng lý do.</p>
        <label className="qv-dialog__note">
          Lý do
          <select data-testid="sd-withdraw-reason" onChange={(event) => setReason(event.target.value)} value={reason}>
            {WITHDRAW_REASONS.map(([code, text]) => (
              <option key={code} value={code}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label className="qv-dialog__note">
          Ghi chú thêm (không bắt buộc)
          <input maxLength={300} onChange={(event) => setNote(event.target.value)} type="text" value={note} />
        </label>
        {error ? (
          <p className="qv-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" data-testid="sd-withdraw-confirm" disabled={busy} onClick={() => onSubmit({ reasonCode: reason, note: note.trim() || null })} type="button">
            {count > 1 ? `Gỡ ${count} thẻ` : "Gỡ thẻ"}
          </button>
        </div>
      </div>
    </div>
  );
}
