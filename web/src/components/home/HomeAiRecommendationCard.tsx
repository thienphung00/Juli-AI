import { Sparkles } from "lucide-react";
import type { HomeAiRecommendation } from "@/lib/mock-data/home";

export function HomeAiRecommendationCard({
  recommendation,
  title = "Gợi ý AI",
}: {
  recommendation: HomeAiRecommendation;
  title?: string;
}) {
  const confidencePct = Math.round(recommendation.confidence * 100);

  return (
    <div className="card p-4" data-testid="home-ai-recommendation">
      <div className="flex items-start justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold" style={{ color: "var(--primary)" }}>
          <Sparkles size={16} aria-hidden className="shrink-0" />
          {title}
        </h2>
        {recommendation.confidence > 0 && (
          <span
            className="badge text-xs"
            style={{
              background: confidencePct >= 70 ? "color-mix(in srgb, var(--success) 12%, transparent)" : "color-mix(in srgb, var(--warning) 12%, transparent)",
              color: confidencePct >= 70 ? "var(--success)" : "var(--warning)",
            }}
            aria-label="Độ tin cậy"
          >
            {confidencePct}%
          </span>
        )}
      </div>
      <p className="mt-2 text-sm font-medium" data-testid="home-ai-recommendation-headline">
        {recommendation.headline}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <a
          href={recommendation.primary_action.href}
          className="btn-primary inline-flex flex-1 items-center justify-center"
          data-testid="home-ai-primary-action"
        >
          {recommendation.primary_action.label}
        </a>
        {recommendation.secondary_action && (
          <button
            type="button"
            className="btn-secondary inline-flex flex-1 items-center justify-center"
            data-testid="home-ai-secondary-action"
          >
            {recommendation.secondary_action.label}
          </button>
        )}
      </div>
    </div>
  );
}
