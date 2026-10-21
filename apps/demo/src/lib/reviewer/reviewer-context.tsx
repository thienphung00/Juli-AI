"use client";

/**
 * Reviewer mode (fast track P32-A, D42): the app as a partner platform's
 * reviewer sees it — the reference shop masked, a persistent banner, every
 * write control read-only except Duyệt, which runs a simulation.
 *
 * Entered from the record the password sign-in stores
 * (`lib/reviewer/session.ts`), then confirmed with `GET /v1/reviewer/me`
 * on every load: an expired / revoked / unknown account is signed out and
 * sent to the sign-in page with the reason. Presentation only — the API
 * refuses every reviewer write on its own (contract §2).
 */

import { useEffect, useState, type ReactNode } from "react";

import { clearActiveShop, readActiveShop } from "../shop-session";
import { readAuthSession } from "../supabase-auth";
import { fetchReviewerMe, type ReviewerMeResult } from "./api-client";
import { ReviewerContext, clearReviewerSignIn, reviewerSignInHref } from "./mode";
import { clearReviewerRecord, readReviewerRecord, storeReviewerRecord, type ReviewerRecord } from "./session";

export { clearReviewerSignIn, reviewerSignInHref, StaticReviewerProvider, useReviewer } from "./mode";

type MeFetcher = (token: string) => Promise<ReviewerMeResult>;

const defaultFetchMe: MeFetcher = (token) => fetchReviewerMe(token);
const defaultRedirect = (href: string) => window.location.assign(href);

export function ReviewerProvider({
  children,
  fetchMe = defaultFetchMe,
  redirect = defaultRedirect,
}: {
  readonly children: ReactNode;
  readonly fetchMe?: MeFetcher;
  readonly redirect?: (href: string) => void;
}) {
  const [reviewer, setReviewer] = useState<ReviewerRecord | null>(null);

  useEffect(() => {
    const record = readReviewerRecord();
    const session = readAuthSession();
    if (!record) return;
    if (!session) {
      clearReviewerRecord();
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => !cancelled && setReviewer(record), 0);
    void fetchMe(session.accessToken).then((result) => {
      if (cancelled) return;
      if (result.status === "reviewer") {
        const sample = result.me.shop === null;
        const next: ReviewerRecord = {
          platform: result.me.platform,
          expiresAt: result.me.expiresAt,
          sample,
          ...(result.me.mode ? { mode: result.me.mode } : {}),
          ...(result.me.writesEnabled ? { writesEnabled: true } : {}),
        };
        storeReviewerRecord(next);
        setReviewer(next);
        // P32-D: the pin was removed since sign-in — drop the stale shop and
        // reload into the sample (its alias would only be refused now).
        if (sample && readActiveShop()) {
          clearActiveShop();
          redirect("/");
        }
      } else if (result.status === "not_reviewer") {
        clearReviewerRecord();
        setReviewer(null);
      } else if (result.status === "denied" && result.denial !== "read_only" && result.denial !== "unconfigured") {
        clearReviewerSignIn();
        setReviewer(null);
        redirect(reviewerSignInHref(result.denial));
      }
      // A network error keeps the stored record: the banner stays, the API still guards.
    });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [fetchMe, redirect]);

  return <ReviewerContext.Provider value={{ reviewer }}>{children}</ReviewerContext.Provider>;
}
