"use client";

import { useEffect, useId, useState } from "react";

import {
  LEGAL_TERMS_DATE,
  PRIVACY_POLICY_URL,
  TERMS_OF_SERVICE_URL,
  acceptTerms,
  fetchPrivacy,
  viDate,
} from "../../lib/privacy/legal";

/**
 * P50 (D60.8): the in-app re-acceptance of the D60 terms. Pattern:
 * `term-strip.tsx`. Shown to a signed-in seller whose `GET /v1/me/privacy`
 * says `needs_terms_acceptance`; the Điều 11 checkbox is the separate
 * acceptance of the liability clause (D60.4) and gates the button. A failed
 * read shows nothing: this strip never blocks the app.
 */
export const TERMS_UPDATED_TEXT = `Điều khoản dịch vụ và Chính sách bảo mật đã cập nhật ngày ${viDate(LEGAL_TERMS_DATE)}.`;
export const LIABILITY_CHECKBOX_LABEL =
  "Tôi đã đọc và đồng ý riêng với Điều 11 (Giới hạn trách nhiệm) của Điều khoản dịch vụ";
export const ACCEPT_ERROR_TEXT = "Chưa lưu được. Bạn thử lại sau ít phút nhé.";

export function TermsAcceptanceStrip({
  token,
  fetchImpl = fetch,
}: {
  readonly token: string;
  readonly fetchImpl?: typeof fetch;
}) {
  const id = useId();
  const [needed, setNeeded] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let live = true;
    fetchPrivacy(token, fetchImpl)
      .then((state) => {
        if (live) setNeeded(state.needs_terms_acceptance);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [token, fetchImpl]);

  if (!needed) return null;

  const onAccept = () => {
    setBusy(true);
    setError(false);
    acceptTerms(token, fetchImpl)
      .then((state) => setNeeded(state.needs_terms_acceptance))
      .catch(() => setError(true))
      .finally(() => setBusy(false));
  };

  const checkboxId = `${id}-dieu-11`;
  return (
    <section aria-label="Điều khoản đã cập nhật" className="terms-strip" data-testid="terms-acceptance-strip">
      <p className="terms-strip__text">
        {TERMS_UPDATED_TEXT}{" "}
        <a href={TERMS_OF_SERVICE_URL} rel="noopener" target="_blank">
          Xem Điều khoản dịch vụ
        </a>
        {" · "}
        <a href={PRIVACY_POLICY_URL} rel="noopener" target="_blank">
          Xem Chính sách bảo mật
        </a>
      </p>
      <div className="terms-strip__row">
        <label className="terms-strip__check" htmlFor={checkboxId}>
          <input
            checked={checked}
            id={checkboxId}
            onChange={(event) => setChecked(event.target.checked)}
            required
            type="checkbox"
          />
          <span>{LIABILITY_CHECKBOX_LABEL}</span>
        </label>
        <button className="qv-btn qv-btn--primary" disabled={!checked || busy} onClick={onAccept} type="button">
          Đồng ý
        </button>
      </div>
      {error ? (
        <p className="terms-strip__error" role="alert">
          {ACCEPT_ERROR_TEXT}
        </p>
      ) : null}
    </section>
  );
}
