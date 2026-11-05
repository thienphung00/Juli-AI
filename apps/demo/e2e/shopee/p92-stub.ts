import type { Page } from "@playwright/test";

import { FLOOR_WARNING, P_ZIP, coPurchase, evaluation, keywordTable, pickerProducts, variationList } from "../../src/lib/shopee-decisions/__tests__/builder-fixtures";

/**
 * Synthetic P92 builder API for the browser specs (`/v1/demo/shopee/builder/*`): the picker, the variations,
 * evaluate / compare (version 2 breaks a floor when `breach2`), and choose. Every POST is recorded.
 */

export const SHOP = { id: "shop-shopee-e2e", name: "Shop mẫu gia dụng" };

export interface BuilderPosts {
  readonly list: { path: string; body: unknown }[];
}

export function builderResponse(path: string, method: string, body: unknown, breach2: boolean): { status: number; body: unknown } | null {
  if (!path.includes("/builder/")) return null;
  const versions = ((body as { versions?: unknown[] } | null)?.versions ?? []) as unknown[];
  const eva = (n: number) => evaluation(n, (i) => (breach2 && i === 1 ? { warnings: [FLOOR_WARNING], breach: true } : {}));
  if (path.endsWith("/builder/products")) return { status: 200, body: pickerProducts() };
  if (path.endsWith("/variations")) return { status: 200, body: variationList(P_ZIP) };
  if (path.endsWith("/co-purchase")) return { status: 200, body: coPurchase() };
  if (path.endsWith("/keywords")) return { status: 200, body: keywordTable() };
  if (path.endsWith("/builder/evaluate")) return { status: 200, body: eva(versions.length || 1) };
  if (path.endsWith("/builder/compare")) return { status: 200, body: eva(versions.length || 2) };
  if (path.endsWith("/builder/choose")) return { status: 201, body: { id: "card-1", code: "JC-2611-0021", status: "sent", origin: "manual", position: 1, versions: [] } };
  return { status: 404, body: { detail: "none" } };
}

export async function stubBuilder(page: Page, opts: { breach2?: boolean } = {}): Promise<BuilderPosts> {
  const posts: BuilderPosts = { list: [] };
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const body = req.method() === "POST" ? req.postDataJSON() : null;
    if (req.method() === "POST") posts.list.push({ path, body });
    if (path === "/v1/shops/me") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: SHOP.id, platform: "shopee" }) });
    const r = builderResponse(path, req.method(), body, opts.breach2 ?? false);
    if (r) return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
    if (path.endsWith("/recommendations")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ platform: "shopee", xep_theo: "diem", queue: "all", cards: [], counts: { family: {}, section: {}, total: 0 } }) });
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "none" }) });
  });
  return posts;
}
