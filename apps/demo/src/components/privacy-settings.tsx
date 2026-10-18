"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

import { applyAdMeasurementOptOut } from "../lib/privacy/ad-measurement";
import {
  PRIVACY_CONTACT_EMAIL,
  PRIVACY_POLICY_URL,
  TERMS_OF_SERVICE_URL,
  cancelDeletion,
  fetchExport,
  fetchPrivacy,
  requestDeletion,
  saveFile,
  updatePrivacy,
  viDate,
  type ExportFile,
  type PrivacyPreferenceKey,
  type PrivacyState,
} from "../lib/privacy/legal";
import { AppPageHeader } from "./app-shell/page-header";

/**
 * Cài đặt → Quyền riêng tư (P50, D60.6 / D60.10), against
 * `fasttrack/contracts/p50-privacy.md`: three preferences saved one by one
 * (optimistic, rolled back on failure), the data export, account deletion
 * with its 30-day window, and the contact e-mail. Signed-in sellers only:
 * the sample and partner trial accounts never reach this component.
 */

export const PRIVACY_TAB_LABEL = "Quyền riêng tư";

interface SwitchCopy {
  readonly key: PrivacyPreferenceKey;
  readonly label: string;
  readonly hint: string;
}

export const PRIVACY_SWITCHES: readonly SwitchCopy[] = [
  {
    key: "marketing_opt_out",
    label: "Không nhận email tiếp thị",
    hint: "Juli vẫn gửi email về tài khoản, hoá đơn và thay đổi điều khoản.",
  },
  {
    key: "ad_measurement_opt_out",
    label: "Không đo lường quảng cáo",
    hint: "Khi bật, Juli không gửi sự kiện đo lường quảng cáo cho TikTok khi bạn dùng Juli.",
  },
  {
    key: "case_study_opt_in",
    label: "Cho phép Juli nêu tên shop làm ví dụ khách hàng",
    hint: "Khi bật, Juli có thể nêu tên shop của bạn khi giới thiệu các shop đang dùng Juli.",
  },
];

export const SAVE_ERROR_TEXT = "Chưa lưu được thay đổi. Bạn thử lại sau ít phút nhé.";
export const EXPORT_ERROR_TEXT = "Chưa tải được dữ liệu. Bạn thử lại sau ít phút nhé.";
export const DELETION_ERROR_TEXT = "Chưa gửi được yêu cầu. Bạn thử lại sau ít phút nhé.";

export const DELETE_DIALOG_TITLE = "Xoá tài khoản Juli?";
export const DELETE_DIALOG_BODY = [
  "Khi bạn xác nhận, Juli khoá các thay đổi trên tài khoản và ngừng đồng bộ shop.",
  "Bạn có 30 ngày để tải dữ liệu của mình. Sau đó, dữ liệu tài khoản và dữ liệu shop bị xoá vĩnh viễn, không khôi phục được.",
  "Hoá đơn được giữ 10 năm theo luật kế toán.",
  "Trong 30 ngày đó, bạn vẫn có thể huỷ yêu cầu xoá.",
] as const;

export function deletionPendingText(scheduledFor: string): string {
  return `Tài khoản sẽ bị xoá vĩnh viễn ngày ${viDate(scheduledFor)}. Trước ngày đó, bạn vẫn tải được dữ liệu của mình.`;
}

export interface PrivacyIo {
  readonly fetchPrivacy: typeof fetchPrivacy;
  readonly updatePrivacy: typeof updatePrivacy;
  readonly fetchExport: typeof fetchExport;
  readonly requestDeletion: typeof requestDeletion;
  readonly cancelDeletion: typeof cancelDeletion;
  readonly saveFile: (file: ExportFile) => void;
}

const DEFAULT_IO: PrivacyIo = { fetchPrivacy, updatePrivacy, fetchExport, requestDeletion, cancelDeletion, saveFile };

export function PrivacySettings({
  token,
  tabs,
  io = DEFAULT_IO,
}: {
  readonly token: string;
  /** The settings tablist, rendered under the page header. */
  readonly tabs?: ReactNode;
  readonly io?: PrivacyIo;
}) {
  const [state, setState] = useState<PrivacyState | "loading" | "error">("loading");
  const [saving, setSaving] = useState<ReadonlySet<PrivacyPreferenceKey>>(new Set());
  const [saveError, setSaveError] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deletionBusy, setDeletionBusy] = useState(false);
  const [deletionError, setDeletionError] = useState(false);

  useEffect(() => {
    let live = true;
    io.fetchPrivacy(token)
      .then((next) => {
        if (live) setState(next);
      })
      .catch(() => {
        if (live) setState("error");
      });
    return () => {
      live = false;
    };
  }, [io, token]);

  const toggle = (key: PrivacyPreferenceKey) => {
    if (typeof state !== "object" || saving.has(key)) return;
    const previous = state[key];
    const next = !previous;
    setSaveError(false);
    setState({ ...state, [key]: next });
    setSaving((current) => new Set(current).add(key));
    // Stopping measurement does not wait for the server: the seller asked now.
    if (key === "ad_measurement_opt_out" && next) applyAdMeasurementOptOut(token, true);
    io.updatePrivacy(token, { [key]: next })
      .then((saved) => {
        setState((current) => (typeof current === "object" ? { ...current, [key]: saved[key] } : saved));
        if (key === "ad_measurement_opt_out") applyAdMeasurementOptOut(token, saved.ad_measurement_opt_out);
      })
      .catch(() => {
        setState((current) => (typeof current === "object" ? { ...current, [key]: previous } : current));
        setSaveError(true);
      })
      .finally(() =>
        setSaving((current) => {
          const rest = new Set(current);
          rest.delete(key);
          return rest;
        }),
      );
  };

  const onExport = () => {
    setExporting(true);
    setExportError(false);
    io.fetchExport(token)
      .then((file) => io.saveFile(file))
      .catch(() => setExportError(true))
      .finally(() => setExporting(false));
  };

  const runDeletion = (action: typeof requestDeletion) => {
    setDeletionBusy(true);
    setDeletionError(false);
    action(token)
      .then((next) => {
        setState(next);
        setDialogOpen(false);
      })
      .catch(() => setDeletionError(true))
      .finally(() => setDeletionBusy(false));
  };

  const closeDialog = useCallback(() => {
    setDialogOpen(false);
    setDeletionError(false);
  }, []);

  return (
    <section aria-labelledby="privacy-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt"
        lede="Bạn chọn cách Juli dùng thông tin của bạn, tải dữ liệu về hoặc xoá tài khoản."
        title={PRIVACY_TAB_LABEL}
        titleId="privacy-title"
      />
      {tabs}
      {state === "loading" ? (
        <p role="status">Đang tải…</p>
      ) : state === "error" ? (
        <p className="qd-error" role="alert">
          Không tải được cài đặt quyền riêng tư. Vui lòng thử lại.
        </p>
      ) : (
        <div className="privacy-settings">
          <div className="privacy-settings__group">
            <h2>Lựa chọn của bạn</h2>
            <div>
              {PRIVACY_SWITCHES.map((item) => (
                <PrivacySwitch
                  busy={saving.has(item.key)}
                  checked={state[item.key]}
                  copy={item}
                  key={item.key}
                  onToggle={() => toggle(item.key)}
                />
              ))}
            </div>
            {saveError ? (
              <p className="privacy-settings__error" role="alert">
                {SAVE_ERROR_TEXT}
              </p>
            ) : null}
          </div>

          <div className="privacy-settings__group">
            <h2>Dữ liệu của bạn</h2>
            <p>Tải về một tệp gồm thông tin tài khoản, lựa chọn quyền riêng tư và dữ liệu shop mà Juli lưu cho bạn.</p>
            <div className="privacy-settings__actions">
              <button className="qv-btn qv-btn--secondary" disabled={exporting} onClick={onExport} type="button">
                {exporting ? "Đang chuẩn bị tệp…" : "Tải dữ liệu của tôi"}
              </button>
            </div>
            {exportError ? (
              <p className="privacy-settings__error" role="alert">
                {EXPORT_ERROR_TEXT}
              </p>
            ) : null}
          </div>

          <div className="privacy-settings__group">
            <h2>Xoá tài khoản</h2>
            {state.deletion_scheduled_for ? (
              <>
                <p className="privacy-settings__pending" data-testid="deletion-pending" role="status">
                  {deletionPendingText(state.deletion_scheduled_for)}
                </p>
                <div className="privacy-settings__actions">
                  <button
                    className="qv-btn qv-btn--secondary"
                    disabled={deletionBusy}
                    onClick={() => runDeletion(io.cancelDeletion)}
                    type="button"
                  >
                    Huỷ yêu cầu xoá
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>Juli giữ dữ liệu 30 ngày để bạn tải về, sau đó xoá vĩnh viễn.</p>
                <div className="privacy-settings__actions">
                  <button className="qv-btn qv-btn--secondary" onClick={() => setDialogOpen(true)} type="button">
                    Xoá tài khoản
                  </button>
                </div>
              </>
            )}
            {deletionError && !dialogOpen ? (
              <p className="privacy-settings__error" role="alert">
                {DELETION_ERROR_TEXT}
              </p>
            ) : null}
          </div>

          <div className="privacy-settings__group">
            <h2>Liên hệ</h2>
            <p>
              Cần hỗ trợ về dữ liệu cá nhân? Gửi email tới{" "}
              <a href={`mailto:${PRIVACY_CONTACT_EMAIL}`}>{PRIVACY_CONTACT_EMAIL}</a>, Juli trả lời trong 2 ngày làm việc.
              Xem thêm <a href={PRIVACY_POLICY_URL}>Chính sách bảo mật</a> và{" "}
              <a href={TERMS_OF_SERVICE_URL}>Điều khoản dịch vụ</a>.
            </p>
          </div>
        </div>
      )}
      <DeleteAccountDialog
        busy={deletionBusy}
        error={dialogOpen && deletionError ? DELETION_ERROR_TEXT : null}
        onCancel={closeDialog}
        onConfirm={() => runDeletion(io.requestDeletion)}
        open={dialogOpen}
      />
    </section>
  );
}

function PrivacySwitch({
  copy,
  checked,
  busy,
  onToggle,
}: {
  readonly copy: SwitchCopy;
  readonly checked: boolean;
  readonly busy: boolean;
  readonly onToggle: () => void;
}) {
  const id = useId();
  return (
    <div className="privacy-switch">
      <span className="privacy-switch__text">
        <span id={`${id}-label`}>{copy.label}</span>
        <span className="privacy-switch__hint" id={`${id}-hint`}>
          {copy.hint}
        </span>
      </span>
      <button
        aria-busy={busy || undefined}
        aria-checked={checked}
        aria-describedby={`${id}-hint`}
        aria-labelledby={`${id}-label`}
        className="privacy-switch__control"
        disabled={busy}
        onClick={onToggle}
        role="switch"
        type="button"
      />
    </div>
  );
}

function DeleteAccountDialog({
  open,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  readonly open: boolean;
  readonly busy: boolean;
  readonly error: string | null;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}) {
  const id = useId();
  const cancelButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement;
    cancelButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener instanceof HTMLElement) opener.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;
  const titleId = `${id}-title`;
  return (
    <div className="qv-overlay" data-testid="delete-account-dialog">
      <div aria-labelledby={titleId} aria-modal="true" className="qv-dialog" role="dialog">
        <h3 className="qv-dialog__title" id={titleId}>
          {DELETE_DIALOG_TITLE}
        </h3>
        {DELETE_DIALOG_BODY.map((line) => (
          <p className="qv-dialog__body" key={line}>
            {line}
          </p>
        ))}
        {error ? (
          <p className="qv-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} ref={cancelButton} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" disabled={busy} onClick={onConfirm} type="button">
            Xoá tài khoản
          </button>
        </div>
      </div>
    </div>
  );
}
