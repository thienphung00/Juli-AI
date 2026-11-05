import { expect, test, type Page } from "@playwright/test";

import { ADS, BOARD, FLOWS, ORDERS, PRODUCTS, PROMOS } from "../../src/components/ops/__tests__/p92-dashboard-fixtures";
import { overview } from "../../src/lib/shopee-analytics/__tests__/fixtures";

/**
 * P92 (web, wave 2): Cài đặt › Loại trừ sản phẩm (add with a reason, Hoàn tác, the Tổng quan line) and
 * the four read-only Ops pages in the seller's Demo (Từ khóa, Quảng cáo, Đơn hàng, Sản phẩm + luồng),
 * in a browser with the API stubbed by synthetic data. Desktop and a 390px phone.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };
const REASONS = [
  { key: "ngung_ban", label: "Ngừng bán" },
  { key: "qua_tang", label: "Quà tặng" },
  { key: "phan_phoi", label: "Hàng phân phối" },
  { key: "khac", label: "Khác" },
];

interface Row {
  item_id: string;
  name: string;
  reason: string;
  reason_label: string;
  set_at: string;
}

async function stub(page: Page, initial: Row[] = []) {
  let excluded = [...initial];
  const requests: { method: string; path: string; headers: Record<string, string>; body: unknown }[] = [];
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    requests.push({ method: req.method(), path, headers: req.headers(), body: req.method() === "PUT" ? req.postDataJSON() : null });
    if (path === "/v1/shops/me") return json({ id: SHOP.id, platform: "shopee" });
    if (path === "/v1/demo/shopee/overview") {
      const base = overview();
      const total = excluded.length > 0 ? 1_950_000 : 0;
      return json({ ...base, gmv: { ...base.gmv, excluded_gmv: total } });
    }
    if (path === "/v1/demo/shopee/builder/products") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const all = [
        { item_id: "22150948835", name: "Hộp quà mẫu thử Z" },
        { item_id: "17820466113", name: "Bình giữ nhiệt inox X" },
      ].filter((p) => p.name.toLowerCase().includes(q) && !excluded.some((e) => e.item_id === p.item_id));
      return json({
        platform: "shopee",
        window: { from: "2026-07-10", to: "2026-10-07", days: 90 },
        sort: "gmv_90d",
        count: all.length,
        offset: 0,
        limit: 8,
        excluded_hidden: excluded.length,
        missing_cost_count: 0,
        products: all.map((p) => ({ ...p, orders_30d: 3, orders_90d: 9, gmv_30d: 60_000, gmv_90d: 190_000, price: 20_000, stock: 5, variation_count: 0, has_cost: true, missing_cost_chip: null, excluded: false, exclude_reason: null })),
      });
    }
    if (path === "/v1/demo/shopee/exclusions" && req.method() === "GET") return json({ excluded, count: excluded.length, reasons: REASONS });
    const item = /^\/v1\/demo\/shopee\/exclusions\/([^/]+)$/.exec(path);
    if (item && req.method() === "PUT") {
      const reason = (req.postDataJSON() as { reason: string }).reason;
      const row: Row = {
        item_id: decodeURIComponent(item[1]!),
        name: item[1] === "22150948835" ? "Hộp quà mẫu thử Z" : "Bình giữ nhiệt inox X",
        reason,
        reason_label: REASONS.find((r) => r.key === reason)!.label,
        set_at: "2026-11-05T09:02:00+07:00",
      };
      excluded = [...excluded.filter((e) => e.item_id !== row.item_id), row];
      return json(row);
    }
    if (item && req.method() === "DELETE") {
      excluded = excluded.filter((e) => e.item_id !== decodeURIComponent(item[1]!));
      return route.fulfill({ status: 204 });
    }
    if (path === "/v1/demo/shopee/keywords") return json(BOARD);
    if (path === "/v1/demo/shopee/dashboard/products") return json(PRODUCTS);
    if (path === "/v1/demo/shopee/dashboard/flows") return json(FLOWS);
    if (path === "/v1/demo/shopee/dashboard/ads") return json(ADS);
    if (path === "/v1/demo/shopee/dashboard/promotions") return json(PROMOS);
    if (path === "/v1/demo/shopee/orders") return json(ORDERS);
    return json({ detail: "none" }, 404);
  });
  return requests;
}

const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

test.describe("seller: Cài đặt › Loại trừ sản phẩm", () => {
  test("add with a reason, see the Tổng quan line, then Hoàn tác", async ({ page }) => {
    const requests = await stub(page);
    await page.goto("/settings?tab=loai-tru-san-pham");
    await expect(page.getByTestId("sx-empty")).toContainText("Chưa loại trừ sản phẩm nào");
    await expect(page.getByTestId("sx-totals-note")).toContainText("Tổng vẫn gồm đơn của các sản phẩm này.");

    const add = page.getByTestId("sx-add");
    await add.getByRole("searchbox").fill("Hộp quà");
    await add.getByRole("button", { name: /Hộp quà mẫu thử Z/ }).click();
    await add.getByLabel("Lý do").selectOption("khac");
    await add.getByRole("button", { name: "Loại trừ" }).click();
    await expect(page.getByTestId("sx-notice-added")).toContainText("Đã loại trừ Hộp quà mẫu thử Z (khác).");
    await expect(page.getByTestId("sx-row-22150948835")).toBeVisible();
    await expect(page.getByTestId("sx-preview-excluded")).toContainText("trong đó 1.950.000đ từ sản phẩm đã loại trừ");
    const put = requests.find((r) => r.method === "PUT")!;
    expect(put.path).toBe("/v1/demo/shopee/exclusions/22150948835");
    expect(put.body).toMatchObject({ reason: "khac" });
    expect(put.headers["x-shop-id"]).toBe(SHOP.id);

    await page.getByTestId("sx-row-22150948835").getByRole("button", { name: "Hoàn tác" }).click();
    await expect(page.getByTestId("sx-notice-undone")).toContainText("Đã hoàn tác.");
    await expect(page.getByTestId("sx-empty")).toBeVisible();
    expect(requests.some((r) => r.method === "DELETE" && r.path === "/v1/demo/shopee/exclusions/22150948835")).toBe(true);
  });

  test("Tổng quan shows the excluded line and it opens the list", async ({ page }) => {
    await stub(page, [{ item_id: "17820466113", name: "Bình giữ nhiệt inox X", reason: "ngung_ban", reason_label: "Ngừng bán", set_at: "2026-10-28T10:15:00+07:00" }]);
    await page.goto("/tong-quan");
    const line = page.getByTestId("sa-excluded-gmv");
    await expect(line).toContainText("trong đó 1.950.000đ từ sản phẩm đã loại trừ");
    await page.getByTestId("sa-excluded-gmv-link").click();
    await expect(page).toHaveURL(/\/settings\?tab=loai-tru-san-pham/);
    await expect(page.getByTestId("sx-row-17820466113")).toBeVisible();
  });
});

test.describe("seller: the four pages from Ops", () => {
  const pages: [string, string, string][] = [
    ["/tu-khoa", "dashboard-tu-khoa", "nước rửa chén"],
    ["/quang-cao", "dashboard-quang-cao", "Chương trình thử"],
    ["/don-hang", "dashboard-don-hang", "0000000000a1"],
    ["/luong-san-pham", "dashboard-luong-san-pham", "Trang shop"],
  ];
  for (const [route, testId, text] of pages) {
    test(`${route} renders read-only through the demo routes`, async ({ page }) => {
      const requests = await stub(page);
      await page.goto(route);
      await expect(page.getByTestId(testId)).toContainText(text);
      const reads = requests.filter((r) => r.path.startsWith("/v1/demo/shopee/") && r.path !== "/v1/demo/shopee/overview");
      expect(reads.length).toBeGreaterThan(0);
      expect(reads.every((r) => r.method === "GET" && r.headers["x-shop-id"] === SHOP.id)).toBe(true);
      await expect(page.getByRole("button", { name: /Tạo từ khóa|Tải lên/ })).toHaveCount(0);
    });
  }

  test("the navigation lists them for a Shopee shop", async ({ page }) => {
    await stub(page);
    await page.goto("/tong-quan");
    const nav = page.getByRole("navigation", { name: "Điều hướng chính" });
    for (const name of ["Từ khóa", "Quảng cáo", "Đơn hàng", "Luồng"]) await expect(nav.getByRole("link", { name })).toBeVisible();
  });
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Loại trừ sản phẩm has no horizontal page scroll", async ({ page }) => {
    await stub(page, [{ item_id: "17820466113", name: "Bình giữ nhiệt inox X với một cái tên khá dài để thử xuống dòng", reason: "ngung_ban", reason_label: "Ngừng bán", set_at: "2026-10-28T10:15:00+07:00" }]);
    await page.goto("/settings?tab=loai-tru-san-pham");
    await expect(page.getByTestId("sx-row-17820466113")).toBeVisible();
    expect(await noHorizontalScroll(page)).toBe(true);
  });

  for (const [route, testId] of [
    ["/tu-khoa", "dashboard-tu-khoa"],
    ["/quang-cao", "dashboard-quang-cao"],
    ["/don-hang", "dashboard-don-hang"],
    ["/luong-san-pham", "dashboard-luong-san-pham"],
  ] as const) {
    test(`${route} has no horizontal page scroll`, async ({ page }) => {
      await stub(page);
      await page.goto(route);
      await expect(page.getByTestId(testId)).toBeVisible();
      await expect(page.getByTestId(testId).locator("table").first()).toBeVisible();
      expect(await noHorizontalScroll(page)).toBe(true);
    });
  }
});
