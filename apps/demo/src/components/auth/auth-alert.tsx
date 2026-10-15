import type { ReactNode } from "react";

/** An auth-screen error: icon + text, announced (`role="alert"`). Colour is never the only signal. */
export function AuthAlert({ id, children }: { readonly id?: string; readonly children: ReactNode }) {
  return (
    <div className="auth-alert" id={id} role="alert">
      <svg
        aria-hidden="true"
        className="auth-alert__icon"
        fill="none"
        height="18"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2"
        viewBox="0 0 24 24"
        width="18"
      >
        <circle cx="12" cy="12" r="9" />
        <line x1="12" x2="12" y1="8" y2="12.5" />
        <line x1="12" x2="12" y1="16" y2="16" />
      </svg>
      <div className="auth-alert__body">{children}</div>
    </div>
  );
}

/** The spinner inside a pending button (decorative; the label says "Đang …"). */
export function AuthSpinner() {
  return <span aria-hidden="true" className="auth-spinner" />;
}
