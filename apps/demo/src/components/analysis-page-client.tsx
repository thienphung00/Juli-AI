"use client";

import { useEffect, useState } from "react";

import { readAuthSession, type AuthSession } from "../lib/supabase-auth";
import { SampleShopAnalysis } from "./shop-analysis/sample-shop-analysis";
import { SignedInShopAnalysis } from "./shop-analysis/signed-in-shop-analysis";

/**
 * The /analytics session split (AC-7.7), same pattern as
 * `DecisionsPageClient`: a stored Supabase session selects the signed-in
 * report; no session shows the synthetic sample, which issues no request.
 * Resolved in an effect so the server render and hydration never disagree.
 */
export function AnalysisPageClient() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);

  useEffect(() => {
    const timer = window.setTimeout(() => setSession(readAuthSession()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (session === undefined) {
    return <p className="text-muted">Đang tải phân tích…</p>;
  }

  if (session) {
    return <SignedInShopAnalysis token={session.accessToken} />;
  }

  return <SampleShopAnalysis />;
}
