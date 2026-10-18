import type { SiteRoute } from "./types";

/** Home, company and legal pages. Owner of `/` content: P33-B. */
export const CORE_ROUTES: readonly SiteRoute[] = [
  {
    path: "/",
    title: "Trợ lý AI vận hành TMĐT cho nhà bán TikTok Shop | Juli AI",
    description:
      "Trợ lý AI cho nhà bán TMĐT, hiện kết nối TikTok Shop: phân tích CTR, CTOR, AOV, đề xuất việc cần làm, thực thi khi bạn duyệt, đo GMV tăng thêm.",
    lastModified: "2026-10-18",
    breadcrumbName: "Trang chủ",
    changeFrequency: "weekly",
    priority: 1,
  },
  {
    path: "/about",
    title: "Về Công ty TNHH Công Nghệ Juli AI | Juli AI",
    description:
      "Juli AI do Công ty TNHH Công Nghệ Juli AI (MST 0319617654) tại TP. Hồ Chí Minh phát triển: sứ mệnh, nguyên tắc dữ liệu và thông tin doanh nghiệp.",
    lastModified: "2026-10-15",
    breadcrumbName: "Giới thiệu",
    changeFrequency: "monthly",
    priority: 0.6,
  },
  {
    path: "/contact",
    title: "Liên hệ tư vấn và hỗ trợ tài khoản | Juli AI",
    description:
      "Liên hệ Juli AI qua email lienhe@app-juli.com để được tư vấn sử dụng, hỗ trợ tài khoản, kết nối TikTok Shop hoặc hợp tác.",
    lastModified: "2026-10-15",
    breadcrumbName: "Liên hệ",
    changeFrequency: "yearly",
    priority: 0.5,
  },
  {
    path: "/privacy",
    title: "Chính sách bảo mật dữ liệu shop | Juli AI",
    description:
      "Juli AI thu thập gì, đọc gì từ TikTok Shop của bạn, chia sẻ với ai và lưu bao lâu; quyền của bạn với dữ liệu. Có bản tiếng Anh (English version).",
    lastModified: "2026-10-16",
    breadcrumbName: "Chính sách bảo mật",
    changeFrequency: "yearly",
    priority: 0.3,
  },
  {
    path: "/terms",
    title: "Điều khoản dịch vụ | Juli AI",
    description:
      "Điều khoản sử dụng Juli AI: tài khoản, kết nối (hiện TikTok Shop, Shopee đang tích hợp), phí dịch vụ 500.000đ/tháng, đề xuất của Juli, chấm dứt và liên hệ.",
    lastModified: "2026-10-16",
    breadcrumbName: "Điều khoản dịch vụ",
    changeFrequency: "yearly",
    priority: 0.3,
  },
];
