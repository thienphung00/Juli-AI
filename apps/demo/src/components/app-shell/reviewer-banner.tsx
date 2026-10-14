"use client";

import { platformLabel, REVIEWER_BANNER_COPY, reviewerExpiryCopy } from "../../lib/reviewer/copy";
import type { ReviewerRecord } from "../../lib/reviewer/session";

/**
 * The partner trial account's persistent strip (fast track P32-A, AC-32.7):
 * on every page of the seller shell, including the run-focus layout.
 */
export function ReviewerBanner({ reviewer }: { readonly reviewer: ReviewerRecord }) {
  const expiry = reviewerExpiryCopy(reviewer.expiresAt);
  const platform = platformLabel(reviewer.platform);
  return (
    <p className="demo-notice reviewer-banner" data-testid="reviewer-banner" role="status">
      <strong>{REVIEWER_BANNER_COPY}</strong>
      {platform || expiry ? (
        <span className="reviewer-banner__meta">
          {" · "}
          {[platform ? `Đối tác ${platform}` : null, expiry].filter(Boolean).join(" · ")}
        </span>
      ) : null}
    </p>
  );
}
