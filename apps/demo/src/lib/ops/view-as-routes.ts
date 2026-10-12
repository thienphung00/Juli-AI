/**
 * "Xem như shop" routes (D25.3). The seller screens link to each other with
 * their own routes (`/analytics?…`, `/decisions?…`, `/`), which do not exist
 * under Juli Ops — following one left view-as for a 404. View-as is one page,
 * `/ops/shops/{id}/xem`, whose query says which seller screen it shows:
 *
 *   /                 → /ops/shops/{id}/xem?trang=trang-chu
 *   /decisions?…      → /ops/shops/{id}/xem?trang=quyet-dinh&…
 *   /analytics?…      → /ops/shops/{id}/xem?trang=phan-tich&…
 *   (sidebar Quy tắc) → /ops/shops/{id}/xem?trang=quy-tac
 *
 * Anything else (TikTok deep links, /auth/…) is returned unchanged.
 */

export type ViewAsTab = "home" | "decisions" | "analytics" | "rules";

const TAB_SLUG: Readonly<Record<ViewAsTab, string>> = {
  home: "trang-chu",
  decisions: "quyet-dinh",
  analytics: "phan-tich",
  rules: "quy-tac",
};

const SLUG_TAB: Readonly<Record<string, ViewAsTab>> = Object.fromEntries(
  Object.entries(TAB_SLUG).map(([tab, slug]) => [slug, tab as ViewAsTab]),
);

export const VIEW_AS_PAGE_PARAM = "trang";

export function viewAsBase(shopId: string): string {
  return `/ops/shops/${encodeURIComponent(shopId)}/xem`;
}

/** The view-as URL of one seller screen with that screen's own query. */
export function viewAsTabHref(shopId: string, tab: ViewAsTab, params?: URLSearchParams): string {
  const query = new URLSearchParams();
  query.set(VIEW_AS_PAGE_PARAM, TAB_SLUG[tab]);
  params?.forEach((value, key) => {
    if (key !== VIEW_AS_PAGE_PARAM) query.append(key, value);
  });
  return `${viewAsBase(shopId)}?${query.toString()}`;
}

function sellerTab(path: string): ViewAsTab | null {
  if (path === "/" || path === "") return "home";
  if (path === "/decisions" || path.startsWith("/decisions/")) return "decisions";
  if (path === "/analytics" || path.startsWith("/analytics/")) return "analytics";
  return null;
}

/** A seller href → its view-as equivalent (unchanged when the seller route has none). */
export function viewAsHref(shopId: string, sellerHref: string): string {
  if (!sellerHref.startsWith("/") || sellerHref.startsWith("//")) return sellerHref;
  const [path, search = ""] = sellerHref.split("?");
  const tab = sellerTab(path);
  if (!tab) return sellerHref;
  return viewAsTabHref(shopId, tab, new URLSearchParams(search));
}

/** Which seller screen a view-as query shows (Quyết định by default) and that screen's own query. */
export function readViewAsQuery(search: URLSearchParams): { tab: ViewAsTab; params: URLSearchParams } {
  const tab = SLUG_TAB[search.get(VIEW_AS_PAGE_PARAM) ?? ""] ?? "decisions";
  const params = new URLSearchParams();
  search.forEach((value, key) => {
    if (key !== VIEW_AS_PAGE_PARAM) params.append(key, value);
  });
  return { tab, params };
}
