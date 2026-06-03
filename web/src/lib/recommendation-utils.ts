import type { RecommendationItem } from "@/lib/api-client";

export function matchScorePercent(item: RecommendationItem): number | null {
  if (typeof item.match_score === "number") {
    const raw = item.match_score;
    return raw > 1 ? Math.max(0, Math.min(100, raw)) : Math.max(0, Math.min(100, raw * 100));
  }
  const payload = item.payload ?? {};
  const maybe =
    typeof payload["match_score"] === "number"
      ? payload["match_score"]
      : typeof payload["composite_score"] === "number"
        ? payload["composite_score"]
        : null;
  if (maybe === null) return null;
  return maybe > 1 ? Math.max(0, Math.min(100, maybe)) : Math.max(0, Math.min(100, maybe * 100));
}

export function creatorNameFromItem(item: RecommendationItem): string {
  const payload = item.payload ?? {};
  if (typeof payload["creator_name"] === "string") return payload["creator_name"];
  return "Creator";
}

export function productNameFromItem(item: RecommendationItem): string {
  const payload = item.payload ?? {};
  if (typeof payload["product_name"] === "string") return payload["product_name"];
  return "Sản phẩm";
}

export function isSparseRecommendations(items: RecommendationItem[]): boolean {
  return items.length === 0;
}

export function toTypeLabel(type: string): string {
  const map: Record<string, string> = {
    product_push: "Đẩy sản phẩm",
    host_product_match: "Ghép host + sản phẩm",
  };
  return map[type] ?? type;
}
