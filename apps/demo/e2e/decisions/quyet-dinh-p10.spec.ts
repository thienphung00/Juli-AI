import { mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  INSTRUCTIONS,
  LEVER_CARDS,
  MAIN_CARD,
  MANUAL_CARD,
  NOW,
  PHOTO_CARD,
  PHOTO_CHECKS,
  RUN,
  SHOP,
  changes,
  decision,
  events,
  listingEvents,
  manualEvents,
  measurement,
  photoEvents,
  revertEvents,
  rules,
  runItem,
  vn,
  type CardSpec,
} from "./p10-fixtures";

/**
 * Quyết định to the approved artboards (AC-10.3, ADR-109 Amendment 1),
 * end to end against a stubbed API shaped like the P10 contract
 * (`fasttrack/contracts/p10-quyet-dinh.md`): the card (Xem thêm, Phê duyệt
 * notice, Từ chối with a required reason), consent with an edit →
 * `edited_values`, Không thực hiện → decline with a reason, the cover-image
 * upload, the Seller Center checklist gating "Tôi đã áp dụng", Đo lường's
 * stage tabs and day-7 "Hoàn tác?", the revert conflict.
 *
 * Set QD_P10_SHOTS_DIR to also write one screenshot per artboard state
 * (`<Artboard>--<state>--app-<width>.png`) for the fidelity comparison.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPORT = JSON.parse(readFileSync(resolve(HERE, "../../src/lib/shop-analysis/sample-report.json"), "utf8"));
const SHOTS = process.env.QD_P10_SHOTS_DIR;

interface Scenario {
  decisions: CardSpec[];
  runs: Record<string, unknown>[];
  events: Record<string, ReturnType<typeof events>>;
  changes: Record<string, unknown>;
  measurement: Record<string, unknown>;
  revert?: { status: number; body: unknown };
}

interface Recorded {
  method: string;
  path: string;
  body: unknown;
  contentType: string | null;
}

function scenario(over: Partial<Scenario> = {}): Scenario {
  return { decisions: [MAIN_CARD], runs: [], events: {}, changes: {}, measurement: {}, ...over };
}

async function stub(page: Page, s: Scenario): Promise<Recorded[]> {
  const posts: Recorded[] = [];
  await page.clock.setFixedTime(new Date(NOW));
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  const report = structuredClone(REPORT);
  report.report.shop_name = SHOP.name;
  const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route(/\/v1\/demo\/analysis(\?.*)?$/, (route) => route.fulfill(json(report)));
  await page.route("**/v1/demo/analytics*", (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(/\/v1\/demo\/rules/, (route) => route.fulfill(json({ success: true, data: rules() })));
  await page.route(/\/v1\/demo\/revert-questions/, async (route) => {
    if (route.request().method() === "POST") {
      posts.push({ method: "POST", path: new URL(route.request().url()).pathname, body: null, contentType: null });
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill(json({ success: true, data: [] }));
  });
  await page.route(/\/v1\/demo\/decisions(\/.*)?$/, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET") return route.fulfill(json({ success: true, data: s.decisions.map(decision), error: null }));
    posts.push({ method: "POST", path, body: request.postDataJSON(), contentType: request.headers()["content-type"] ?? null });
    if (path.endsWith("/approve")) return route.fulfill(json({ success: true, data: { run_id: RUN.listing } }, 202));
    if (path.endsWith("/reject")) return route.fulfill(json({ status: "rejected", cooldown_until: "2026-10-16T02:00:00Z" }));
    return route.fulfill({ status: 404, body: "{}" });
  });
  await page.route(/\/v1\/demo\/runs(\/.*)?$/, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const parts = path.split("/");
    const runId = parts[4];
    const leaf = parts[5];
    if (request.method() === "POST") {
      const type = request.headers()["content-type"] ?? null;
      posts.push({ method: "POST", path, body: type?.includes("json") ? request.postDataJSON() : request.postData(), contentType: type });
      if (leaf === "confirmations") return route.fulfill(json({ decision: "approve", status: "accepted", celery_task_id: "t" }, 202));
      if (leaf === "decline") return route.fulfill(json({ status: "declined", cooldown_until: "2026-10-16T02:00:00Z" }));
      if (leaf === "photo") return route.fulfill(json({ checks: PHOTO_CHECKS }, 202));
      if (leaf === "applied") return route.fulfill(json({}, 202));
      if (leaf === "revert") {
        const answer = s.revert ?? { status: 202, body: { success: true, data: { run_id: RUN.revert } } };
        return route.fulfill(json(answer.body, answer.status));
      }
      return route.fulfill({ status: 404, body: "{}" });
    }
    if (!runId) return route.fulfill(json({ success: true, data: s.runs }));
    if (leaf === "events") {
      const list = s.events[runId] ?? [];
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: list.map((e) => `id: ${e.sequence_number}\nevent: ${e.event_type}\ndata: ${JSON.stringify(e)}\n\n`).join(""),
      });
    }
    if (leaf === "changes") return route.fulfill(json(s.changes[runId] ?? changes(runId, { changes: [] })));
    if (leaf === "measurement") {
      const m = s.measurement[runId];
      return m ? route.fulfill(json(m)) : route.fulfill({ status: 404, body: "{}" });
    }
    if (leaf === "instructions") return route.fulfill(json(INSTRUCTIONS));
    return route.fulfill({ status: 404, body: "{}" });
  });
  return posts;
}

async function shot(page: Page, name: string, target?: Locator) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const width = page.viewportSize()?.width ?? 0;
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  const path = resolve(SHOTS, `${name}--app-${width}.png`);
  if (target) await target.screenshot({ path });
  else await page.locator(".qd-page").screenshot({ path });
}

async function dialogShot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const width = page.viewportSize()?.width ?? 0;
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  await page.screenshot({ path: resolve(SHOTS, `${name}--app-${width}.png`) });
}

const LISTING_RUN = (over: Record<string, unknown> = {}) => runItem(RUN.listing, MAIN_CARD.name, over);
const QUEUE = [
  runItem(RUN.queued1, LEVER_CARDS[2].name, { status: "queued" }),
  runItem(RUN.queued2, LEVER_CARDS[3].name, { status: "queued" }),
];
const RUN_DECISIONS = [MAIN_CARD, LEVER_CARDS[2], LEVER_CARDS[3]];

function listingScenario(phase: Parameters<typeof listingEvents>[0]): Scenario {
  const runOver =
    phase === "consent"
      ? { status: "waiting_approval" }
      : phase === "done"
        ? { status: "completed", stop_reason: "final_response", completed_at: vn("10:47:31") }
        : phase === "declined"
          ? { status: "completed", stop_reason: "confirmation_declined", completed_at: vn("10:02:00") }
          : { status: "running" };
  return scenario({
    decisions: RUN_DECISIONS,
    runs: [LISTING_RUN(runOver), ...QUEUE],
    events: { [RUN.listing]: events(RUN.listing, listingEvents(phase)) },
    changes: { [RUN.listing]: changes(RUN.listing) },
  });
}

function photoScenario(phase: Parameters<typeof photoEvents>[0]): Scenario {
  const runOver =
    phase === "upload"
      ? { status: "waiting_external", awaiting: "photo" }
      : phase === "consent"
        ? { status: "waiting_approval" }
        : phase === "done"
          ? { status: "completed", stop_reason: "final_response", completed_at: vn("15:02:32") }
          : phase === "declined"
            ? { status: "completed", stop_reason: "confirmation_declined", completed_at: vn("14:23:00") }
            : { status: "running" };
  return scenario({
    decisions: [PHOTO_CARD],
    runs: [runItem(RUN.photo, PHOTO_CARD.name, runOver)],
    events: { [RUN.photo]: events(RUN.photo, photoEvents(phase)) },
    changes: {
      [RUN.photo]: changes(RUN.photo, {
        changes: [{ field: "main_images", label: "Ảnh bìa", before: { count: 1 }, after: { count: 1 }, after_source: "read", recorded_at: null }],
      }),
    },
  });
}

function manualScenario(phase: Parameters<typeof manualEvents>[0]): Scenario {
  const runOver =
    phase === "guide"
      ? { status: "waiting_external", awaiting: "seller_action" }
      : phase === "done"
        ? { status: "completed", stop_reason: "final_response", completed_at: vn("11:20:10") }
        : phase === "skipped"
          ? { status: "completed", stop_reason: "confirmation_declined", completed_at: vn("11:20:00") }
          : { status: "running" };
  return scenario({
    decisions: [MANUAL_CARD],
    runs: [runItem(RUN.manual, MANUAL_CARD.name, runOver)],
    events: { [RUN.manual]: events(RUN.manual, manualEvents(phase)) },
    changes: { [RUN.manual]: changes(RUN.manual, { changes: [], revert: { available: false, reason_code: "seller_center", message: null, runs: [] } }) },
  });
}

function revertScenario(phase: Parameters<typeof revertEvents>[0]): Scenario {
  const runOver =
    phase === "consent"
      ? { status: "waiting_approval" }
      : phase === "done"
        ? { status: "completed", stop_reason: "final_response", completed_at: vn("09:48:01", "2026-10-16") }
        : phase === "conflict"
          ? { status: "failed", stop_reason: "concurrency_conflict", completed_at: vn("09:13:30", "2026-10-16") }
          : phase === "cancelled"
            ? { status: "completed", stop_reason: "confirmation_declined", completed_at: vn("09:14:30", "2026-10-16") }
            : { status: "running" };
  return scenario({
    decisions: [MAIN_CARD],
    runs: [
      runItem(RUN.revert, MAIN_CARD.name, { ...runOver, created_at: vn("09:12:00", "2026-10-16") }),
      LISTING_RUN({ status: "completed", stop_reason: "final_response", completed_at: vn("10:47:31") }),
    ],
    events: {
      [RUN.revert]: events(RUN.revert, revertEvents(phase)),
      [RUN.listing]: events(RUN.listing, listingEvents("done")),
    },
    changes: {
      [RUN.revert]: changes(RUN.revert, { reverts_run_id: RUN.listing, changes: phase === "done" ? changes(RUN.revert).changes : [] }),
      [RUN.listing]: changes(RUN.listing),
    },
  });
}

function measureScenario(m: ReturnType<typeof measurement> | null): Scenario {
  return scenario({
    decisions: [MAIN_CARD],
    runs: [LISTING_RUN({ status: "completed", stop_reason: "final_response", completed_at: vn("10:47:31") })],
    events: { [RUN.listing]: events(RUN.listing, listingEvents("done")) },
    changes: { [RUN.listing]: changes(RUN.listing) },
    measurement: m ? { [RUN.listing]: m } : {},
  });
}

const RUN_URL = (id: string) => `/decisions?tab=dang-thuc-hien&run=${id}`;

// -- behaviour ----------------------------------------------------------------------

test.describe("P10 Đề xuất card", () => {
  test("Xem thêm expands in place; Phê duyệt shows the notice; Từ chối needs one reason", async ({ page }) => {
    const posts = await stub(page, scenario({ decisions: [MAIN_CARD, LEVER_CARDS[2]] }));
    await page.goto("/decisions");
    const card = page.getByTestId("recommendation-card").filter({ hasText: "Son môi số 12" });
    await expect(card.getByTestId("card-status")).toHaveText("Chờ duyệt");
    await expect(card).toContainText("SKU · SM-012");
    await expect(card).not.toContainText("Lý do đầy đủ");
    await card.getByRole("button", { name: /Xem thêm/ }).click();
    await expect(card).toContainText("Lý do đầy đủ");
    await expect(card).toContainText("TikTok báo mã chẩn đoán: “Mô tả quá ngắn”.");
    await expect(card.getByRole("button", { name: /Thu gọn/ })).toHaveAttribute("aria-expanded", "true");

    await card.getByRole("button", { name: "Phê duyệt" }).click();
    await expect(card.getByTestId("card-status")).toHaveText("Đang thực hiện");
    await expect(card.getByRole("status")).toContainText("Đã tạo lượt chạy.");
    await expect(card.getByRole("link", { name: "Xem tiến độ ›" })).toBeVisible();
    expect(posts.map((p) => p.path)).toContain("/v1/demo/decisions/1/approve");

    const other = page.getByTestId("recommendation-card").filter({ hasText: "Mặt nạ đất sét" });
    await other.getByRole("button", { name: "Từ chối" }).click();
    const dialog = page.getByRole("dialog", { name: "Từ chối thẻ này?" });
    await expect(dialog.getByRole("button", { name: "Từ chối thẻ" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "Lý do hoặc số liệu chưa thuyết phục" }).check();
    await dialog.getByRole("textbox").fill("Số liệu cũ");
    await dialog.getByRole("button", { name: "Từ chối thẻ" }).click();
    await expect(other.getByTestId("card-status")).toHaveText("Đã từ chối");
    await expect(other).toContainText("Đã từ chối. Juli không thay đổi gì trên sản phẩm này.");
    expect(posts.find((p) => p.path.endsWith("/13/reject"))?.body).toEqual({ reason_code: "not_convincing", note: "Số liệu cũ" });
  });
});

test.describe("P10 Đang thực hiện", () => {
  test("consent edit sends edited_values; Không thực hiện declines with a reason", async ({ page }) => {
    const posts = await stub(page, listingScenario("consent"));
    await page.goto(RUN_URL(RUN.listing));
    const consent = page.getByTestId("consent-block");
    await expect(consent).toContainText("Còn hiệu lực 3 giờ 58 phút");
    await expect(consent.getByRole("button", { name: "Xác nhận thay đổi này" })).toBeDisabled();
    await consent.getByRole("button", { name: "✎ Sửa nội dung trước khi áp dụng" }).click();
    await page.getByLabel("Tiêu đề (bạn sửa)").fill("Son môi lì số 12 — màu đỏ ruby");
    await page.getByRole("button", { name: "Lưu bản sửa" }).click();
    await expect(consent).toContainText("Bạn đã sửa");
    await consent.getByRole("button", { name: "Xác nhận thay đổi này" }).click();
    await expect.poll(() => posts.find((p) => p.path.includes("/confirmations/"))?.body).toMatchObject({
      decision: "approve",
      option_id: "opt-1",
      edited_values: { title: "Son môi lì số 12 — màu đỏ ruby" },
    });

    await page.getByRole("button", { name: "Không thực hiện" }).click();
    const dialog = page.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await expect(dialog.getByRole("button", { name: "Kết thúc, không thay đổi" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "Văn phong chưa phù hợp" }).check();
    await dialog.getByRole("button", { name: "Kết thúc, không thay đổi" }).click();
    await expect.poll(() => posts.find((p) => p.path.endsWith("/decline"))?.body).toEqual({ reason_code: "tone" });
    await expect(page.getByTestId("run-detail")).toContainText("Bạn đã chọn không thay đổi.");
  });

  test("cover image: the upload posts the file and shows the checks", async ({ page }) => {
    const posts = await stub(page, photoScenario("upload"));
    await page.goto(RUN_URL(RUN.photo));
    await expect(page.getByTestId("photo-request")).toContainText("Juli cần ảnh bìa mới từ bạn");
    await page.getByTestId("photo-input").setInputFiles({ name: "anh.png", mimeType: "image/png", buffer: Buffer.from([137, 80, 78, 71]) });
    await expect(page.getByTestId("photo-checks")).toContainText("1200 × 1200 px");
    const upload = posts.find((p) => p.path.endsWith("/photo"));
    expect(upload?.contentType).toContain("multipart/form-data");
  });

  test("promotion: Tôi đã áp dụng is enabled only once every step is ticked", async ({ page }) => {
    const posts = await stub(page, manualScenario("guide"));
    await page.goto(RUN_URL(RUN.manual));
    const guide = page.getByTestId("seller-guide");
    await expect(guide).toContainText("Làm theo 4 bước trên Seller Center");
    await expect(guide.getByRole("link", { name: "Mở Seller Center ↗" })).toHaveAttribute("href", INSTRUCTIONS.deep_link);
    const applied = guide.getByRole("button", { name: "Tôi đã áp dụng" });
    const boxes = guide.getByRole("checkbox");
    for (let i = 0; i < 3; i += 1) await boxes.nth(i).check();
    await expect(applied).toBeDisabled();
    await boxes.nth(3).check();
    await applied.click();
    await expect.poll(() => posts.some((p) => p.path.endsWith("/applied"))).toBe(true);
  });

  test("Hoàn tác asks one reason; a 409 external_change shows Juli stops", async ({ page }) => {
    const s = listingScenario("done");
    s.revert = {
      status: 409,
      body: { detail: { code: "external_change", message: "Tiêu đề của sản phẩm đã được thay đổi bên ngoài Juli sau khi Juli ghi.", fields: ["title"] } },
    };
    const posts = await stub(page, s);
    await page.goto(RUN_URL(RUN.listing));
    await page.getByRole("button", { name: "Hoàn tác" }).click();
    const dialog = page.getByRole("dialog", { name: "Hoàn tác thay đổi này?" });
    await expect(dialog.getByRole("button", { name: "Bắt đầu hoàn tác" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "Doanh số hoặc chỉ số giảm" }).check();
    await dialog.getByRole("button", { name: "Bắt đầu hoàn tác" }).click();
    await expect(page.getByTestId("revert-conflict")).toContainText("Juli dừng, không ghi đè");
    await expect(page.getByTestId("revert-conflict")).toContainText("thay đổi bên ngoài Juli");
    expect(posts.find((p) => p.path.endsWith("/revert"))?.body).toEqual({ reason_code: "metrics_dropped" });
  });
});

test.describe("P10 Đo lường", () => {
  test("stage tabs follow measurement.stage; day 7 outside the band asks Hoàn tác?", async ({ page }) => {
    const posts = await stub(page, measureScenario(measurement("d7bad")));
    await page.goto("/decisions?tab=do-luong");
    await expect(page.getByRole("tab", { name: "Ngày 7 · kiểm tra" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ngày 7: một chỉ số ra ngoài khoảng bạn cho phép");
    await expect(page.getByTestId("measure-target")).toContainText("9.613 – 10.207");
    await expect(page.getByTestId("day7-ask")).toContainText("AOV còn 152k ₫ (−5,0 %)");
    await page.getByRole("button", { name: "Giữ thay đổi" }).click();
    await expect.poll(() => posts.some((p) => p.path.endsWith("/revert-questions/q-1/dismiss"))).toBe(true);
    await page.getByRole("tab", { name: "Ngày 0" }).click();
    await expect(page).toHaveURL(/moc=ngay-0/);
  });
});

// -- fidelity screenshots (QD_P10_SHOTS_DIR) ------------------------------------------------

test.describe("P10 fidelity screenshots", () => {
  test.skip(!SHOTS, "set QD_P10_SHOTS_DIR to write the fidelity screenshots");
  test.setTimeout(600_000);

  async function at(page: Page, width: number) {
    await page.setViewportSize({ width, height: 1200 });
  }

  for (const width of [1440, 390]) {
    test(`Main / Mobile / Decline (reject) @${width}`, async ({ page }) => {
      test.skip(test.info().project.name !== "desktop");
      await stub(page, scenario({ decisions: [MAIN_CARD] }));
      await at(page, width);
      await page.goto("/decisions");
      const card = page.getByTestId("recommendation-card").first();
      await expect(card).toBeVisible();
      const prefix = width === 390 ? "Mobile" : "Main";
      await shot(page, `${prefix}--collapsed`, card);
      await card.getByRole("button", { name: /Xem thêm/ }).click();
      await shot(page, `${prefix}--expanded`, card);
      await card.getByRole("button", { name: /Thu gọn/ }).click();
      await card.getByRole("button", { name: "Từ chối" }).click();
      await dialogShot(page, "Decline--reject-dialog");
      await page.getByRole("radio", { name: "Lý do hoặc số liệu chưa thuyết phục" }).check();
      await dialogShot(page, "Decline--reject-dialog-picked");
      await page.getByRole("button", { name: "Từ chối thẻ" }).click();
      await expect(card.getByTestId("card-status")).toHaveText("Đã từ chối");
      await shot(page, `${prefix}--rejected`, card);
      await shot(page, "Decline--reject-done", card);
    });

    test(`Main approved @${width}`, async ({ page }) => {
      test.skip(test.info().project.name !== "desktop");
      await stub(page, scenario({ decisions: [MAIN_CARD] }));
      await at(page, width);
      await page.goto("/decisions");
      const card = page.getByTestId("recommendation-card").first();
      await card.getByRole("button", { name: "Phê duyệt" }).click();
      await expect(card.getByTestId("card-status")).toHaveText("Đang thực hiện");
      await shot(page, `${width === 390 ? "Mobile" : "Main"}--approved`, card);
    });

    test(`Levers @${width}`, async ({ page }) => {
      test.skip(test.info().project.name !== "desktop");
      await stub(page, scenario({ decisions: LEVER_CARDS }));
      await at(page, width === 1440 ? 2064 : 390);
      await page.goto("/decisions");
      await expect(page.getByTestId("recommendation-card").first()).toBeVisible();
      await shot(page, "Levers--default");
    });

    for (const phase of ["consent", "writing", "review", "done", "declined"] as const) {
      test(`Run ${phase} @${width}`, async ({ page }) => {
        test.skip(test.info().project.name !== "desktop");
        await stub(page, listingScenario(phase));
        await at(page, width === 1440 ? 1144 : 390);
        await page.goto(RUN_URL(RUN.listing));
        await expect(page.getByTestId("run-timeline")).toBeVisible();
        await shot(page, `Run--${phase}`);
        if (phase === "consent") {
          await page.getByTestId("consent-block").locator(".qv-option").click();
          await shot(page, "Run--consent-selected");
          await page.getByRole("button", { name: "✎ Sửa nội dung trước khi áp dụng" }).click();
          await shot(page, "Run--editing");
          await page.getByLabel("Tiêu đề (bạn sửa)").fill("Son môi lì số 12 — màu đỏ ruby");
          await page.getByRole("button", { name: "Lưu bản sửa" }).click();
          await shot(page, "Run--edited");
          await page.getByRole("button", { name: "Không thực hiện" }).click();
          await dialogShot(page, "Decline--skip-dialog");
          await page.getByRole("radio", { name: "Văn phong chưa phù hợp" }).check();
          await dialogShot(page, "Decline--skip-dialog-picked");
          await page.getByRole("button", { name: "Kết thúc, không thay đổi" }).click();
          await expect(page.getByTestId("run-detail")).toContainText("Bạn đã chọn không thay đổi.");
          await shot(page, "Decline--skip-done");
          await page.getByRole("button", { name: "Thu gọn" }).click();
          await shot(page, "Run--collapsed");
        }
        if (phase === "done") {
          await page.getByRole("button", { name: "Hoàn tác" }).click();
          await dialogShot(page, "Revert--reason");
          await page.getByRole("radio", { name: "Doanh số hoặc chỉ số giảm" }).check();
          await dialogShot(page, "Revert--reason-picked");
        }
      });
    }

    for (const phase of ["upload", "consent", "writing", "review", "done", "declined"] as const) {
      test(`RunPhoto ${phase} @${width}`, async ({ page }) => {
        test.skip(test.info().project.name !== "desktop");
        await stub(page, photoScenario(phase));
        await at(page, width === 1440 ? 1144 : 390);
        await page.goto(RUN_URL(RUN.photo));
        await expect(page.getByTestId("run-timeline")).toBeVisible();
        await shot(page, `RunPhoto--${phase}`);
        if (phase === "consent") {
          await page.getByTestId("consent-block").locator(".qv-option").click();
          await shot(page, "RunPhoto--consent-selected");
        }
        if (phase === "upload") {
          await page.getByRole("button", { name: "Thu gọn" }).click();
          await shot(page, "RunPhoto--collapsed");
        }
      });
    }

    for (const phase of ["guide", "verify", "done", "skipped"] as const) {
      test(`RunManual ${phase} @${width}`, async ({ page }) => {
        test.skip(test.info().project.name !== "desktop");
        await stub(page, manualScenario(phase));
        await at(page, width === 1440 ? 1144 : 390);
        await page.goto(RUN_URL(RUN.manual));
        await expect(page.getByTestId("run-timeline")).toBeVisible();
        await shot(page, `RunManual--${phase}`);
        if (phase === "guide") {
          const boxes = page.getByTestId("seller-guide").getByRole("checkbox");
          for (let i = 0; i < 4; i += 1) await boxes.nth(i).check();
          await shot(page, "RunManual--guide-ticked");
          await page.getByRole("button", { name: "Thu gọn" }).click();
          await shot(page, "RunManual--collapsed");
        }
      });
    }

    for (const phase of ["consent", "writing", "review", "done", "conflict", "cancelled"] as const) {
      test(`Revert ${phase} @${width}`, async ({ page }) => {
        test.skip(test.info().project.name !== "desktop");
        await stub(page, revertScenario(phase));
        await at(page, width === 1440 ? 1144 : 390);
        await page.goto(RUN_URL(RUN.revert));
        await expect(page.getByTestId("run-timeline")).toBeVisible();
        await shot(page, `Revert--${phase}`);
        if (phase === "consent") {
          await page.getByTestId("consent-block").locator(".qv-option").click();
          await shot(page, "Revert--consent-selected");
        }
      });
    }

    const MEASURES = [
      ["Measure--d0", measurement("waiting")],
      ["Measure--d7-ok", measurement("d7ok")],
      ["Measure--d7-bad", measurement("d7bad")],
      ["Measure--d14", measurement("final", "gan_dat")],
      ["Day7--ok", measurement("d7ok")],
      ["Day7--bad", measurement("d7bad")],
      ["Day14--dat", measurement("final", "dat")],
      ["Day14--gan-dat", measurement("final", "gan_dat")],
      ["Day14--khong-dat", measurement("final", "khong_dat")],
      ["Day14--chua-ket-luan", measurement("final", "chua_ket_luan")],
    ] as const;
    for (const [name, m] of MEASURES) {
      test(`${name} @${width}`, async ({ page }) => {
        test.skip(test.info().project.name !== "desktop");
        await stub(page, measureScenario(m));
        await at(page, width === 1440 ? (name.startsWith("Measure") ? 944 : 1144) : 390);
        await page.goto("/decisions?tab=do-luong");
        await expect(page.getByTestId("measure-panel")).toBeVisible();
        await shot(page, name);
        if (name === "Measure--d0") {
          await page.getByTestId("measure-panel").getByRole("button", { name: "Thu gọn" }).click();
          await shot(page, "Measure--collapsed");
        }
        if (name === "Day7--bad") {
          await page.getByRole("button", { name: "Giữ thay đổi" }).click();
          await expect(page.getByTestId("measure-panel")).toContainText("Bạn giữ thay đổi.");
          await shot(page, "Day7--bad-keep");
        }
      });
    }

    test(`Day7 bad → revert @${width}`, async ({ page }) => {
      test.skip(test.info().project.name !== "desktop");
      await stub(page, measureScenario(measurement("d7bad")));
      await at(page, width === 1440 ? 1144 : 390);
      await page.goto("/decisions?tab=do-luong");
      await page.getByTestId("day7-ask").getByRole("button", { name: "Hoàn tác" }).click();
      await page.getByRole("radio", { name: "Doanh số hoặc chỉ số giảm" }).check();
      await page.getByRole("button", { name: "Bắt đầu hoàn tác" }).click();
      await expect(page.getByTestId("measure-panel")).toContainText("Đã tạo lượt chạy hoàn tác");
      await shot(page, "Day7--bad-revert");
    });
  }
});
