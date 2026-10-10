"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  DECLINE_REASONS,
  REASON_NOTE_MAX,
  REJECT_REASONS,
  REVERT_REASONS,
  type ReasonChoice,
  type ReasonOption,
} from "../../lib/quyet-dinh/reasons";

/**
 * The reason dialogs of ADR-109 Amendment 1 d.7 (`Revert.dc.html`,
 * `Decline.dc.html`): one reason REQUIRED (radio; the confirm button stays
 * disabled until one is chosen), an optional note (≤ 300), then the caller's
 * action. No "Để sau". Esc / the cancel button close without acting.
 */

export type ReasonDialogMode = "reject" | "skip" | "revert";

interface ModeCopy {
  readonly title: string;
  readonly legend: string;
  readonly placeholder: string;
  /** Text after "Vì sao?" ("(chọn một)" since a0382006 on Từ chối / Không thực hiện). */
  readonly hint: string;
  readonly cancel: string;
  readonly submit: string;
  readonly reasons: readonly ReasonOption[];
}

const COPY: Readonly<Record<ReasonDialogMode, ModeCopy>> = {
  reject: {
    title: "Từ chối thẻ này?",
    legend: "Vì sao?",
    placeholder: "Ví dụ: shop không dùng từ “cao cấp” trong tên sản phẩm",
    hint: "(chọn một)",
    cancel: "Quay lại",
    submit: "Từ chối thẻ",
    reasons: REJECT_REASONS,
  },
  skip: {
    title: "Không thực hiện thay đổi này?",
    legend: "Vì sao?",
    placeholder: "Ví dụ: shop không dùng từ “cao cấp” trong tên sản phẩm",
    hint: "(chọn một)",
    cancel: "Quay lại",
    submit: "Đồng ý",
    reasons: DECLINE_REASONS,
  },
  revert: {
    title: "Hoàn tác thay đổi này?",
    legend: "Vì sao bạn muốn hoàn tác?",
    placeholder: "Ví dụ: khách nhắn hỏi về tên sản phẩm mới",
    hint: "(chọn một · bắt buộc)",
    cancel: "Huỷ, giữ thay đổi",
    submit: "Bắt đầu hoàn tác",
    reasons: REVERT_REASONS,
  },
};

export const REJECT_DIALOG_BODY = "Thẻ sẽ rời khỏi Đề xuất. Juli không thay đổi gì trên sản phẩm.";
export const SKIP_DIALOG_BODY = "Khi đồng ý, gợi ý sẽ không quay lại";

/** "Juli sẽ khôi phục Tiêu đề và Mô tả cũ của <strong>…</strong>, …" (Revert.dc.html). */
export function revertDialogBody(fieldLabels: readonly string[], productName: string): ReactNode {
  const fields =
    fieldLabels.length === 0
      ? "nội dung"
      : fieldLabels.length === 1
        ? fieldLabels[0]
        : `${fieldLabels.slice(0, -1).join(", ")} và ${fieldLabels[fieldLabels.length - 1]}`;
  return (
    <>
      Juli sẽ khôi phục {fields} cũ của <strong>{productName}</strong>, bạn xác nhận lần cuối trước khi Juli ghi. Kết
      quả đo của thay đổi này sẽ dừng.
    </>
  );
}

export interface ReasonDialogProps {
  readonly mode: ReasonDialogMode;
  readonly open: boolean;
  readonly body: ReactNode;
  /** Overrides the mode's own cancel label ("Không áp dụng nữa" keeps "Quay lại"). */
  readonly submitLabel?: string;
  readonly busy?: boolean;
  /** A failed submit's sentence, shown above the buttons. */
  readonly error?: string | null;
  readonly onCancel: () => void;
  readonly onSubmit: (choice: ReasonChoice) => void;
}

export function ReasonDialog({ mode, open, body, submitLabel, busy = false, error = null, onCancel, onSubmit }: ReasonDialogProps) {
  const copy = COPY[mode];
  const id = useId();
  const [picked, setPicked] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const firstRadio = useRef<HTMLInputElement | null>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    firstRadio.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    const previous = opener.current;
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [open, onCancel]);

  useEffect(() => {
    if (open) return;
    const timer = window.setTimeout(() => {
      setPicked(null);
      setNote("");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  if (!open) return null;
  const titleId = `${id}-title`;
  const disabled = picked === null || busy;

  return (
    <div className="qv-overlay" data-testid={`reason-dialog-${mode}`}>
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className={`qv-dialog${mode === "revert" ? " qv-dialog--revert" : ""}`}
        role="dialog"
      >
        <h3 className="qv-dialog__title" id={titleId}>
          {copy.title}
        </h3>
        <p className="qv-dialog__body">{body}</p>
        <fieldset className="qv-reasons">
          <legend>
            {copy.legend} <span>{copy.hint}</span>
          </legend>
          {copy.reasons.map((reason, index) => (
            <label className="qv-reason" key={reason.code}>
              <input
                checked={picked === reason.code}
                name={`${id}-reason`}
                onChange={() => setPicked(reason.code)}
                ref={index === 0 ? firstRadio : undefined}
                type="radio"
                value={reason.code}
              />
              <span>{reason.label}</span>
            </label>
          ))}
        </fieldset>
        <label className="qv-dialog__note">
          Ghi chú thêm (không bắt buộc)
          <input
            maxLength={REASON_NOTE_MAX}
            onChange={(event) => setNote(event.target.value)}
            placeholder={copy.placeholder}
            type="text"
            value={note}
          />
        </label>
        {error ? (
          <p className="qv-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} type="button">
            {copy.cancel}
          </button>
          <button
            className="qv-btn qv-btn--primary"
            disabled={disabled}
            onClick={() => {
              if (picked === null) return;
              const trimmed = note.trim();
              onSubmit(trimmed ? { reason_code: picked, note: trimmed } : { reason_code: picked });
            }}
            type="button"
          >
            {submitLabel ?? copy.submit}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The completion message after Từ chối / Không thực hiện / Hoàn tác (owner edit
 * a0382006, `Decline.dc.html` / `Revert.dc.html`): the green box with the title,
 * a white "Lý do bạn chọn" box (the label of the code the seller picked + what
 * Juli does with it), then the lines.
 */
export function ReasonDone({
  title,
  reason,
  lines,
  small,
}: {
  readonly title: string;
  readonly reason: ReasonOption;
  readonly lines: readonly string[];
  readonly small?: string;
}) {
  return (
    <div className="qv-done qv-done--tight" data-testid="reason-done" role="status">
      <div className="qv-done__title">{title}</div>
      <div className="qv-reason-box">
        <span className="qv-reason-box__k">Lý do bạn chọn</span>
        <span className="qv-reason-box__v">{reason.label}</span>
        <span className="qv-reason-box__learn">Lý do giúp Juli đưa ra đề xuất tốt hơn: {reason.learn}</span>
      </div>
      {lines.map((line) => (
        <div className="qv-done__text" key={line}>
          {line}
        </div>
      ))}
      {small ? <div className="qv-done__small">{small}</div> : null}
    </div>
  );
}
