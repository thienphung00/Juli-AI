import type { SiteRoute } from "./types";

/** The free 3-month trial sign-up and its thank-you page. Owner: P33-F. */
export const SIGNUP_ROUTES: readonly SiteRoute[] = [
  {
    path: "/dang-ky",
    title: "Đăng ký dùng thử miễn phí 3 tháng | Juli AI",
    description:
      "Đăng ký dùng thử Juli AI miễn phí 3 tháng: để lại số điện thoại hoặc Zalo, đội ngũ Juli liên hệ và cùng bạn kết nối TikTok Shop.",
    lastModified: "2026-10-15",
    breadcrumbName: "Đăng ký dùng thử",
    changeFrequency: "monthly",
    priority: 0.8,
  },
  {
    // Rendered after a sign-up only: noindex, out of the sitemap, linked from nowhere.
    path: "/dang-ky/cam-on",
    title: "Cảm ơn bạn đã đăng ký dùng thử | Juli AI",
    description:
      "Juli AI đã nhận đăng ký dùng thử của bạn. Đội ngũ Juli sẽ liên hệ để kết nối shop, hoặc bạn có thể tự kết nối TikTok Shop ngay.",
    lastModified: "2026-10-15",
    breadcrumbName: "Cảm ơn",
    parent: "/dang-ky",
    noindex: true,
  },
];
