import { expect, test } from "@playwright/test";

import { P_IDLE, P_ZIP } from "../../src/lib/shopee-decisions/__tests__/builder-fixtures";
import { stubBuilder } from "./p92-stub";

/**
 * P92 smoke (wave 2): Tự tạo phương án in a browser with the builder API stubbed by synthetic fixtures. The picker shows
 * every active listing, voucher 5k/100k and 10k/100k are compared side by side, and "Chọn" on a version that breaks
 * the floor opens the P91 warning and is sent again with acknowledge_breaches. Desktop and the 390 px phone.
 */

const noSideScroll = (page: import("@playwright/test").Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

test.describe("P92 builder", () => {
  test("the picker lists every active listing, including those without orders in 30 days, and fits the screen", async ({ page }) => {
    await stubBuilder(page);
    await page.goto("/decisions?tu-tao=1&from=quyet-dinh");
    await expect(page.getByTestId("p2-picker-count")).toContainText("12 sản phẩm đang bán");
    await expect(page.getByTestId(`p2-prod-${P_IDLE}`)).toContainText("không bán 30 ngày qua");
    await expect(page.getByRole("button", { name: "Thiếu giá vốn 2" })).toBeVisible();
    await expect(page.getByTestId("p2-excluded-note")).toContainText("Đã loại trừ 4 sản phẩm");
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("button", { name: /Xem thêm 3 sản phẩm/ }).click();
    await expect(page.getByTestId(/^p2-prod-/)).toHaveCount(12);
  });

  test("variation picker with the collapsed 'So sánh phân loại', then the 13 kinds", async ({ page }) => {
    await stubBuilder(page);
    await page.goto("/decisions?tu-tao=1&from=quyet-dinh");
    await page.getByTestId(`p2-prod-${P_ZIP}`).click();
    await expect(page.getByTestId("p2-vstep")).toBeVisible();
    await expect(page.getByTestId("p2-vcmp")).toHaveCount(0);
    await page.getByTestId("p2-vcmp-toggle").click();
    await expect(page.getByTestId("p2-vcmp-v10")).toContainText("chưa tính");
    expect(await noSideScroll(page)).toBe(true);
    await page.getByTestId("p2-vnext").click();
    await expect(page.locator("[data-testid^=p2-kind-]")).toHaveCount(13);
    expect(await noSideScroll(page)).toBe(true);
  });

  test("voucher 5k/100k vs 10k/100k side by side, Chọn on the floor breach asks, then sends acknowledge_breaches", async ({ page }) => {
    const posts = await stubBuilder(page, { breach2: true });
    await page.goto("/decisions?tu-tao=1&from=quyet-dinh");
    await page.getByTestId(`p2-prod-${P_ZIP}`).click();
    await page.getByTestId("p2-vnext").click();
    for (const value of ["5000", "10000"]) {
      await page.getByTestId("p2-kind-voucher").click();
      await page.getByRole("textbox", { name: "Giá trị" }).fill(value);
      await page.getByRole("textbox", { name: "Đơn tối thiểu" }).fill("100000");
      await expect(page.getByTestId("p2-dprofit")).toContainText("+54.000đ");
      await page.getByTestId("p2-add").click();
    }
    await page.getByTestId("p2-open-compare").click();
    await expect(page.getByTestId("p2-warn-2")).toContainText("Chạm giá sàn");
    expect(posts.list.filter((p) => p.path.endsWith("/builder/compare")).at(-1)?.body).toMatchObject({ versions: [{ kind: "voucher", value: 5000, min_spend: 100000 }, { kind: "voucher", value: 10000, min_spend: 100000 }] });
    expect(await noSideScroll(page)).toBe(true);
    await page.getByTestId("p2-choose-2").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Chọn P2 dù chạm giá sàn?");
    await dialog.getByRole("button", { name: "Quay lại" }).click();
    expect(posts.list.some((p) => p.path.endsWith("/builder/choose"))).toBe(false);
    await page.getByTestId("p2-choose-2").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Vẫn tiếp tục" }).click();
    await expect(page.getByTestId("p2-chosen")).toContainText("Đã chuyển P2 sang Quyết định · thẻ thủ công JC-2611-0021");
    await expect(page.getByTestId("p2-ack")).toContainText("Đã xác nhận vượt giá sàn");
    expect(posts.list.find((p) => p.path.endsWith("/builder/choose"))?.body).toMatchObject({ chosen: 1, acknowledge_breaches: true });
  });
});
