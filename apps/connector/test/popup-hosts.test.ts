// @vitest-environment jsdom
// The second pairing button: the optional host is asked for from the person's click, first thing.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ungrantedHosts, wireHostButton } from "../src/core/popup/shell";

const HOSTS = ["https://seller-vn.tiktok.com/*"];

function mockChrome(contains: boolean) {
  const order: string[] = [];
  const request = vi.fn(async () => (order.push("request"), true));
  const containsFn = vi.fn(async () => contains);
  (globalThis as Record<string, unknown>).chrome = { permissions: { request, contains: containsFn } };
  return { request, contains: containsFn, order };
}

beforeEach(() => {
  document.body.innerHTML = '<button id="b" type="button" hidden>Cho phép truy cập TikTok Seller Center</button>';
});
afterEach(() => {
  delete (globalThis as Record<string, unknown>).chrome;
});

describe("optional hosts", () => {
  it("reports the hosts that are not granted yet, and none when they are", async () => {
    mockChrome(false);
    expect(await ungrantedHosts(HOSTS)).toEqual(HOSTS);
    mockChrome(true);
    expect(await ungrantedHosts(HOSTS)).toEqual([]);
  });

  it("asks for nothing and shows no button when a pack has no optional host (Shopee pairing)", async () => {
    const c = mockChrome(false);
    expect(await ungrantedHosts([])).toEqual([]);
    expect(await ungrantedHosts(undefined)).toEqual([]);
    expect(c.contains).not.toHaveBeenCalled();
    const button = document.getElementById("b") as HTMLButtonElement;
    wireHostButton(button, [], () => undefined);
    expect(button.hidden).toBe(true);
    button.click();
    expect(c.request).not.toHaveBeenCalled();
  });

  it("shows the button and calls permissions.request synchronously in the click handler", async () => {
    const c = mockChrome(false);
    const after = vi.fn();
    const button = document.getElementById("b") as HTMLButtonElement;
    wireHostButton(button, HOSTS, after);
    expect(button.hidden).toBe(false);
    expect(c.request).not.toHaveBeenCalled(); // nothing is asked before a click
    button.click();
    expect(c.request).toHaveBeenCalledTimes(1); // same tick as the click: the gesture is intact
    expect(c.request).toHaveBeenCalledWith({ origins: HOSTS });
    await vi.waitFor(() => expect(after).toHaveBeenCalled());
  });
});
