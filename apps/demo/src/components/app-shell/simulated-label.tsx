"use client";

import type { ReactNode } from "react";

import { REVIEWER_SIMULATED_LABEL, REVIEWER_SIMULATED_SETTINGS_LABEL } from "../../lib/reviewer/copy";
import { useReviewer } from "../../lib/reviewer/mode";

/**
 * P32-E (D42 amendment 2): the label on every simulated write of the partner
 * trial account in the sample shop — "Mô phỏng · không gửi tới TikTok", or
 * "Mô phỏng · không lưu" for settings. Renders nothing for anyone else (a
 * seller, the signed-out sample, a reviewer pinned to a real shop).
 */
export function SimulatedLabel({
  kind = "tiktok",
  children,
}: {
  readonly kind?: "tiktok" | "settings";
  readonly children?: ReactNode;
}) {
  const reviewer = useReviewer();
  if (!reviewer?.sample) return null;
  return (
    <p className="reviewer-sim__label simulated-label" data-kind={kind} data-testid="simulated-label">
      <strong>{kind === "settings" ? REVIEWER_SIMULATED_SETTINGS_LABEL : REVIEWER_SIMULATED_LABEL}</strong>
      {children ? <span className="simulated-label__more"> · {children}</span> : null}
    </p>
  );
}

/** True in the partner trial account's sample shop, where every write is simulated in memory. */
export function useSampleSimulation(): boolean {
  return useReviewer()?.sample === true;
}
