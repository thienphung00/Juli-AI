import type { SiteRoute } from "./types";

/**
 * Capability pages under `/san-pham/*` and `/ket-noi/tiktok-shop` (D43.1).
 * Owner: P33-C. `/ket-noi/tiktok-shop` hangs off the home page (it is an
 * integration page, not a product feature).
 */
export const CAPABILITY_ROUTES: readonly SiteRoute[] = [
  {
    path: "/san-pham/phan-tich-shop",
    title: "Phân tích TikTok Shop theo 5 luồng truy cập | Juli AI",
    description:
      "Tách GMV TikTok Shop theo Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Liên kết; tìm chỉ số nghẽn và xếp hạng sản phẩm theo tác động GMV.",
    lastModified: "2026-10-15",
    breadcrumbName: "Phân tích shop",
    parent: "/san-pham",
    changeFrequency: "monthly",
    priority: 0.8,
  },
  {
    path: "/san-pham/de-xuat-va-thuc-thi",
    title: "Đề xuất tối ưu, thực hiện khi bạn duyệt | Juli AI",
    description:
      "Thẻ đề xuất cho từng sản phẩm TikTok Shop: lý do, mục tiêu, GMV dự kiến. Juli chỉ ghi tiêu đề, mô tả khi bạn duyệt; hoàn tác được.",
    lastModified: "2026-10-15",
    breadcrumbName: "Đề xuất và thực thi",
    parent: "/san-pham",
    changeFrequency: "monthly",
    priority: 0.8,
  },
  {
    path: "/san-pham/do-luong-gmv",
    title: "Đo lường GMV sau thay đổi: ngày 7, ngày 14 | Juli AI",
    description:
      "Juli đo mỗi thay đổi trên TikTok Shop so với mốc 14 ngày trước: kiểm tra ngày 7, chốt ngày 14, nhãn độ tin cậy, không tự nhận công.",
    lastModified: "2026-10-15",
    breadcrumbName: "Đo lường GMV",
    parent: "/san-pham",
    changeFrequency: "monthly",
    priority: 0.8,
  },
  {
    path: "/ket-noi/tiktok-shop",
    title: "Kết nối TikTok Shop qua uỷ quyền chính thức | Juli AI",
    description:
      "Cách Juli kết nối TikTok Shop: uỷ quyền chính thức, dữ liệu được đọc, thay đổi chỉ ghi khi bạn duyệt, quét nhanh sau kết nối, ngắt kết nối.",
    lastModified: "2026-10-15",
    breadcrumbName: "Kết nối TikTok Shop",
    changeFrequency: "monthly",
    priority: 0.7,
  },
];
