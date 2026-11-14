"use client";

import { useState } from "react";

import { confirmUnsubscribe } from "../../lib/shopee-analytics/stock";

/**
 * The stock e-mail's unsubscribe page (P100 Part S): opening it changes nothing; the button does,
 * for the one member the signed token names.
 */
export function UnsubscribeConfirm({ token, fetchImpl }: { readonly token: string | null; readonly fetchImpl?: typeof fetch }) {
  const [state, setState] = useState<"ask" | "busy" | "done" | "failed">("ask");
  if (!token) {
    return (
      <main className="unsub-page" data-testid="unsub-page">
        <h1>Liên kết không hợp lệ</h1>
      </main>
    );
  }
  if (state === "done") {
    return (
      <main className="unsub-page" data-testid="unsub-page">
        <h1>Đã huỷ nhận email báo cáo tồn kho</h1>
      </main>
    );
  }
  return (
    <main className="unsub-page" data-testid="unsub-page">
      <h1>Huỷ nhận email báo cáo tồn kho?</h1>
      {state === "failed" ? (
        <p className="qv-inline-error" role="alert">
          Chưa huỷ được. Thử lại sau.
        </p>
      ) : null}
      <button
        className="qv-btn qv-btn--primary"
        disabled={state === "busy"}
        onClick={() => {
          setState("busy");
          confirmUnsubscribe(token, fetchImpl).then(
            (ok) => setState(ok ? "done" : "failed"),
            () => setState("failed"),
          );
        }}
        type="button"
      >
        Huỷ nhận email này
      </button>
    </main>
  );
}
