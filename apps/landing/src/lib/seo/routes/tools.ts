import type { SiteRoute } from "./types";

/** Free tools under `/cong-cu/*` (D49.1). Owner: P43. No `/cong-cu` index page yet: the trail is Home → tool. */
export const TOOL_ROUTES: readonly SiteRoute[] = [
  {
    path: "/cong-cu/tinh-gmv",
    title: "Công cụ tính GMV TikTok Shop miễn phí | Juli AI",
    description:
      "Tính GMV TikTok Shop miễn phí từ Lượt hiển thị, CTR, CTOR, AOV hoặc từ lượt nhấp, đơn hàng: xem phễu từng bước và GMV đổi ra sao khi một chỉ số tăng.",
    lastModified: "2026-10-18",
    breadcrumbName: "Công cụ tính GMV",
    changeFrequency: "monthly",
    priority: 0.7,
  },
];
