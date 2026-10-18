import { COMPANY } from "../site";
import { absoluteUrl } from "./config";
import type { SiteRoute } from "./routes";
import { PRICE_VND } from "./schema";

/**
 * `/llms.txt` (llmstxt.org, D48 additions 4): a short Vietnamese description of
 * Juli AI and every indexable registered page with its meta description. Built
 * from the route registry so it stays in sync; `noindex` routes (blog drafts,
 * the sign-up thank-you page) are left out, as in the sitemap.
 */
const SECTIONS: ReadonlyArray<{ heading: string; matches: (path: string) => boolean }> = [
  { heading: "Sản phẩm", matches: (p) => p === "/san-pham" || p.startsWith("/san-pham/") },
  { heading: "Kết nối", matches: (p) => p.startsWith("/ket-noi/") },
  { heading: "Công cụ miễn phí", matches: (p) => p.startsWith("/cong-cu/") },
  { heading: "Blog", matches: (p) => p === "/blog" || p.startsWith("/blog/") },
  { heading: "Dùng thử", matches: (p) => p === "/dang-ky" || p.startsWith("/dang-ky/") },
  { heading: "Công ty và pháp lý", matches: () => true },
];

const SUFFIX = / \| Juli AI$/;

function line(route: SiteRoute): string {
  return `- [${route.title.replace(SUFFIX, "")}](${absoluteUrl(route.path)}): ${route.description}`;
}

export function llmsTxt(routes: readonly SiteRoute[]): string {
  const indexable = routes.filter((route) => !route.noindex);
  const home = indexable.find((route) => route.path === "/");
  const rest = indexable.filter((route) => route.path !== "/");
  const price = PRICE_VND.toLocaleString("vi-VN");
  const out: string[] = [
    "# Juli AI",
    "",
    "> Juli AI là trợ lý AI vận hành TMĐT cho nhà bán hàng: đọc dữ liệu shop qua API chính thức, " +
      "tìm chỗ cải thiện GMV (GMV = Lượt hiển thị × CTR × CTOR × AOV, theo từng luồng truy cập và " +
      "từng sản phẩm), đề xuất việc cần làm, chỉ thực hiện thay đổi khi người bán duyệt, và đo kết " +
      "quả ở ngày 7, ngày 14. Hiện kết nối TikTok Shop, Shopee đang tích hợp.",
    "",
    "- Juli ghi tiêu đề và mô tả sản phẩm lên shop chỉ sau khi người bán duyệt và xác nhận; giá và " +
      "khuyến mãi là đề xuất để người bán tự làm trong Seller Center. Juli không chạy quảng cáo.",
    `- Giá: ${price}đ/tháng (một gói); tài khoản mới dùng thử miễn phí 3 tháng, không cần thẻ thanh toán.`,
    `- Đơn vị phát triển: ${COMPANY.name}, MST ${COMPANY.taxId}, ${COMPANY.address}. ` +
      `Liên hệ: ${COMPANY.email}.`,
    "- Ngôn ngữ của trang: tiếng Việt.",
  ];
  if (home) out.push("", "## Trang chủ", "", line(home));
  const used = new Set<string>();
  for (const section of SECTIONS) {
    const items = rest.filter((route) => !used.has(route.path) && section.matches(route.path));
    if (items.length === 0) continue;
    for (const route of items) used.add(route.path);
    out.push("", `## ${section.heading}`, "", ...items.map(line));
  }
  return `${out.join("\n")}\n`;
}
