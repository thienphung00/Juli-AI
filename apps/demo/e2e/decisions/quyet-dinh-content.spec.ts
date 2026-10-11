import { expect, test, type Page } from "@playwright/test";

/**
 * P14-E "Juli soạn · bạn làm" (`fasttrack/contracts/p14-content-cards.md`,
 * `ContentCards.dc.html`, `ContentRun.dc.html`) in the signed-out sample: the
 * two content cards, the video run from bản 1 to "Đang đo kết quả" and the
 * LIVE run's Không thực hiện — all local, zero requests to a Juli backend route,
 * no model call.
 */

function recordBackendRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) requests.push(`${request.method()} ${url.pathname}`);
  });
  return requests;
}

const contentGroup = (page: Page) => page.locator('[data-testid="decision-group"][data-group-key="content"]');
const contentCard = (page: Page, name: string) =>
  contentGroup(page).getByTestId("recommendation-card").filter({ hasText: name });

test.describe("Signed-out Quyết định — P14-E content cards", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test("the content group shows both cards; video: bản 1 → Soạn lại → bản 2 → Dùng → đăng → Đang đo", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions");

    await expect(contentGroup(page)).toContainText("2 thẻ nội dung: Juli soạn, bạn quay hoặc LIVE");
    await expect(contentGroup(page).getByRole("button", { name: /^Duyệt/ })).toHaveCount(0);
    const video = contentCard(page, "Mặt nạ đất sét 100g");
    const live = contentCard(page, "Son môi số 12");
    await expect(video.getByTestId("drafts-chip")).toHaveText("Juli soạn · bạn làm");
    await expect(live.getByTestId("drafts-chip")).toHaveText("Juli soạn · bạn làm");
    await expect(video).toContainText(/CTR( -)? Video của người bán/);
    await expect(video).toContainText("+1,7 tr ₫/tháng");
    await expect(live).toContainText(/CTOR( -)? LIVE của người bán/);

    await video.getByRole("button", { name: /Xem thêm/ }).click();
    await expect(video).toContainText("Juli sẽ soạn");
    await expect(video).toContainText("Hook 3 giây và 2 phương án mở đầu");
    await expect(video).toContainText("CTR trên các video mới gắn MN-015 trong 7 và 14 ngày, so với video cũ.");

    await video.getByRole("button", { name: "Phê duyệt" }).click();
    await expect(video.getByTestId("card-status")).toHaveText("Đang thực hiện");
    await video.getByRole("link", { name: "Xem tiến độ ›" }).click();

    const run = page.getByTestId("run-detail");
    await expect(run).toContainText("MN-015 · Mặt nạ đất sét 100g · kịch bản video");
    await expect(page.getByTestId("content-steps").getByRole("listitem")).toHaveCount(6);
    const script = page.getByTestId("content-script");
    await expect(script).toContainText("Bản 1 · bạn sửa trực tiếp được");
    // P15: the run shows the canned "Phân tích video" (sample: upload disabled, no request).
    const analysis = run.getByTestId("video-analysis");
    await expect(analysis.getByTestId("video-analysis-result")).toContainText("Sản phẩm xuất hiện lần đầu ở giây 6,0");
    await expect(analysis.getByTestId("video-analysis-input")).toBeDisabled();
    await expect(script).toContainText("Đã kiểm tra: không có từ cấm");

    await script.getByRole("button", { name: "Soạn lại" }).click();
    await expect(script).toContainText("Bản 2 · bạn sửa trực tiếp được");
    await expect(script.getByRole("button", { name: "Soạn lại" })).toBeDisabled();
    await script.getByRole("button", { name: "Dùng kịch bản này" }).click();

    const wait = page.getByTestId("content-wait");
    await expect(wait).toContainText("Đang chờ bạn đăng video");
    await wait.getByRole("button", { name: "Tôi đã đăng video" }).click();
    await expect(page.getByTestId("content-measuring")).toContainText("Đang đo kết quả");
    await expect(page.getByTestId("run-chip")).toHaveText("Đang đo");
    await expect(page.getByRole("button", { name: /Hoàn tác/ })).toHaveCount(0);

    expect(v1).toEqual([]);
  });

  test("LIVE: Không thực hiện at the script asks for one reason and ends the run", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions");
    const live = contentCard(page, "Son môi số 12");
    await live.getByRole("button", { name: "Phê duyệt" }).click();
    await live.getByRole("link", { name: "Xem tiến độ ›" }).click();

    const script = page.getByTestId("content-script");
    await expect(script).toContainText("Kịch bản host cho SM-012 + thứ tự giỏ");
    await script.getByRole("button", { name: "Không thực hiện" }).click();
    const dialog = page.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await dialog.getByRole("radio", { name: "Văn phong chưa phù hợp" }).check();
    await dialog.getByRole("button", { name: "Đồng ý" }).click();
    await expect(page.getByTestId("reason-done")).toContainText("Hoàn thành · không thực hiện thay đổi");
    await expect(page.getByTestId("run-chip")).toHaveText("Không thay đổi");

    expect(v1).toEqual([]);
  });
});
