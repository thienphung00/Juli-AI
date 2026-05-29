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
        <h2 className="text-sm font-semibold" style={{ color: "var(--primary)" }}>
          ✨ {title}
        </h2>
        {recommendation.confidence > 0 && (
          <span
            className="badge text-xs"
            style={{
              background: confidencePct >= 70 ? "#10b98120" : "#f59e0b20",
              color: confidencePct >= 70 ? "#10b981" : "#f59e0b",
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
          className="inline-flex flex-1 items-center justify-center rounded-xl px-3 py-2.5 text-sm font-semibold text-white"
          style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
          data-testid="home-ai-primary-action"
        >
          {recommendation.primary_action.label}
        </a>
        {recommendation.secondary_action && (
          <button
            type="button"
            className="inline-flex flex-1 items-center justify-center rounded-xl border px-3 py-2.5 text-sm font-semibold"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            data-testid="home-ai-secondary-action"
          >
            {recommendation.secondary_action.label}
          </button>
        )}
      </div>
    </div>
  );
}
