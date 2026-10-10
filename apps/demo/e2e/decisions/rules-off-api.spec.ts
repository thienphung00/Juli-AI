import { expect, test, type Page } from "@playwright/test";

/**
 * P14-F (contract fasttrack/contracts/p14-rules-and-cost.md §3): the rule
 * fields for what no TikTok API gives Juli.
 *
 * - Signed in, /settings: every field is in the rules editor; saving sends the
 *   value the backend stores (PUT /v1/demo/rules/{key}), a refusal shows inline
 *   in Vietnamese, and the saved value comes back with who set it.
 * - Signed out, Quyết định's sample rules editor: the same fields show the
 *   sample values read-only, with no input, and no /v1 request is made.
 */

const UNSET = { value: null, set_by: null, set_by_user_id: null, set_at: null };

function baseRules(over: Record<string, unknown>) {
  return {
    stability_band: {},
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...UNSET, value: 5 },
    auto_levers: { ...UNSET, value: ["attributes", "description", "image", "title"] },
    protected_terms: { ...UNSET, value: [] },
    band_metrics: ["impressions", "ctr"],
    listing_levers: ["title", "description", "attributes", "image"],
    sku_cost: {},
    default_gross_margin_pct: null,
    default_max_discount_pct: null,
    program_fee_pct: null,
    joins_platform_campaigns: null,
    platform_campaign_note: null,
    target_roas: null,
    gmv_max_daily_budget: null,
    live_schedule: null,
    weekdays: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    ...over,
  };
}

async function signedIn(page: Page) {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
  });
  const stored: Record<string, unknown> = {};
  const puts: { key: string; body: Record<string, unknown> }[] = [];
  await page.route("**/v1/**", (route) => route.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  await page.route("**/v1/demo/rules**", async (route) => {
    const request = route.request();
    if (request.method() === "PUT") {
      const key = new URL(request.url()).pathname.split("/").at(-1)!;
      const body = request.postDataJSON() as Record<string, unknown>;
      puts.push({ key, body });
      if (key === "target_roas" && Number(body.value) <= 0) {
        await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "target_roas: value must be > 0" }) });
        return;
      }
      stored[key] = { value: body.value, set_by: body.set_by, set_by_user_id: "u", set_at: "2026-10-10T03:00:00Z" };
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: baseRules(stored) }),
    });
  });
  return puts;
}

test("signed in: the P14 rule fields save, refuse inline, and show who set them", async ({ page }) => {
  const puts = await signedIn(page);
  await page.goto("/settings");
  const group = page.getByTestId("rules-off-api");
  await expect(group).toContainText("Thông tin TikTok không cung cấp");
  for (const label of [
    "Giá vốn theo SKU",
    "Biên lợi nhuận gộp mặc định",
    "Trần giảm giá tối đa (toàn shop)",
    "Phí tham gia chương trình",
    "Tham gia chiến dịch sàn",
    "Chiến dịch đang đăng ký",
    "Mục tiêu ROAS",
    "Ngân sách GMV Max hằng ngày",
    "Khung giờ LIVE thường xuyên",
  ]) {
    await expect(group).toContainText(label);
  }

  const roas = group.getByTestId("rule-target_roas");
  await roas.getByRole("textbox").fill("0");
  await roas.getByRole("button", { name: "Lưu" }).click();
  await expect(roas.getByRole("alert")).toHaveText("ROAS phải lớn hơn 0 và không quá 100.");
  await roas.getByRole("textbox").fill("6");
  await roas.getByRole("button", { name: "Lưu" }).click();
  await expect(roas).toContainText("Bạn đặt");

  const campaigns = group.getByTestId("rule-joins_platform_campaigns");
  await campaigns.getByRole("combobox").selectOption("yes");
  await campaigns.getByRole("button", { name: "Lưu" }).click();
  await expect(campaigns).toContainText("Bạn đặt");

  const live = group.getByTestId("rule-live_schedule");
  await live.getByRole("textbox").fill("T2 T4 T6 20:00-22:00");
  await live.getByRole("button", { name: "Lưu" }).click();
  await expect(live).toContainText("Bạn đặt");

  expect(puts.map((p) => [p.key, p.body.value])).toEqual([
    ["target_roas", 0],
    ["target_roas", 6],
    ["joins_platform_campaigns", true],
    ["live_schedule", [{ days: ["mon", "wed", "fri"], start: "20:00", end: "22:00" }]],
  ]);
  expect(puts.every((p) => p.body.set_by === "seller")).toBe(true);
});

test("signed out: the sample rules editor shows the P14 fields read-only, with no /v1 request", async ({ page }) => {
  const v1: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) v1.push(`${request.method()} ${url.pathname}`);
  });
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.goto("/decisions?quy-tac=1");
  const group = page.getByTestId("rules-off-api");
  await expect(group.getByTestId("off-api-sample-note")).toContainText("Đăng nhập để đặt");
  await expect(group.getByTestId("rule-target_roas")).toContainText("6 lần");
  await expect(group.getByTestId("rule-live_schedule")).toContainText("T3 T5 20:00-22:00");
  await expect(group.getByRole("textbox")).toHaveCount(0);
  await expect(group.getByRole("button")).toHaveCount(0);
  expect(v1).toEqual([]);
});
