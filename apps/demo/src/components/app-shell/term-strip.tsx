"use client";

import { useEffect, useState } from "react";

/**
 * D28.4: the shop's Juli term, as the seller sees it (artboard OpsShopTerm,
 * "seller thấy"). Grace (7 days after expiry): an amber reminder; read-only
 * ("chỉ xem"): a grey strip. Nothing while the term is set and running, and
 * nothing for a shop with no term yet. "Xem như shop" shows the same strip
 * through the ops view fetch (`/v1/shops/me/term` → `/view/term`).
 */
export const TERM_PATH = "/v1/shops/me/term" as const;
export const CONTACT_EMAIL = "lienhe@app-juli.com";

export interface SellerTerm {
  readonly state: "none" | "ok" | "soon" | "grace" | "read_only";
  readonly expires_on: string | null;
  readonly days_left: number | null;
  readonly grace_days_left: number | null;
}

/** "10/10/2026". */
function ddmmyyyy(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

/** The strip's text and tone for a term, or `null` when the seller sees nothing. */
export function termStrip(term: SellerTerm | null | undefined): { readonly tone: "grace" | "read_only"; readonly text: string } | null {
  if (!term) return null;
  if (term.state === "grace") {
    return {
      tone: "grace",
      text: `Gói Juli của shop đã hết hạn ngày ${ddmmyyyy(term.expires_on)}. Juli vẫn chạy thêm ${term.grace_days_left ?? 0} ngày — liên hệ ${CONTACT_EMAIL} để gia hạn.`,
    };
  }
  if (term.state === "read_only") {
    return {
      tone: "read_only",
      text: `Shop đang ở chế độ chỉ xem: Juli không tạo thẻ mới và không chạy hành động. Liên hệ ${CONTACT_EMAIL} để gia hạn.`,
    };
  }
  return null;
}

export const TERM_STRIP_STYLE = {
  grace: { color: "#5c3a00", background: "#fff4e0", borderBottom: "1px solid #f3d9a8" },
  read_only: { color: "#ffffff", background: "#4a4a55" },
} as const;

export function TermStripView({ term }: { readonly term: SellerTerm | null | undefined }) {
  const strip = termStrip(term);
  if (!strip) return null;
  return (
    <p
      data-testid="term-strip"
      data-tone={strip.tone}
      role="status"
      style={{ margin: 0, padding: "10px 16px", fontSize: 14, lineHeight: 1.45, ...TERM_STRIP_STYLE[strip.tone] }}
    >
      {strip.text}
    </p>
  );
}

export function TermStrip({
  token,
  shopId,
  fetchImpl = fetch,
}: {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}) {
  const [term, setTerm] = useState<SellerTerm | null>(null);
  useEffect(() => {
    let live = true;
    fetchImpl(TERM_PATH, {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) return;
        const body = (await response.json()) as { data?: SellerTerm };
        if (live) setTerm(body.data ?? null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [token, shopId, fetchImpl]);
  return <TermStripView term={term} />;
}
