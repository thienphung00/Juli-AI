/** Categories blocked from TikTok Shop listing per P1.6 rules engine policy. */
export const BLOCKED_CATEGORIES = [
  "Vũ khí",
  "Thuốc lá",
  "Hàng cấm",
  "Weapons",
  "Tobacco",
] as const;

/** Minimum readiness score required for `ready_for_export` status. */
export const READINESS_EXPORT_THRESHOLD = 70;

export const BLOCKING_ISSUE_MISSING_PRICE = "Giá bán chưa được nhập";
export const BLOCKING_ISSUE_BLOCKED_CATEGORY =
  "Danh mục sản phẩm bị cấm trên TikTok Shop";
