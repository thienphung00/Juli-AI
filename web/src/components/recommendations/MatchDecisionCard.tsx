"use client";

import type { RecommendationItem } from "@/lib/api-client";
import {
  creatorNameFromItem,
  matchScorePercent,
  productNameFromItem,
  toTypeLabel,
} from "@/lib/recommendation-utils";
import { PredictedOutcomePanel } from "./PredictedOutcomePanel";

export function MatchDecisionCard({
  item,
  onAction,
}: {
  item: RecommendationItem;
  onAction: () => void;
}) {
  const matchScore = matchScorePercent(item);
  const creatorName = creatorNameFromItem(item);
  const productName = productNameFromItem(item);

  return (
    <div className="card p-4" data-testid="match-decision-card">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold" style={{ color: "var(--muted-foreground)" }}>
          {toTypeLabel(item.recommendation_type)}
        </p>
        {matchScore !== null && (
          <span
            className="badge"
            style={{
              background: matchScore >= 70 ? "#10b98120" : "#f59e0b20",
              color: matchScore >= 70 ? "#10b981" : "#f59e0b",
            }}
            aria-label="Điểm ghép"
            data-testid="match-score-badge"
          >
            {Math.round(matchScore)}%
          </span>
        )}
      </div>

      <p className="mt-2 text-sm font-semibold">
        {creatorName} × {productName}
      </p>

      <p className="mt-2 text-sm font-medium" data-testid="recommendation-message">
        {item.message}
      </p>

      {item.predicted_outcome && (
        <PredictedOutcomePanel predicted={item.predicted_outcome} />
      )}

      <button
        type="button"
        className="mt-3 w-full rounded-xl px-3 py-2.5 text-sm font-semibold text-white"
        style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
        onClick={onAction}
        data-testid="recommendation-cta"
      >
        {item.cta}
      </button>
    </div>
  );
}
