"use client";

import { useEffect, useState } from "react";

import { UnsubscribeConfirm } from "../../components/shopee-analytics/unsubscribe-confirm";

/** /huy-email#<token> — the stock e-mail's "Huỷ nhận email này"; the token stays in the fragment. */
export default function UnsubscribePage() {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const timer = window.setTimeout(() => setToken(window.location.hash.replace(/^#/, "") || null), 0);
    return () => window.clearTimeout(timer);
  }, []);
  if (token === undefined) return null;
  return <UnsubscribeConfirm token={token} />;
}
