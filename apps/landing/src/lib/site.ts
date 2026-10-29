/**
 * The Demo CTA destination: the public Demo in Mock mode (no signup needed).
 * Overridable per environment for preview deployments.
 */
export const DEMO_URL =
  process.env.NEXT_PUBLIC_DEMO_URL ?? "https://app.app-juli.com/";

/**
 * The single Login/Signup destination for the landing CTAs (hero + closing
 * trial CTA). It points at the Demo, which carries its own Login/Signup entry,
 * because the main-domain `/login` route does not exist yet (Phase 3.5-C owns
 * it, ADR-048 / ADR-050). Overridable per environment.
 */
export const LOGIN_URL =
  process.env.NEXT_PUBLIC_LOGIN_URL ?? "https://app.app-juli.com/";

/**
 * The free 3-month trial sign-up (D43 additions, owner 2026-10-15): an internal
 * fast form page on app-juli.com, `/dang-ky`, built by P33-F
 * (`fasttrack/p33f-trial-signup`) with its thank-you page; it exists after
 * integration. The Pixel listener (`TikTokTracking`) tracks clicks to it.
 * Overridable per environment.
 */
export const SIGNUP_URL = process.env.NEXT_PUBLIC_SIGNUP_URL ?? "/dang-ky";

/** The trial CTA label, everywhere on the site. */
export const TRIAL_CTA_LABEL = "Dùng thử miễn phí 3 tháng";

/** In-page anchors on `/`. */
export const SECTION_IDS = {
  howItWorks: "cach-hoat-dong",
  capabilities: "tinh-nang",
  faq: "cau-hoi",
} as const;

/**
 * The public, no-login pages describing the product and the company — the
 * header and footer link them from every page. TikTok's developer review
 * rejects a site that is only a landing page plus a login (2026-10 ticket
 * 4486401), so these must stay reachable without an account.
 */
export const SITE_PAGES = [
  { href: "/san-pham", label: "Sản phẩm" },
  { href: "/blog", label: "Blog" },
  { href: "/about", label: "Giới thiệu" },
  { href: "/contact", label: "Liên hệ" },
] as const;

/**
 * The capability pages under `/san-pham` and the TikTok Shop integration page
 * (D43.1, built by P33-C). Linked from the footer, the homepage capability
 * blocks and the `/san-pham` overview.
 */
export const PRODUCT_PAGES = {
  analysis: { href: "/san-pham/phan-tich-shop", label: "Phân tích shop" },
  actions: { href: "/san-pham/de-xuat-va-thuc-thi", label: "Đề xuất và thực thi" },
  measurement: { href: "/san-pham/do-luong-gmv", label: "Đo lường GMV" },
  tiktokShop: { href: "/ket-noi/tiktok-shop", label: "Kết nối TikTok Shop" },
} as const;

/**
 * Free tools (D49.1). Not product pages, so not in the header's "Sản phẩm"
 * dropdown (D46.1 lists exactly four); linked from the footer, the home FAQ
 * and `/san-pham/phan-tich-shop`.
 */
export const FREE_TOOLS = {
  gmvCalculator: { href: "/cong-cu/tinh-gmv", label: "Công cụ tính GMV" },
} as const;

/** Footer "Sản phẩm" column, in reading order (the free tool last). */
export const FOOTER_PRODUCT_LINKS = [
  { href: "/san-pham", label: "Tổng quan sản phẩm" },
  PRODUCT_PAGES.analysis,
  PRODUCT_PAGES.actions,
  PRODUCT_PAGES.measurement,
  PRODUCT_PAGES.tiktokShop,
  FREE_TOOLS.gmvCalculator,
] as const;

/**
 * The origins this site is actually served from, and the only ones whose
 * pages may post to `/api/tt/event`.
 *
 * Apex only for production: nginx 301s `www.app-juli.com` to `app-juli.com`
 * (infra/nginx/app-juli.com.conf), so no page is ever served from www and no
 * browser will send it as an Origin. The dev entry is the port
 * `package.json` binds `next dev` and `next start` to.
 */
export const SITE_ORIGINS: readonly string[] = [
  "https://app-juli.com",
  "http://localhost:3007",
];

/** The legal entity operating Juli AI, named on /privacy and /terms. */
export const COMPANY = {
  name: "Công ty TNHH Công Nghệ Juli AI",
  taxId: "0319617654",
  address:
    "1B Đường số 30 Trần Não, Phường An Khánh, Thành phố Hồ Chí Minh, Việt Nam",
  email: "lienhe@app-juli.com",
  /** `address` split for schema.org `PostalAddress` (JSON-LD, D43.5). */
  postalAddress: {
    streetAddress: "1B Đường số 30 Trần Não",
    addressLocality: "Phường An Khánh",
    addressRegion: "Thành phố Hồ Chí Minh",
    addressCountry: "VN",
  },
} as const;

/**
 * The header's primary nav (D44, `Main.dc.html`): product, the TikTok Shop
 * integration, blog, company. `/contact` lives in the footer and the mobile
 * menu. `match` marks the item active for that path and everything under it.
 */
export const HEADER_NAV = [
  { href: "/san-pham", label: "Sản phẩm", match: "/san-pham" },
  { href: "/ket-noi/tiktok-shop", label: "Kết nối TikTok Shop", match: "/ket-noi" },
  { href: "/blog", label: "Blog", match: "/blog" },
  { href: "/about", label: "Giới thiệu", match: "/about" },
] as const;

/**
 * The header's "Sản phẩm" dropdown (D46.1): overview first, then the three
 * capability pages, each with a one-line description (≤ 8 words, facts as on
 * the pages). `/ket-noi/tiktok-shop` stays a top-level header item.
 */
export const PRODUCT_MENU = [
  { href: "/san-pham", label: "Tổng quan sản phẩm", description: "Juli làm gì, cách làm và bảng giá" },
  { ...PRODUCT_PAGES.analysis, description: "GMV theo luồng truy cập và phễu" },
  { ...PRODUCT_PAGES.actions, description: "Thẻ đề xuất, thực thi khi bạn duyệt" },
  { ...PRODUCT_PAGES.measurement, description: "Đo kết quả ngày 7 và ngày 14" },
] as const;

/** Footer "Công ty" column (D44 footer): company pages, then the Demo. */
export const FOOTER_COMPANY_LINKS = [
  { href: "/about", label: "Giới thiệu" },
  { href: "/blog", label: "Blog" },
  { href: "/contact", label: "Liên hệ" },
] as const;
