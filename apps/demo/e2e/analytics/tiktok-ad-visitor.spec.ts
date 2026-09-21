import { expect, test, type Page } from "@playwright/test";

/**
 * The Demo loads the TikTok pixel only for a visitor who arrived from a TikTok
 * ad (owner decision, 2026-09-21). `exit-gate/locale-and-assistance.spec.ts`
 * owns the other half — that an organic visitor's session issues no external
 * request at all.
 *
 * This spec owns the half absence-testing cannot cover: that the pixel really
 * does load, and really does run, for the visitor it is meant for. A suite
 * that only asserts "no pixel here" stays green when the pixel is dead
 * everywhere.
 */
const TIKTOK_HOSTS = /tiktok/;

/**
 * Record what the page tried to send TikTok, and send none of it. Asserting on
 * the request rather than the `<script>` element is what actually pins the
 * data source id: the id only reaches TikTok through the `sdkid` parameter the
 * vendor loader builds, so a snippet that shipped the wrong one would still
 * look right in the DOM.
 */
async function captureTikTokRequests(page: Page): Promise<string[]> {
  const requests: string[] = [];

  await page.route(
    (url) => TIKTOK_HOSTS.test(url.hostname),
    (route, request) => {
      requests.push(request.url());
      return route.abort();
    },
  );

  return requests;
}

test.describe("TikTok pixel on the Demo", () => {
  test("a visitor arriving from an ad loads the pixel for the one data source", async ({
    page,
  }) => {
    const requests = await captureTikTokRequests(page);

    await page.goto("/?ttclid=e2e-click-id");

    await expect
      .poll(() => requests.find((url) => url.includes("/pixel/events.js")))
      .toContain("sdkid=DAO9C6JC77U88MSNU74G");

    // It ran, too: `ttq` is the queue the base code installs synchronously. A
    // snippet that parsed but threw would leave the tag in the DOM regardless.
    expect(
      await page.evaluate(() => typeof (window as { ttq?: unknown }).ttq),
    ).not.toBe("undefined");
  });

  test("the click id outlives the landing page, so a later conversion is still attributed", async ({
    page,
  }) => {
    const requests = await captureTikTokRequests(page);

    await page.goto("/?ttclid=e2e-click-id");
    await expect.poll(() => requests.length).toBeGreaterThan(0);

    requests.length = 0;
    // A later page with no `ttclid` of its own: the stored id has to carry it.
    await page.goto("/decisions");

    await expect.poll(() => requests.length).toBeGreaterThan(0);
    expect(
      await page.evaluate(() =>
        window.localStorage.getItem("juli_tiktok_click_id"),
      ),
    ).toBe("e2e-click-id");
  });

  test("an organic visitor on the same page loads nothing", async ({ page }) => {
    const requests = await captureTikTokRequests(page);

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Dùng thử Demo" })).toBeVisible();

    expect(requests).toEqual([]);
    expect(
      await page.evaluate(() => typeof (window as { ttq?: unknown }).ttq),
    ).toBe("undefined");
  });
});
