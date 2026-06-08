import type { ComplianceResult } from "@/lib/mock-data/listing-workflow/schemas";
import {
  BLOCKED_CATEGORIES,
  BLOCKING_ISSUE_BLOCKED_CATEGORY,
  BLOCKING_ISSUE_MISSING_PRICE,
} from "./constants";
import type { ExtractedProductFields } from "./types";

function isBlockedCategory(category: string): boolean {
  const normalized = category.trim().toLowerCase();
  return BLOCKED_CATEGORIES.some(
    (blocked) => blocked.toLowerCase() === normalized,
  );
}

export function evaluateCompliance(fields: ExtractedProductFields): ComplianceResult {
  const blocking_issues: string[] = [];
  const warnings: string[] = [];

  if (!fields.product_name.trim()) {
    blocking_issues.push("Tên sản phẩm chưa được nhập");
  }

  if (!fields.category.trim()) {
    blocking_issues.push("Danh mục sản phẩm chưa được nhập");
  }

  if (fields.price <= 0) {
    blocking_issues.push(BLOCKING_ISSUE_MISSING_PRICE);
  }

  if (isBlockedCategory(fields.category)) {
    blocking_issues.push(BLOCKING_ISSUE_BLOCKED_CATEGORY);
  }

  if (!fields.brand) {
    warnings.push("Thiếu thông tin thương hiệu");
  }

  if (!fields.description?.trim()) {
    warnings.push("Thiếu mô tả sản phẩm chi tiết");
  }

  if (blocking_issues.length > 0) {
    return { status: "blocked", warnings, blocking_issues };
  }

  if (warnings.length > 0) {
    return { status: "warning", warnings, blocking_issues: [] };
  }

  return { status: "approved", warnings: [], blocking_issues: [] };
}
