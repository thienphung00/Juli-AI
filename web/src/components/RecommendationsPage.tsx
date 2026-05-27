"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type RecommendationItem } from "@/lib/api-client";
import { NavBar } from "./NavBar";

function getConfidence(item: RecommendationItem): number | null {
  const payload = item.payload ?? {};
  const maybe =
    typeof payload["composite_score"] === "number"
      ? payload["composite_score"]
      : typeof payload["match_score"] === "number"
        ? payload["match_score"]
        : null;
  if (maybe === null) return null;
  if (maybe > 1) return Math.max(0, Math.min(100, maybe));
  return Math.max(0, Math.min(100, maybe * 100));
}

function toTypeLabel(type: string): string {
  const map: Record<string, string> = {
    product_push: "Đẩy sản phẩm",
    host_product_match: "Ghép host + sản phẩm",
  };
  return map[type] ?? type;
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
      setItems(res.items ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setItems([]);
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

  const rendered = useMemo(
    () =>
      items.map((item) => ({
        item,
        confidence: getConfidence(item),
      })),
    [items]
  );

  return (
    <div className="min-h-screen pb-24" style={{ background: "var(--background)" }}>
      <header
        className="sticky top-0 z-10 px-4 py-3"
        style={{ background: "var(--background)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Gợi ý</h1>
          <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
            Gợi ý hành động 1-chạm cho livestream hôm nay
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4" data-testid="recommendations-feed">
        {error && (
          <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
            {error}
          </p>
        )}
        {lastAction && (
          <p role="status" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#10b98120", color: "#10b981" }}>
            {lastAction}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center" data-testid="recommendations-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>
              Chưa có gợi ý nào
            </p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Hệ thống sẽ tạo gợi ý khi có dữ liệu đủ
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="recommendations-list">
            {rendered.map(({ item, confidence }) => (
              <RecommendationCard
                key={item.id}
                item={item}
                confidence={confidence}
                onCta={() => setLastAction(`Đã lưu CTA: ${item.cta}`)}
              />
            ))}
          </div>
        )}
      </main>

      <NavBar />
    </div>
  );
}

function RecommendationCard({
  item,
  confidence,
  onCta,
}: {
  item: RecommendationItem;
  confidence: number | null;
  onCta: () => void;
}) {
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
        onClick={onCta}
        data-testid="recommendation-cta"
      >
        {item.cta}
      </button>
    </div>
  );
}

