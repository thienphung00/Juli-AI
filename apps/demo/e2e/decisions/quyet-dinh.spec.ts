import { mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { enterReplayDemo, navigatePrimaryDestination } from "../helpers/demo-navigation";

/**
 * Quyết định (AC-8.7, ADR-109 d.6, 8–13) end to end: the anonymous door keeps
 * the bundled fixtures and issues no /v1 request; a stubbed signed-in seller
 * sees grouped cards blocked until a stability band is set, sets one in the
 * rules editor, approves the group (sequential approve calls), watches the
 * run's timeline from its SSE stream, and opens Đo lường.
 *
 * Set QD_SHOTS_DIR to also write 1440 / 390 screenshots.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPORT = JSON.parse(readFileSync(resolve(HERE, "../../src/lib/shop-analysis/sample-report.json"), "utf8"));
const SHOTS = process.env.QD_SHOTS_DIR;

function trackApi(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) urls.push(`${request.method()} ${url.pathname}`);
  });
  return urls;
}

test("anonymous Quyết định shows the bundled P10 sample and issues no /v1 request", async ({ page }) => {
  const api = trackApi(page);
  await enterReplayDemo(page);
  await navigatePrimaryDestination(page, "Quyết định");
  await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("recommendation-card").first()).toContainText("SKU · SM-012");
  expect(api).toEqual([]);
});

const RUN_ID = "22222222-2222-4222-8222-222222222222";

function decision(id: string, name: string, lever: string, executable: boolean, gmv: number) {
  return {
    id,
    title: `Tối ưu ${name}`,
    description: "",
    severity: "high",
    priority: 1,
    computed_at: null,
    surfaced_at: null,
    is_executable: executable,
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: "2026-10-08",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: { code: "page", label: "Nhấp → Đặt hàng (trang sản phẩm)" },
        lever: {
          code: lever,
          label: lever,
          action: lever === "product_discount" ? "Giảm giá sản phẩm" : "Viết lại mô tả",
          detail: lever === "product_discount" ? "Giảm theo trần bạn đặt" : "Mô tả dài hơn, có cách dùng, xuống dòng",
          evidence: [{ code: "DESC", source: "tiktok", detail: "Mô tả quá ngắn" }],
        },
        main_kpi: { key: "ctor", label: "CTOR", value: "2,1 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: gmv,
        product_title: name,
        tiktok_product_id: `17290000000${id}`,
      },
    },
  };
}

const DECISIONS = [
  decision("1", "Hộp cơm giữ nhiệt 3 tầng", "description", true, 120_000),
  decision("2", "Bình nước inox 1 lít", "description", true, 80_000),
  decision("3", "Thớt gỗ tròn 30cm", "product_discount", false, 40_000),
];

function ev(seq: number, event_type: string, payload: Record<string, unknown>) {
  return {
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-08T03:01:${String(seq * 3).padStart(2, "0")}Z`,
    payload,
    v: 1,
  };
}

const EVENTS = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "c0", tool_name: "get_product_diagnoses" }),
  ev(3, "tool.completed", { tool_call_id: "c0", tool_name: "get_product_diagnoses", ok: true, summary: 'Có mã: "Mô tả quá ngắn"' }),
  ev(4, "tool.started", { tool_call_id: "c1", tool_name: "get_product_information" }),
  ev(5, "tool.completed", { tool_call_id: "c1", tool_name: "get_product_information", ok: true, summary: "Hoàn tất" }),
  ev(6, "tool.started", { tool_call_id: "c2", tool_name: "get_seo_keywords" }),
  ev(7, "tool.completed", { tool_call_id: "c2", tool_name: "get_seo_keywords", ok: true, summary: "Hoàn tất" }),
  ev(8, "workflow.approval_required", {
    tool_call_id: "c3",
    tool_name: "update_product_listing",
    proposed_change: { description: "Mô tả mới" },
    expires_at: "2099-01-01T00:00:00Z",
    options: [{ option_id: "1", proposed_change: { description: "Mô tả mới, có cách dùng" }, rationale: "Đủ ý, dễ đọc", params_sha: "x" }],
  }),
];

async function signedIn(page: Page) {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
  });
  const report = structuredClone(REPORT);
  report.report.shop_name = "Shop E2E";
  const state = { bandSet: false, approvals: [] as string[], runs: [] as unknown[] };

  await page.route(/\/v1\/demo\/analysis(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) }),
  );
  await page.route("**/v1/demo/analytics*", (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route("**/v1/demo/decisions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data: DECISIONS, error: null }) }),
  );
  await page.route(/\/v1\/demo\/decisions\/[^/]+\/approve$/, async (route) => {
    const id = route.request().url().split("/").at(-2)!;
    state.approvals.push(id);
    const runId = state.approvals.length === 1 ? RUN_ID : `33333333-3333-4333-8333-33333333333${state.approvals.length}`;
    state.runs.unshift({
      id: runId,
      status: state.approvals.length === 1 ? "waiting_approval" : "queued",
      stop_reason: null,
      product_name: DECISIONS.find((d) => d.id === id)!.recommendation.diagnosis.product_title,
      created_at: "2026-10-08T03:01:00Z",
      completed_at: null,
      running_seconds_elapsed: 0,
      latest_narration: null,
      decision_summary: null,
    });
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ success: true, data: { run_id: runId } }) });
  });
  await page.route("**/v1/demo/rules**", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      expect(body).toMatchObject({ scope_ref: "ctr", value: 3, set_by: "team" });
      state.bandSet = true;
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      return;
    }
    const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
    const data = {
      stability_band: state.bandSet ? { ctr: { value: 3, set_by: "team", set_by_user_id: "u", set_at: "2026-10-08T03:00:00Z" } } : {},
      product_cost: {},
      max_discount_pct: {},
      min_margin_pct: null,
      max_open_cards: { ...unset, value: 30 },
      auto_levers: { ...unset, value: ["attributes", "description", "image", "title"] },
      protected_terms: { ...unset, value: [] },
      band_metrics: ["impressions", "ctr", "conversion_rate", "items_sold", "gmv", "sku_orders", "gmv_per_order"],
      listing_levers: ["title", "description", "attributes", "image"],
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data }) });
  });
  await page.route(/\/v1\/demo\/runs$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data: state.runs }) }),
  );
  await page.route(/\/v1\/demo\/runs\/[^/]+\/events/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: EVENTS.map((e) => `id: ${e.sequence_number}\nevent: ${e.event_type}\ndata: ${JSON.stringify(e)}\n\n`).join(""),
    }),
  );
  await page.route(/\/v1\/demo\/runs\/[^/]+\/changes$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ run_id: RUN_ID, reverts_run_id: null, changes: [], revert: { available: false, reason_code: "not_finished", message: null, runs: [] }, question: null }),
    }),
  );
  await page.route("**/v1/demo/revert-questions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data: [] }) }),
  );
  return state;
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: resolve(SHOTS, `${name}-${width}.png`), fullPage: true });
}

test("signed-in: bands gate → rules editor → Duyệt 2 thẻ → SSE timeline → Đo lường", async ({ page }) => {
  const state = await signedIn(page);
  if (SHOTS && test.info().project.name === "desktop") await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto("/decisions");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("3 thẻ tối ưu để nâng CTOR Thẻ sản phẩm");
  const batch = page.getByRole("button", { name: "Duyệt 2 thẻ" });
  await expect(batch).toBeDisabled();
  // AC-10.3: a promotion card names who executes it (Levers.dc.html).
  await expect(page.getByRole("article", { name: "Thớt gỗ tròn 30cm" })).toContainText("Bạn thực hiện trên Seller Center");
  await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
  await shot(page, "de-xuat-bands-missing");

  await page.getByRole("button", { name: "Đặt ngưỡng" }).click();
  await expect(page).toHaveURL(/quy-tac=1/);
  const editor = page.getByTestId("rules-editor");
  await editor.getByRole("checkbox", { name: "Điền thay Seller (đội ngũ Juli)" }).check();
  const ctr = editor.getByTestId("rule-stability_band-ctr");
  await ctr.getByRole("textbox").fill("3");
  await ctr.getByRole("button", { name: "Lưu" }).click();
  await expect(ctr).toContainText("Đội ngũ Juli đặt");
  await shot(page, "rules-editor");
  await editor.getByRole("button", { name: "Đóng" }).click();

  await expect(page.getByTestId("stability-card")).toContainText("CTR · ±3 %");
  await expect(batch).toBeEnabled();
  await shot(page, "de-xuat");
  await batch.click();
  await page.getByRole("dialog").getByRole("button", { name: "Duyệt" }).click();

  await expect(page).toHaveURL(new RegExp(`tab=dang-thuc-hien&run=${RUN_ID}`));
  expect(state.approvals).toEqual(["1", "2"]);
  const timeline = page.getByTestId("run-timeline");
  await expect(timeline).toContainText("Đọc chẩn đoán TikTok");
  await expect(timeline).toContainText('Có mã: "Mô tả quá ngắn"');
  await expect(timeline.locator('[aria-current="step"]')).toContainText("Xác nhận một lần");
  // AC-10.3: the consent block sits under the timeline (Run.dc.html); the queue is one flat list.
  await expect(page.getByTestId("consent-block").getByRole("button", { name: "Xác nhận thay đổi này" })).toBeVisible();
  const queue = page.getByTestId("run-queue");
  await expect(queue).toContainText("Đang chờ bạn");
  await expect(queue).toContainText("Trong hàng đợi");
  await shot(page, "dang-thuc-hien");

  const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll).toBeLessThanOrEqual(inner);

  // AC-10.3: not-yet-reached stages / steps use #6b6b76 instead of the
  // artboards' #8a8a94 so they pass WCAG AA too (owner decision, 2026-10-09).
  const results = await new AxeBuilder({ page })
    .include(".qd-page")
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);

  await page.getByRole("tab", { name: "Đo lường" }).click();
  await expect(page).toHaveURL(/tab=do-luong/);
  await expect(page.getByTestId("measure-list")).toContainText("Chưa có lượt chạy nào ghi thay đổi");
  await shot(page, "do-luong");
});
