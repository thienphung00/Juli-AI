"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { readAuthSession, type AuthSession } from "../lib/supabase-auth";
import { RecommendationsView } from "./recommendations-view";
import { SignedInDecisions } from "./signed-in-decisions";

/**
 * The /decisions session split (issue #1909, ADR-094). A stored real
 * Supabase session (`lib/supabase-auth.ts`) selects the signed-in branch —
 * `SignedInDecisions`, the one Decisions module allowed to call
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

  const [session, setSession] = useState<AuthSession | null | undefined>(
    undefined,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSession(readAuthSession());
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  if (session === undefined) {
    return <p className="demo-kicker">Đang tải đề xuất…</p>;
  }

  if (session) {
    return <SignedInDecisions token={session.accessToken} />;
  }

  return <RecommendationsView initialLoadState={initialLoadState} />;
}
