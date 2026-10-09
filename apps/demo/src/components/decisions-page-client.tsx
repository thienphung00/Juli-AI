"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { resolveTab } from "../lib/quyet-dinh/copy";
import { readActiveShop, type ActiveShop } from "../lib/shop-session";
import { readAuthSession, type AuthSession } from "../lib/supabase-auth";
import { SignedInQuyetDinh, resolveMeasureTab } from "./quyet-dinh/signed-in-quyet-dinh";
import { RecommendationsView } from "./recommendations-view";

/**
 * The /decisions session split (issue #1909, ADR-094). A stored real
 * Supabase session (`lib/supabase-auth.ts`) selects the signed-in branch —
 * `SignedInQuyetDinh` (AC-8.7, ADR-109 d.6/8–13), the one Decisions module allowed to call
 * authenticated `/v1/*` routes. No session keeps today's anonymous
 * fixture branch, `RecommendationsView`, byte-for-byte: it stays inside a
 * module graph that reaches no network call site (ADR-094 decision 1).
 *
 * The session is resolved in an effect (same `undefined | null | session`
 * pattern as `app/auth/connect-shop/page.tsx`), never during render: the
 * server has no `sessionStorage`, and resolving before first paint would
 * either flash the fixture branch at a signed-in seller or desync
 * hydration.
 */
export function DecisionsPageClient() {
  const searchParams = useSearchParams();
  const load = searchParams.get("load");
  const initialLoadState = load === "error" ? "error" : "ready";

  const router = useRouter();
  // Quyết định's state lives in /decisions' query string. The UI follows the
  // href it asked for straight away; `router.replace` then moves the URL. With
  // the production build a page first loaded WITH a query (a deep link such as
  // ?tab=do-luong) never committed `router.replace` (AC-10.3 e2e) — the UI
  // must not wait on it (DEBT P10-C).
  const [pending, setPending] = useState<{ href: string; base: string } | null>(null);
  const base = searchParams.toString();
  const onNavigate = useCallback(
    (href: string) => {
      setPending({ href, base });
      router.replace(href, { scroll: false });
    },
    [router, base],
  );
  const params = pending && pending.base === base ? new URLSearchParams(pending.href.split("?")[1] ?? "") : searchParams;
  const [session, setSession] = useState<AuthSession | null | undefined>(
    undefined,
  );
  const [shop, setShop] = useState<ActiveShop | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setShop(readActiveShop());
      setSession(readAuthSession());
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  if (session === undefined) {
    return <p className="demo-kicker">Đang tải đề xuất…</p>;
  }

  if (session) {
    return (
      <SignedInQuyetDinh
        onNavigate={onNavigate}
        query={{
          tab: resolveTab(params.get("tab")),
          run: params.get("run"),
          rulesOpen: params.get("quy-tac") === "1",
          measureTab: resolveMeasureTab(params.get("moc")),
        }}
        shop={shop}
        token={session.accessToken}
      />
    );
  }

  return <RecommendationsView initialLoadState={initialLoadState} />;
}
