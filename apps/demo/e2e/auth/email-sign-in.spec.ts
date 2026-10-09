import { mkdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { openShopMenu } from "../helpers/demo-navigation";

/**
 * "Đăng nhập bằng email" end to end (AC-9.1), Supabase stubbed with
 * page.route: landing door → email → "Gửi mã" → 6-digit code → signed in on
 * /auth/connect-shop, whose `GET /v1/shops` and "Kết nối TikTok Shop"
 * (`GET /v1/auth/tiktok/start`) carry the email session's bearer — the same
 * path the Google door takes. Also: wrong code, rate limit, the magic link
 * landing on /auth/callback, and the avatar menu's email item.
 *
 * Needs an artifact built with a Supabase project URL (any `*.supabase.co`;
 * the stubs answer for whichever host it is). Set EMAIL_SHOTS_DIR to also
 * write 1440 / 390 screenshots.
 */

const SHOTS = process.env.EMAIL_SHOTS_DIR;

function base64url(value: string): string {
  return Buffer.from(value).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Unsigned, display-only — the backend is stubbed; GoTrue's real token is ES256-signed. */
const ACCESS_TOKEN = [
  base64url(JSON.stringify({ alg: "ES256", typ: "JWT", kid: "e2e" })),
  base64url(
    JSON.stringify({
      aud: "authenticated",
      sub: "11111111-1111-4111-8111-111111111111",
      email: "ban@shopcuaban.vn",
      role: "authenticated",
      amr: [{ method: "otp", timestamp: 1_791_500_000 }],
      user_metadata: { email: "ban@shopcuaban.vn", email_verified: true },
    }),
  ),
  "sig",
].join(".");

interface SupabaseStubs {
  otp?: (route: Route) => Promise<void>;
  verify?: (route: Route) => Promise<void>;
}

async function stubSupabase(page: Page, stubs: SupabaseStubs = {}) {
  const calls: { path: string; body: Record<string, unknown>; redirectTo: string | null }[] = [];
  await page.route(/\.supabase\.co\/auth\/v1\/(otp|verify)/, async (route) => {
    const url = new URL(route.request().url());
    calls.push({
      path: url.pathname,
      body: route.request().postDataJSON() as Record<string, unknown>,
      redirectTo: url.searchParams.get("redirect_to"),
    });
    if (url.pathname === "/auth/v1/otp") {
      return stubs.otp ? stubs.otp(route) : route.fulfill({ status: 200, json: {} });
    }
    return stubs.verify
      ? stubs.verify(route)
      : route.fulfill({
          status: 200,
          json: {
            access_token: ACCESS_TOKEN,
            token_type: "bearer",
            expires_in: 3600,
            refresh_token: "r-email",
            user: { id: "11111111-1111-4111-8111-111111111111", email: "ban@shopcuaban.vn" },
          },
        });
  });
  return calls;
}

async function stubJuliApi(page: Page) {
  const bearers: string[] = [];
  await page.route(/\/v1\/shops$/, async (route) => {
    bearers.push(route.request().headers().authorization ?? "");
    await route.fulfill({ status: 200, json: [] });
  });
  await page.route(/\/v1\/auth\/tiktok\/start/, async (route) => {
    bearers.push(route.request().headers().authorization ?? "");
    await route.fulfill({ status: 200, json: { authorize_url: "https://services.tiktokshop.com/open/authorize?e2e=1" } });
  });
  await page.route("https://services.tiktokshop.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<title>TikTok</title><h1>TikTok consent</h1>" }),
  );
  return bearers;
}

async function freshLanding(page: Page) {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.reload();
}

async function shoot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const width = page.viewportSize()?.width ?? 0;
  const size = width >= 768 ? 1440 : 390;
  await page.setViewportSize({ width: size, height: size === 1440 ? 900 : 844 });
  await page.screenshot({ path: `${SHOTS}/${name}-${size}.png`, fullPage: true });
}

test("landing → email → Gửi mã → code → signed in; connect-shop and TikTok start carry the email session", async ({
  page,
}) => {
  const calls = await stubSupabase(page);
  const bearers = await stubJuliApi(page);
  await freshLanding(page);

  await page.getByRole("button", { name: "Đăng nhập bằng email" }).click();
  await page.getByLabel("Email", { exact: true }).fill("ban@shopcuaban.vn");
  await shoot(page, "landing-email");
  await page.getByRole("button", { name: "Gửi mã" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Đã gửi mã 6 chữ số tới ban@shopcuaban.vn" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Gửi lại mã sau \d+ giây$/ })).toBeDisabled();
  expect(calls[0]).toMatchObject({
    path: "/auth/v1/otp",
    body: { email: "ban@shopcuaban.vn", create_user: true },
  });
  expect(new URL(calls[0].redirectTo as string).pathname).toBe("/auth/callback");

  const results = await new AxeBuilder({ page }).include("form[aria-label='Đăng nhập bằng email']").analyze();
  expect(results.violations).toEqual([]);
  await page.getByLabel("Mã đăng nhập (6 chữ số)").fill("123456");
  await shoot(page, "landing-code");
  await page.getByRole("button", { name: "Xác nhận" }).click();

  await expect(page).toHaveURL(/\/auth\/connect-shop$/);
  await expect(page.getByText("Bạn đã đăng nhập bằng")).toContainText("ban@shopcuaban.vn");
  expect(calls[1]).toMatchObject({ path: "/auth/v1/verify", body: { type: "email", email: "ban@shopcuaban.vn", token: "123456" } });
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("juli_demo_auth_session") ?? "null"));
  expect(stored).toEqual({ accessToken: ACCESS_TOKEN, refreshToken: "r-email", expiresIn: 3600, tokenType: "bearer" });
  await shoot(page, "connect-shop-after-email");

  await page.getByTestId("connect-tiktok-shop-cta").click();
  await expect(page).toHaveURL(/services\.tiktokshop\.com/);
  expect(bearers).toEqual([`Bearer ${ACCESS_TOKEN}`, `Bearer ${ACCESS_TOKEN}`]);
});

test("a wrong code and a rate-limited send are told in Vietnamese, and the code is never echoed", async ({ page }) => {
  let otpCalls = 0;
  await stubSupabase(page, {
    otp: async (route) => {
      otpCalls += 1;
      if (otpCalls === 1) return route.fulfill({ status: 200, json: {} });
      return route.fulfill({
        status: 429,
        json: { error_code: "over_email_send_rate_limit", msg: "For security purposes, you can only request this after 45 seconds." },
      });
    },
    verify: (route) => route.fulfill({ status: 403, json: { error_code: "otp_expired", msg: "Token has expired or is invalid" } }),
  });
  await freshLanding(page);

  await page.getByRole("button", { name: "Đăng nhập bằng email" }).click();
  await page.getByLabel("Email", { exact: true }).fill("không-phải-email");
  await page.getByRole("button", { name: "Gửi mã" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Email chưa đúng định dạng");
  expect(otpCalls).toBe(0);

  await page.getByLabel("Email", { exact: true }).fill("ban@shopcuaban.vn");
  await page.getByRole("button", { name: "Gửi mã" }).click();
  await page.getByLabel("Mã đăng nhập (6 chữ số)").fill("654321");
  await page.getByRole("button", { name: "Xác nhận" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Mã không đúng hoặc đã hết hạn");
  await expect(page.locator("body")).not.toContainText("654321");
  await shoot(page, "wrong-code");

  // The resend button is locked by the 60 s cooldown; "Dùng email khác" →
  // "Gửi mã" is still locked too, so the rate limit is driven via a fresh form.
  await page.goto("/auth/email");
  await page.getByLabel("Email", { exact: true }).fill("ban@shopcuaban.vn");
  await page.getByRole("button", { name: "Gửi mã" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Bạn đã yêu cầu quá nhiều lần");
  await expect(page.getByRole("button", { name: /^Gửi mã sau \d+ giây$/ })).toBeDisabled();
  await shoot(page, "rate-limited");
});

test("the email's magic link lands on /auth/callback and signs in like Google; an expired link says so", async ({ page }) => {
  await stubJuliApi(page);
  await page.goto(
    `/auth/callback#access_token=${ACCESS_TOKEN}&expires_at=1791600000&expires_in=3600&refresh_token=r-magic&token_type=bearer&type=magiclink`,
  );
  await expect(page).toHaveURL(/\/auth\/connect-shop$/);
  await expect(page.getByText("Bạn đã đăng nhập bằng")).toContainText("ban@shopcuaban.vn");

  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/auth/callback#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Liên kết đăng nhập đã hết hạn hoặc đã được dùng");
});

test("the anonymous avatar menu offers email sign-in beside Google", async ({ page }) => {
  await freshLanding(page);
  await page.getByRole("button", { name: "Dùng thử Demo" }).click();
  await openShopMenu(page);
  await expect(page.getByRole("link", { name: "Đăng nhập với Google", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Đăng nhập bằng email" }).click();
  await expect(page).toHaveURL(/\/auth\/email$/);
  await expect(page.getByRole("heading", { level: 1, name: "Đăng nhập bằng email" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Gửi mã" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await shoot(page, "email-page");
});
