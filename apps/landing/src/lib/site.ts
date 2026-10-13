/**
 * The Demo CTA destination: the public Demo in Mock mode (no signup needed).
 * Overridable per environment for preview deployments.
 */
export const DEMO_URL =
  process.env.NEXT_PUBLIC_DEMO_URL ?? "https://demo.app-juli.com/";

/**
 * The single Login/Signup destination for the landing CTAs (hero + closing
 * trial CTA). It points at the Demo, which carries its own Login/Signup entry,
 * because the main-domain `/login` route does not exist yet (Phase 3.5-C owns
 * it, ADR-048 / ADR-050). Overridable per environment.
 */
export const LOGIN_URL =
  process.env.NEXT_PUBLIC_LOGIN_URL ?? "https://demo.app-juli.com/";

/** In-page anchors on `/` used by secondary CTAs. */
export const SECTION_IDS = {
  features: "tinh-nang",
  comparison: "giai-phap",
} as const;

/**
 * The public, no-login pages describing the product and the company — the
 * header and footer link them from every page. TikTok's developer review
 * rejects a site that is only a landing page plus a login (2026-10 ticket
 * 4486401), so these must stay reachable without an account.
 */
export const SITE_PAGES = [
  { href: "/product", label: "Sản phẩm" },
  { href: "/about", label: "Giới thiệu" },
  { href: "/contact", label: "Liên hệ" },
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
} as const;
