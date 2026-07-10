import type {
  ComplianceResult,
  ListingContent,
  ReadinessResult,
} from "@/lib/mock-data/listing-workflow/schemas";
import { READINESS_EXPORT_THRESHOLD } from "./constants";
import type { ExtractedProductFields } from "./types";

export { READINESS_EXPORT_THRESHOLD };

export function evaluateReadiness(
  fields: ExtractedProductFields,
  listingContent: ListingContent,
  compliance: ComplianceResult,
): ReadinessResult {
  if (compliance.status === "blocked") {
    return {
      overall_score: Math.max(
        0,
        20 -
          compliance.blocking_issues.length * 5 -
          compliance.warnings.length * 2,
      ),
      suggested_improvements: [
        ...compliance.blocking_issues,
        ...compliance.warnings,
      ],
    };
  }

  let score = 0;
  const suggested_improvements: string[] = [];

  if (fields.product_name.trim()) score += 15;
  if (fields.category.trim()) score += 10;
  if (fields.price > 0) score += 20;
  if (fields.brand) score += 10;
  else suggested_improvements.push("Thêm thương hiệu nếu có");
  if (fields.description?.trim()) score += 10;
  else suggested_improvements.push("Bổ sung mô tả sản phẩm");
  if (listingContent.title.trim().length >= 10) score += 10;
  if (listingContent.bullet_points.length >= 3) score += 10;
  if (listingContent.seo_keywords.length >= 2) score += 8;
  if (listingContent.hashtags.length >= 2) score += 7;

  if (compliance.status === "warning") {
    score = Math.max(0, score - compliance.warnings.length * 5);
    suggested_improvements.push(...compliance.warnings);
  }

  if (score < READINESS_EXPORT_THRESHOLD) {
    suggested_improvements.push(
      `Nâng điểm sẵn sàng lên ít nhất ${READINESS_EXPORT_THRESHOLD} trước khi xuất`,
    );
  }

  return {
    overall_score: Math.min(100, Math.max(0, score)),
    suggested_improvements: [...new Set(suggested_improvements)],
  };
}
