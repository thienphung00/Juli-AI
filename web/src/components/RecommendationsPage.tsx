"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type RecommendationItem } from "@/lib/api-client";
import {
  trackMatchEmptyState,
  trackRecommendationAction,
  trackRecommendationViewed,
} from "@/lib/analytics";
import { isSparseRecommendations, matchScorePercent, toTypeLabel } from "@/lib/recommendation-utils";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { CollectingDataEmpty } from "./recommendations/CollectingDataEmpty";
import { MatchDecisionCard } from "./recommendations/MatchDecisionCard";

function payloadId(item: RecommendationItem, key: string): string | null {
  const value = item.payload?.[key];
  return typeof value === "string" ? value : null;
}

export function RecommendationsPage() {
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.recommendations.list();
      const nextItems = res.items ?? [];
      setItems(nextItems);
      if (isSparseRecommendations(nextItems)) {
        const shopId =
          typeof window !== "undefined"
            ? localStorage.getItem("active_shop_id")
            : null;
        trackMatchEmptyState(shopId, "sparse_graph");
      } else {
        nextItems.forEach((item) => {
          trackRecommendationViewed(
            item.id,
            item.recommendation_type,
            matchScorePercent(item)
          );
        });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setItems([]);
        trackMatchEmptyState(
          localStorage.getItem("active_shop_id"),
          "sparse_graph"
        );
      } else {
        setError("Không thể tải gợi ý. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCta = (item: RecommendationItem) => {
    trackRecommendationAction({
      recommendationId: item.id,
      recommendationType: item.recommendation_type,
      actionType: item.action_type ?? "unknown",
      matchScore: item.match_score ?? matchScorePercent(item),
      creatorId: payloadId(item, "creator_id"),
      productId: payloadId(item, "tiktok_product_id"),
    });
    setLastAction(`Đã lưu CTA: ${item.cta}`);
  };

  return (
    <AuthenticatedShell
      title="Gợi ý"
      subtitle="Quyết định ghép creator–sản phẩm hôm nay"
    >
      <div data-testid="recommendations-feed">
        {error && (
          <p
            role="alert"
            className="mb-4 rounded-xl p-3 text-sm"
            style={{ background: "#ef444420", color: "#ef4444" }}
          >
            {error}
            <button
              type="button"
              className="ml-2 font-semibold underline"
              onClick={() => load()}
            >
              Thử lại
            </button>
          </p>
        )}
        {lastAction && (
          <p
            role="status"
            className="mb-4 rounded-xl p-3 text-sm"
            style={{ background: "#10b98120", color: "#10b981" }}
          >
            {lastAction}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : isSparseRecommendations(items) ? (
          <CollectingDataEmpty />
        ) : (
          <div className="space-y-3" data-testid="recommendations-list">
            {items.map((item) =>
              item.recommendation_type === "host_product_match" ? (
                <MatchDecisionCard
                  key={item.id}
                  item={item}
                  onAction={() => handleCta(item)}
                />
              ) : (
                <LegacyRecommendationCard
                  key={item.id}
                  item={item}
                  onAction={() => handleCta(item)}
                />
              )
            )}
          </div>
        )}
      </div>
    </AuthenticatedShell>
  );
}

function LegacyRecommendationCard({
  item,
  onAction,
}: {
  item: RecommendationItem;
  onAction: () => void;
}) {
  const confidence = matchScorePercent(item);

  return (
    <div className="card p-4" data-testid="recommendation-card">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold" style={{ color: "var(--muted-foreground)" }}>
          {toTypeLabel(item.recommendation_type)}
        </p>
        {confidence !== null && (
          <span
            className="badge"
            style={{
              background: confidence >= 70 ? "#10b98120" : "#f59e0b20",
              color: confidence >= 70 ? "#10b981" : "#f59e0b",
            }}
            aria-label="Độ tin cậy"
          >
            {Math.round(confidence)}%
          </span>
        )}
      </div>

      <p className="mt-2 text-sm font-medium" data-testid="recommendation-message">
        {item.message}
      </p>

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
