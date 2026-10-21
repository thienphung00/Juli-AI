"use client";

/**
 * Reviewer mode's context, without any network call site (fast track P32-A),
 * so components the anonymous door can reach may ask "is this a partner
 * trial account?" (`replay-module-graph.test.ts`). The provider that confirms
 * the account with the API lives in `reviewer-context.tsx`.
 */

import { createContext, useContext, type ReactNode } from "react";

import { clearActiveShop } from "../shop-session";
import { clearAuthSession } from "../supabase-auth";
import { clearReviewerRecord, type ReviewerRecord } from "./session";

export interface ReviewerMode {
  /** The confirmed (or stored, until confirmed) reviewer; null for a seller. */
  readonly reviewer: ReviewerRecord | null;
}

export const ReviewerContext = createContext<ReviewerMode>({ reviewer: null });

export function useReviewer(): ReviewerRecord | null {
  return useContext(ReviewerContext).reviewer;
}

/** P64 (D73): the reviewer is pinned to the live TikTok sandbox shop — real data, real writes. */
export function isSandboxReviewer(reviewer: ReviewerRecord | null): boolean {
  return reviewer?.mode === "sandbox" && reviewer.sample !== true;
}

export function useSandboxReviewer(): boolean {
  return isSandboxReviewer(useReviewer());
}

/** Test seam: render a fixed reviewer without storage or network. */
export function StaticReviewerProvider({
  reviewer,
  children,
}: {
  readonly reviewer: ReviewerRecord | null;
  readonly children: ReactNode;
}) {
  return <ReviewerContext.Provider value={{ reviewer }}>{children}</ReviewerContext.Provider>;
}

/** Where a denied reviewer is sent: the password form, with the reason. */
export function reviewerSignInHref(denial: string): string {
  return `/auth/email?doi-tac=${encodeURIComponent(denial)}#doi-tac`;
}

/** Sign a reviewer out of every store (session, active shop, reviewer record). */
export function clearReviewerSignIn(): void {
  clearAuthSession();
  clearActiveShop();
  clearReviewerRecord();
}
