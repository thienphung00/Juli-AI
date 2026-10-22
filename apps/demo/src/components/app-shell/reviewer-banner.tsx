"use client";

import {
  platformLabel,
  REVIEWER_BANNER_COPY,
  REVIEWER_RESET_LABEL,
  REVIEWER_SAMPLE_BANNER_COPY,
  REVIEWER_SANDBOX_BANNER_COPY,
  reviewerExpiryCopy,
} from "../../lib/reviewer/copy";
import { isSandboxReviewer } from "../../lib/reviewer/mode";
import type { ReviewerRecord } from "../../lib/reviewer/session";

/**
 * The partner trial account's persistent strip (fast track P32-A, AC-32.7):
 * on every page of the seller shell, including the run-focus layout. With no
 * pinned shop (P32-D) it says "dữ liệu mẫu": the pages show the sample shop,
 * and (P32-E) carries "Đặt lại dữ liệu mẫu", which starts every simulated
 * decision, run and rule over.
 */
export function ReviewerBanner({
  reviewer,
  onReset,
}: {
  readonly reviewer: ReviewerRecord;
  readonly onReset?: () => void;
}) {
  const expiry = reviewerExpiryCopy(reviewer.expiresAt);
  const bannerCopy = isSandboxReviewer(reviewer)
    ? REVIEWER_SANDBOX_BANNER_COPY
    : reviewer.sample
      ? REVIEWER_SAMPLE_BANNER_COPY
      : REVIEWER_BANNER_COPY;
  const platform = platformLabel(reviewer.platform);
  return (
    <p className="demo-notice reviewer-banner" data-testid="reviewer-banner" role="status">
      <strong>{bannerCopy}</strong>
      {platform || expiry ? (
        <span className="reviewer-banner__meta">
          {" · "}
          {[platform ? `Đối tác ${platform}` : null, expiry].filter(Boolean).join(" · ")}
        </span>
      ) : null}
      {reviewer.sample && onReset ? (
        <button className="qv-btn qv-btn--secondary reviewer-banner__reset" onClick={onReset} type="button">
          {REVIEWER_RESET_LABEL}
        </button>
      ) : null}
    </p>
  );
}
