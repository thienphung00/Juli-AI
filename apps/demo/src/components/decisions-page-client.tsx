"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { resolveTab } from "../lib/quyet-dinh/copy";
import { readActiveShop, type ActiveShop } from "../lib/shop-session";
import { readAuthSession, type AuthSession } from "../lib/supabase-auth";
import type { OnboardingStatus } from "../lib/onboarding/api-client";
import { NoShopSampleStrip } from "./app-shell/no-shop-sample-strip";
import { useDemoResetEpoch } from "./demo-state";
import { ShopOnboardingStrip } from "./onboarding/onboarding-strip";
import { resolveMeasureTab } from "./quyet-dinh/quyet-dinh-view";
import { SampleQuyetDinh } from "./quyet-dinh/sample-quyet-dinh";
import { SignedInQuyetDinh } from "./quyet-dinh/signed-in-quyet-dinh";

/**
 * The /decisions session split (issue #1909, ADR-094). A stored real
 * Supabase session (`lib/supabase-auth.ts`) selects the signed-in branch —
 * `SignedInQuyetDinh` (AC-8.7, ADR-109 d.6/8–13), the one Decisions module allowed to call
 * authenticated `/v1/*` routes. A session with no acting shop (P13) and no
 * session at all both render the same P10 screens as
 * a sample ("Bản minh họa", `SampleQuyetDinh`) over in-memory fixture
 * clients: it stays inside a module graph that reaches no network call site
 * (ADR-094 decision 1, `replay-module-graph.test.ts`).
 *
 * The session is resolved in an effect (same `undefined | null | session`
 * pattern as `app/auth/connect-shop/page.tsx`), never during render: the
 * server has no `sessionStorage`, and resolving before first paint would
 * either flash the fixture branch at a signed-in seller or desync
 * hydration.
 */
export function DecisionsPageClient() {
  const searchParams = useSearchParams();

  const router = useRouter();
  // "Làm mới Demo" puts the sample back: a new epoch remounts its in-memory store.
  const resetEpoch = useDemoResetEpoch();
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
  // P17: while Juli reads a newly connected shop, every onboarding poll re-reads
  // the cards so quick-scan and full cards appear as soon as they exist.
  const [cardsRefresh, setCardsRefresh] = useState(0);
  // The first read lands with the page's own card read, so only later polls re-read.
  const onboardingReads = useRef(0);
  const onOnboardingStatus = useCallback((status: OnboardingStatus) => {
    onboardingReads.current += 1;
    if (status.active && onboardingReads.current > 1) setCardsRefresh((tick) => tick + 1);
  }, []);

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

  const query = {
    tab: resolveTab(params.get("tab")),
    run: params.get("run"),
    rulesOpen: params.get("quy-tac") === "1",
    measureTab: resolveMeasureTab(params.get("moc")),
    // Phân tích's "Xem đề xuất ›" / "Xem N đề xuất ›" (ADR-109 Amendment 2 d.4).
    focusCard: params.get("the"),
    focusMetric: params.get("nhom"),
  };

  if (session && !shop) {
    // P13: signed in, no TikTok Shop yet → the sample (in-memory clients, no
    // request, nothing written for the seller), under the connect strip.
    return (
      <>
        <NoShopSampleStrip />
        <SampleQuyetDinh key={resetEpoch} onNavigate={onNavigate} query={query} />
      </>
    );
  }

  if (session) {
    return (
      <>
        {shop ? (
          <ShopOnboardingStrip onStatus={onOnboardingStatus} shopId={shop.id} token={session.accessToken} />
        ) : null}
        <SignedInQuyetDinh
          cardsRefresh={cardsRefresh}
          onNavigate={onNavigate}
          query={query}
          shop={shop}
          token={session.accessToken}
        />
      </>
    );
  }

  return <SampleQuyetDinh key={resetEpoch} onNavigate={onNavigate} query={query} />;
}
