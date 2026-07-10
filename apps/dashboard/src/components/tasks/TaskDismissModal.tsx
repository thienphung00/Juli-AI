"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import {
  TASK_DISMISS_REASON_LABELS,
  TASK_DISMISS_REASONS,
  type TaskDismissReason,
} from "@/lib/task-executor/dismiss-reasons";

export function TaskDismissModal({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: (reason: TaskDismissReason, note?: string) => void;
}) {
  const [reason, setReason] = useState<TaskDismissReason | null>(null);
  const [note, setNote] = useState("");

  const canSubmit =
    reason !== null && (reason !== "other" || note.trim().length > 0);

  const modal = (
    <div
      className="fixed inset-0 z-[110] flex items-end justify-center p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:items-center"
      data-testid="task-dismiss-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="task-dismiss-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label="Hủy bỏ qua nhiệm vụ"
        onClick={onCancel}
      />
      <div
        className="card relative z-10 w-full max-w-md p-4"
        data-testid="task-dismiss-dialog"
      >
        <h2
          id="task-dismiss-title"
          className="text-base font-bold"
          style={{ color: "var(--foreground)" }}
        >
          Vì sao bạn bỏ qua nhiệm vụ này?
        </h2>
        <p className="text-muted mt-2 text-sm">
          Chọn một lý do để Juli cải thiện gợi ý trong tương lai.
        </p>

        <fieldset className="mt-4 space-y-2">
          <legend className="sr-only">Lý do bỏ qua</legend>
          {TASK_DISMISS_REASONS.map((value) => (
            <label
              key={value}
              className="flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)" }}
            >
              <input
                type="radio"
                name="task-dismiss-reason"
                value={value}
                checked={reason === value}
                onChange={() => setReason(value)}
                data-testid={`task-dismiss-reason-${value}`}
                className="mt-0.5"
              />
              <span>{TASK_DISMISS_REASON_LABELS[value]}</span>
            </label>
          ))}
        </fieldset>

        {reason === "other" && (
          <label className="mt-4 block text-sm">
            <span className="font-medium">Ghi chú (bắt buộc)</span>
            <textarea
              className="field-input mt-1 w-full rounded-lg px-3 py-2 text-sm"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              data-testid="task-dismiss-note"
              placeholder="Mô tả ngắn lý do khác…"
            />
          </label>
        )}

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="btn-secondary flex-1"
            data-testid="task-dismiss-cancel"
            onClick={onCancel}
          >
            Hủy
          </button>
          <button
            type="button"
            className="btn-primary flex-1"
            data-testid="task-dismiss-submit"
            disabled={!canSubmit}
            onClick={() => {
              if (!reason) return;
              onConfirm(reason, reason === "other" ? note.trim() : undefined);
            }}
          >
            Xác nhận bỏ qua
          </button>
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") {
    return modal;
  }

  return createPortal(modal, document.body);
}
