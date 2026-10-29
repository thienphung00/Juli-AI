import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { MAIN_CARD, NOW, decision, rules } from "../decisions/p10-fixtures";

/**
 * The partner trial account end to end (fast track P32-A, D42, AC-32.2 /
 * AC-32.7), Supabase and the Juli API stubbed with page.route: /auth/email →
 * "Tài khoản đối tác" → e-mail + password → GoTrue password grant →
 * `/v1/reviewer/me` → Trang chủ with the banner → Quyết định → Duyệt →
 * "Thực thi (mô phỏng)" shows the change Juli would send. The real approve
 * route is never requested. Also: wrong password, and an expired account.
 *
 * Needs an artifact built with a Supabase project URL (any `*.supabase.co`).
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPORT = JSON.parse(readFileSync(resolve(HERE, "../../src/lib/shop-analysis/sample-report.json"), "utf8"));
const BANNER = "Tài khoản đối tác · dữ liệu shop thật đã ẩn tên · chỉ xem, duyệt chỉ mô phỏng";
const ALIAS_SHOP = { id: "5d0c1f0e-0000-5000-8000-00000000a11a", name: "Shop 123" };

function base64url(value: string): string {
  return Buffer.from(value).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const ACCESS_TOKEN = [
  base64url(JSON.stringify({ alg: "ES256", typ: "JWT", kid: "e2e" })),
  base64url(
    JSON.stringify({
      aud: "authenticated",
      sub: "22222222-2222-4222-8222-222222222222",
      email: "shopee-review@app-juli.com",
      amr: [{ method: "password", timestamp: 1_791_500_000 }],
      app_metadata: { juli_role: "reviewer", juli_platform: "shopee" },
    }),
  ),
  "sig",
].join(".");

const SIMULATION = (step: "approve" | "execute", cardId: string) => ({
  simulated: true,
  step,
  action_card_id: cardId,
  label: "Mô phỏng · không gửi tới TikTok",
  steps: [
    { key: "approve", label: "Duyệt", done: true },
    { key: "execute", label: "Thực thi", done: step === "execute" },
  ],
  change: {
    executor: "juli",
    lever: { code: "description", label: "Mô tả" },
    product: { title: "Sản phẩm 456", tiktok_product_id: "demo-product-0f1e2d3c" },
    request: { method: "PUT", path: "/product/202309/products/{product_id}", operation: "update_product_listing", fields: ["description"] },
    fields: [{ field: "description", label: "Mô tả", before: "180 ký tự, một đoạn", after: "Juli soạn nội dung mới sau khi duyệt" }],
    note: null,
  },
  enqueued: false,
  tiktok_write: false,
});

interface Seen {
  paths: string[];
  passwordBodies: Record<string, unknown>[];
}

async function stub(page: Page, me: { status: number; body: unknown; denied?: string }): Promise<Seen> {
  const seen: Seen = { paths: [], passwordBodies: [] };
  await page.clock.setFixedTime(new Date(NOW));
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => ({
    status,
    contentType: "application/json",
    headers,
    body: JSON.stringify(body),
  });
  await page.route(/\.supabase\.co\/auth\/v1\/token/, async (route) => {
    seen.passwordBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    const body = route.request().postDataJSON() as { password?: string };
    if (body.password !== "dung-mat-khau") {
      return route.fulfill(json({ code: 400, error_code: "invalid_credentials", msg: "Invalid login credentials" }, 400));
    }
    return route.fulfill(
      json({ access_token: ACCESS_TOKEN, token_type: "bearer", expires_in: 3600, refresh_token: "r-pw", user: { id: "2222" } }),
    );
  });
  await page.route((url) => url.pathname.startsWith("/v1/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    seen.paths.push(`${request.method()} ${path}`);
    if (path === "/v1/reviewer/me") {
      return route.fulfill(json(me.body, me.status, me.denied ? { "X-Juli-Reviewer-Denied": me.denied } : {}));
    }
    const simulate = /^\/v1\/reviewer\/decisions\/([^/]+)\/simulate$/.exec(path);
    if (simulate) {
      const step = (request.postDataJSON() as { step: "approve" | "execute" }).step;
      return route.fulfill(json(SIMULATION(step, simulate[1])));
    }
    if (/^\/v1\/demo\/analysis$/.test(path)) {
      const report = structuredClone(REPORT);
      report.report.shop_name = ALIAS_SHOP.name;
      return route.fulfill(json(report));
    }
    if (path === "/v1/demo/decisions" && request.method() === "GET") {
      return route.fulfill(json({ success: true, data: [decision(MAIN_CARD)], error: null }));
    }
    if (path === "/v1/demo/rules") return route.fulfill(json({ success: true, data: rules() }));
    if (path === "/v1/demo/runs") return route.fulfill(json({ success: true, data: [] }));
    if (path === "/v1/demo/revert-questions") return route.fulfill(json({ success: true, data: [] }));
    if (request.method() !== "GET") {
      return route.fulfill(json({ detail: "read only" }, 403, { "X-Juli-Reviewer-Denied": "read_only" }));
    }
    return route.fulfill({ status: 404, body: "{}" });
  });
  return seen;
}

const REVIEWER_ME = {
  status: 200,
  body: { reviewer: true, platform: "shopee", expires_at: "2026-11-13T00:00:00Z", shop: ALIAS_SHOP },
};

async function signIn(page: Page, password: string) {
  await page.goto("/auth/email#doi-tac");
  const form = page.getByRole("form", { name: "Đăng nhập bằng mật khẩu" });
  await expect(form).toBeVisible();
  await form.getByLabel("Email").fill("shopee-review@app-juli.com");
  await form.getByLabel("Mật khẩu").fill(password);
  await form.getByRole("button", { name: "Đăng nhập" }).click();
}

test.describe("partner trial account (P32-A)", () => {
  test("sign in → banner → Quyết định → Duyệt → Thực thi simulated, never the real approve", async ({ page }) => {
    const seen = await stub(page, REVIEWER_ME);
    await signIn(page, "dung-mat-khau");

    await page.waitForURL((url) => url.pathname === "/");
    await expect(page.getByTestId("reviewer-banner")).toContainText(BANNER);
    expect(seen.passwordBodies).toEqual([{ email: "shopee-review@app-juli.com", password: "dung-mat-khau" }]);

    await page.goto("/decisions");
    await expect(page.getByTestId("reviewer-banner")).toContainText(BANNER);
    await expect(page.getByTestId("no-shop-sample-strip")).toHaveCount(0);
    const card = page.getByTestId("recommendation-card").first();
    await expect(card.getByRole("button", { name: "Từ chối" })).toBeDisabled();
    await card.getByRole("button", { name: "Duyệt" }).click();

    const panel = page.getByTestId("reviewer-simulation");
    await expect(panel).toContainText("Mô phỏng · không gửi tới TikTok");
    await expect(panel).toContainText("Đã duyệt (mô phỏng)");
    await panel.getByRole("button", { name: "Thực thi (mô phỏng)" }).click();
    const change = panel.getByTestId("reviewer-simulation-change");
    await expect(change).toContainText("PUT /product/202309/products/{product_id}");
    await expect(change).toContainText("update_product_listing");
    await expect(change).toContainText("Không có thay đổi nào được gửi tới TikTok Shop.");

    expect(seen.paths.filter((p) => p.endsWith("/approve"))).toEqual([]);
    expect(seen.paths.filter((p) => p.includes("/events"))).toEqual([]);
    expect(seen.paths.filter((p) => p.includes("/simulate"))).toHaveLength(2);

    // No connect entry point for a reviewer.
    await page.goto("/auth/connect-shop");
    await page.waitForURL((url) => url.pathname === "/");
  });

  test("a wrong password says so in Vietnamese and asks the Juli API nothing", async ({ page }) => {
    const seen = await stub(page, REVIEWER_ME);
    await signIn(page, "sai");
    await expect(page.getByText("Sai email hoặc mật khẩu.")).toBeVisible();
    expect(seen.paths).toEqual([]);
  });

  test("an expired trial account is told so and stays signed out", async ({ page }) => {
    await stub(page, { status: 403, body: { detail: "expired" }, denied: "expired" });
    await signIn(page, "dung-mat-khau");
    await expect(page.getByText("Tài khoản đối tác này đã hết hạn. Vui lòng liên hệ Juli để gia hạn.")).toBeVisible();
    expect(await page.evaluate(() => window.localStorage.getItem("juli_demo_auth_session"))).toBeNull();
  });
});
