import { expect, test, type Page } from "@playwright/test";

import { enterReplayDemo } from "../helpers/demo-navigation";

/**
 * P15 "Phân tích video" (`fasttrack/contracts/p15-content-analysis.md`) in
 * Phân tích › Nội dung row detail: the signed-out sample's canned analysis (no
 * /v1 request, upload disabled), and a stubbed signed-in seller uploading a
 * file in chunks → queued → done.
 */

function trackApi(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) urls.push(`${request.method()} ${url.pathname}`);
  });
  return urls;
}

async function openFirstVideoRow(page: Page) {
  await page.getByRole("tab", { name: "Nội dung" }).click();
  await expect(page.getByRole("heading", { name: "Video tác động CTR nhiều nhất" })).toBeVisible();
  const first = page.getByTestId("pa-row").first();
  await first.getByRole("button", { expanded: false }).first().click();
  return first;
}

test("signed out: a video row shows the canned analysis and no request is made", async ({ page }) => {
  const api = trackApi(page);
  await enterReplayDemo(page);
  await page.goto("/analytics");
  const row = await openFirstVideoRow(page);
  const block = row.getByTestId("video-analysis");
  await expect(block.getByText("Bản minh họa", { exact: true })).toBeVisible();
  await expect(block.getByTestId("video-analysis-result")).toContainText("Sản phẩm xuất hiện lần đầu ở giây 6,0");
  for (const label of ["Giây sản phẩm xuất hiện", "Lời kêu gọi mua (CTA)", "Nhịp cắt", "Vấn đề", "Gợi ý"]) {
    await expect(block.getByText(label, { exact: true })).toBeVisible();
  }
  await expect(block.getByTestId("video-analysis-input")).toBeDisabled();
  expect(api).toEqual([]);
});

test("signed in: upload in chunks, then the analysis appears", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
  });
  const { sampleEnvelope, sampleRankings } = await import("../../src/lib/phan-tich/sample-data");
  const { SAMPLE_ANALYSES } = await import("../../src/lib/content-analysis/sample");
  const report = sampleEnvelope();
  report.report.shop_name = "Shop E2E";
  const rankings = sampleRankings();
  await page.route("**/v1/demo/analysis/rankings*", async (route) => {
    const url = new URL(route.request().url());
    const body = (rankings[url.searchParams.get("stream") as keyof typeof rankings] as Record<string, unknown> | undefined)?.[
      url.searchParams.get("metric") ?? ""
    ];
    await route.fulfill(body ? { status: 200, contentType: "application/json", body: JSON.stringify(body) } : { status: 404, body: "{}" });
  });
  await page.route(/\/v1\/demo\/analysis(\?.*)?$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) }));
  await page.route(/\/v1\/demo\/decisions(\?.*)?$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"data":[]}' }));
  await page.route("**/v1/demo/analytics*", (route) => route.fulfill({ status: 404, body: "{}" }));

  const size = 3 * 1024 * 1024 + 100;
  const chunk = 1024 * 1024;
  let received = 0;
  const puts: number[] = [];
  let created: Record<string, unknown> | null = null;
  const base = { ...SAMPLE_ANALYSES.video, id: "an-1", result: null, file_deleted: false };
  await page.route(/\/v1\/demo\/content-analysis(\?.*)?$/, async (route) => {
    const request = route.request();
    expect(request.headers()["authorization"]).toBe("Bearer e2e-token");
    expect(request.headers()["x-shop-id"]).toBe("shop-e2e");
    if (request.method() === "POST") {
      created = request.postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            analysis: { ...base, status: "awaiting_upload", status_label: "Đang tải lên", upload: { received_bytes: 0, size_bytes: size } },
            upload: { url: "/v1/demo/content-analysis/an-1/file", token: "123.abc", chunk_bytes: chunk, expires_at: "2026-10-10T12:00:00Z" },
          },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"data":[]}' });
  });
  await page.route("**/v1/demo/content-analysis/an-1/file*", async (route) => {
    const url = new URL(route.request().url());
    puts.push(Number(url.searchParams.get("offset")));
    received += route.request().postDataBuffer()?.length ?? 0;
    const status = received >= size ? "queued" : "awaiting_upload";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { ...base, status, status_label: status === "queued" ? "Đang chờ phân tích" : "Đang tải lên", upload: { received_bytes: received, size_bytes: size } } }),
    });
  });
  await page.route("**/v1/demo/content-analysis/an-1", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { ...SAMPLE_ANALYSES.video, id: "an-1" } }) }),
  );

  await page.goto("/analytics");
  const row = await openFirstVideoRow(page);
  const block = row.getByTestId("video-analysis");
  await expect(block.getByText(/Tải video của bạn lên/)).toBeVisible();
  const bytes = Buffer.alloc(size);
  bytes.write("ftypisom", 4, "latin1");
  await block.getByTestId("video-analysis-input").setInputFiles({ name: "clip.mp4", mimeType: "video/mp4", buffer: bytes });
  await expect(block.getByTestId("video-analysis-result")).toBeVisible({ timeout: 20_000 });
  await expect(block.getByTestId("video-analysis-status")).toHaveText("Đã phân tích");
  expect(puts).toEqual([0, chunk, 2 * chunk, 3 * chunk]);
  expect(created).toMatchObject({ kind: "video", file_name: "clip.mp4", content_type: "video/mp4", size_bytes: size });
  expect(String((created as Record<string, unknown> | null)?.content_ref)).toMatch(/^video:/);
});
