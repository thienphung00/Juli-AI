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

export interface TaskExecutorActionEvent {
  taskId: string;
  action: "approve" | "dismiss";
}

/** Client-side analytics for Phase 1 no-op task executor (issue #117). */
export function trackTaskExecutorAction(event: TaskExecutorActionEvent): void {
  if (typeof window === "undefined") return;

  const detail = {
    event: "task_executor_action",
    ...event,
  };

  window.dispatchEvent(
    new CustomEvent("juli:analytics", {
      detail,
    }),
  );

  if (process.env.NODE_ENV === "development") {
    console.info("task_executor_action", detail);
  }
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
