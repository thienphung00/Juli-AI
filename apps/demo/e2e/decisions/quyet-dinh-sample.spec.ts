import { expect, test, type Page } from "@playwright/test";

/**
 * P11: signed out, Quyết định is the P10 design as a sample ("Bản minh họa",
 * ADR-094 d.1) — the same card, Đang thực hiện timeline and Đo lường as the
 * signed-in door, fed by bundled fixtures. Every action changes local state
 * only: the whole walk issues no request to a Juli backend route.
 *
 * Also P11: the sign-in lives in localStorage, so it survives a new tab.
 */

function recordBackendRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) requests.push(`${request.method()} ${url.pathname}`);
  });
  return requests;
}

const card = (page: Page, name: string) => page.getByTestId("recommendation-card").filter({ hasText: name });

test.describe("Signed-out Quyết định — the P10 sample", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test("Đề xuất shows the P10 card; approve → consent → confirm plays to the end, with zero /v1 requests", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions");

    await expect(page.getByTestId("mock-data-notice")).toContainText("Dữ liệu mẫu");
    const main = card(page, "Son môi số 12");
    await expect(main.getByTestId("card-status")).toHaveText("Chờ duyệt");
    await expect(main).toContainText("SKU · SM-012");
    await expect(main).toContainText("5,4 %");
    await expect(main).toContainText("5,9 %");
    await expect(main).toContainText("+2,1 tr ₫/tháng");
    await expect(card(page, "Sữa rửa mặt amino 150ml")).toContainText("Juli tải lên — cần ảnh từ bạn");
    await expect(card(page, "Kem dưỡng ẩm ceramide")).toContainText("Bạn thực hiện trên Seller Center");

    await main.getByRole("button", { name: /Xem thêm/ }).click();
    await expect(main).toContainText("TikTok báo mã chẩn đoán: “Mô tả quá ngắn”.");
    await main.getByRole("button", { name: /Thu gọn/ }).click();

    await main.getByRole("button", { name: "Phê duyệt" }).click();
    await expect(main.getByTestId("card-status")).toHaveText("Đang thực hiện");
    await main.getByRole("link", { name: "Xem tiến độ ›" }).click();

    const consent = page.getByTestId("consent-block");
    await expect(consent).toContainText("Juli đề xuất thay đổi sau");
    await consent.locator(".qv-option").click();
    await consent.getByRole("button", { name: "Xác nhận thay đổi này" }).click();
    await expect(page.getByTestId("run-timeline")).toContainText("Phiên bản mới đã được duyệt");
    await expect(page.getByRole("button", { name: "Hoàn tác" })).toBeVisible();

    await page.getByRole("tab", { name: "Đo lường" }).click();
    await expect(page.getByTestId("measure-panel").first()).toBeVisible();

    expect(v1).toEqual([]);
  });

  test("Từ chối needs one reason and stays local", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions");
    const other = card(page, "Mặt nạ đất sét 100g");
    await other.getByRole("button", { name: "Từ chối" }).click();
    const dialog = page.getByRole("dialog", { name: "Từ chối thẻ này?" });
    await expect(dialog.getByRole("button", { name: "Từ chối thẻ" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "Lý do hoặc số liệu chưa thuyết phục" }).check();
    await dialog.getByRole("button", { name: "Từ chối thẻ" }).click();
    await expect(other.getByTestId("card-status")).toHaveText("Đã từ chối");
    expect(v1).toEqual([]);
  });

  test("cover image and Seller Center flows run locally", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions");

    const photo = card(page, "Sữa rửa mặt amino 150ml");
    await photo.getByRole("button", { name: "Phê duyệt" }).click();
    await photo.getByRole("link", { name: "Xem tiến độ ›" }).click();
    await expect(page.getByTestId("photo-request")).toContainText("Juli cần ảnh bìa mới từ bạn");
    await page.getByTestId("photo-input").setInputFiles({ name: "anh.png", mimeType: "image/png", buffer: Buffer.from([137, 80, 78, 71]) });
    await expect(page.getByTestId("consent-block")).toBeVisible();

    await page.getByRole("tab", { name: "Đề xuất" }).click();
    const manual = card(page, "Kem dưỡng ẩm ceramide");
    await manual.getByRole("button", { name: "Phê duyệt" }).click();
    await manual.getByRole("link", { name: "Xem tiến độ ›" }).click();
    const guide = page.getByTestId("seller-guide");
    await expect(guide).toContainText("Làm theo 4 bước trên Seller Center");
    const boxes = guide.getByRole("checkbox");
    for (let i = 0; i < 4; i += 1) await boxes.nth(i).check();
    await guide.getByRole("button", { name: "Tôi đã áp dụng" }).click();
    await expect(page.getByTestId("run-timeline")).toContainText("Tìm thấy: Giảm giá sản phẩm");

    expect(v1).toEqual([]);
  });

  test("Đo lường shows the sample's measured run", async ({ page }) => {
    const v1 = recordBackendRequests(page);
    await page.goto("/decisions?tab=do-luong");
    await expect(page.getByRole("tab", { name: "Ngày 7 · kiểm tra" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("measure-panel").first()).toContainText("Toner rau má 200ml");
    await expect(page.getByTestId("measure-target").first()).toContainText("9.613 – 10.207");
    expect(v1).toEqual([]);
  });
});

test.describe("Sign-in survives a new tab (P11)", () => {
  test("a session from an older build (sessionStorage) is kept and a second tab is still signed in", async ({ context, page }) => {
    await context.route(/\/v1\/demo\//, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data: [], error: null }) }),
    );
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
      sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
      sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
    });
    await page.goto("/decisions");
    await expect(page.getByTestId("mock-data-notice")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => localStorage.getItem("juli_demo_auth_session"))).not.toBeNull();

    const second = await context.newPage();
    const seen: string[] = [];
    second.on("request", (request) => {
      if (new URL(request.url()).pathname === "/v1/demo/decisions") seen.push(request.headers()["authorization"] ?? "");
    });
    await second.goto("/decisions");
    await expect.poll(() => seen).toContain("Bearer e2e-token");
    await expect(second.getByTestId("mock-data-notice")).toHaveCount(0);
  });
});
