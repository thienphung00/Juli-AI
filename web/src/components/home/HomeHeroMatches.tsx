import Link from "next/link";
import type { HomeHeroMatch } from "@/lib/mock-data/home";

export function HomeHeroMatches({ matches = [] }: { matches?: HomeHeroMatch[] }) {
  if (matches.length === 0) {
    return (
      <div className="card p-4" data-testid="home-hero-empty">
        <p className="text-sm font-medium" style={{ color: "var(--muted-foreground)" }}>
          Đang thu thập dữ liệu
        </p>
        <p className="mt-1 text-xs" style={{ color: "var(--muted-foreground)", opacity: 0.7 }}>
          Ghép creator–sản phẩm sẽ xuất hiện khi đủ dữ liệu đồ thị
        </p>
        <Link
          href="/recommendations"
          className="mt-3 inline-block text-xs font-semibold"
          style={{ color: "var(--primary)" }}
        >
          Mở Gợi ý →
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="home-hero-matches">
      <h2 className="text-sm font-semibold" style={{ color: "var(--primary)" }}>
        ✨ Quyết định hôm nay
      </h2>
      {matches.map((match) => (
        <div key={match.id} className="card p-4" data-testid="home-hero-match-card">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold" style={{ color: "var(--muted-foreground)" }}>
              {match.creator_name} × {match.product_name}
            </p>
            <span
              className="badge text-xs"
              style={{
                background: match.match_score >= 0.7 ? "#10b98120" : "#f59e0b20",
                color: match.match_score >= 0.7 ? "#10b981" : "#f59e0b",
              }}
              aria-label="Điểm ghép"
            >
              {Math.round(match.match_score * 100)}%
            </span>
          </div>
          <p className="mt-2 text-sm font-medium" data-testid="home-hero-match-headline">
            {match.headline}
          </p>
          <Link
            href={match.primary_action_href}
            className="mt-3 inline-flex w-full items-center justify-center rounded-xl px-3 py-2.5 text-sm font-semibold text-white"
            style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
            data-testid="home-hero-match-cta"
          >
            {match.cta}
          </Link>
        </div>
      ))}
    </div>
  );
}
