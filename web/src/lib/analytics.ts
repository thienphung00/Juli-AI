export interface RecommendationActionEvent {
  recommendationId: string;
  recommendationType: string;
  actionType: string;
  matchScore?: number | null;
  creatorId?: string | null;
  productId?: string | null;
}

/** Client-side analytics hook for recommendation CTAs (PRD appendix D). */
export function trackRecommendationAction(
  event: RecommendationActionEvent
): void {
  if (typeof window === "undefined") return;

  const detail = {
    event: "recommendation_action_tapped",
    ...event,
  };

  window.dispatchEvent(
    new CustomEvent("juli:analytics", {
      detail,
    })
  );

  if (process.env.NODE_ENV === "development") {
    console.info("recommendation_action_tapped", detail);
  }
}

export function trackRecommendationViewed(
  recommendationId: string,
  recommendationType: string,
  matchScore?: number | null
): void {
  if (typeof window === "undefined") return;

  window.dispatchEvent(
    new CustomEvent("juli:analytics", {
      detail: {
        event: "recommendation_viewed",
        recommendationId,
        recommendationType,
        matchScore,
      },
    })
  );
}

export function trackMatchEmptyState(shopId: string | null, reason: string): void {
  if (typeof window === "undefined") return;

  window.dispatchEvent(
    new CustomEvent("juli:analytics", {
      detail: {
        event: "match_empty_state",
        shopId,
        reason,
      },
    })
  );
}
