import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseBusinesses } from "../../lib/businesses-client";
import { readActiveBusiness, storeActiveBusiness } from "../../lib/shop-session";
import { startTikTokConnect } from "../../lib/tiktok-connect-client";
import { BusinessSwitcher } from "../app-shell/business-switcher";

/** P101 W1: the header switcher, Doanh nghiệp ▾ → Shop ▾, from `GET /v1/businesses`. */

const BUSINESS_A = "11111111-1111-4111-8111-111111111111";
const BUSINESS_B = "22222222-2222-4222-8222-222222222222";
const PAYLOAD = {
  data: [
    {
      id: BUSINESS_A,
      name: "Ory",
      role: "owner",
      shops: [
        { id: "shop-1", name: "Ory Shopee", platform: "shopee", kind: "real" },
        { id: "shop-2", name: "Ory TikTok", platform: "tiktok", kind: "real" },
      ],
    },
    { id: BUSINESS_B, name: "Fujiwa", role: "member", shops: [{ id: "shop-3", name: "Fujiwa", platform: "tiktok", kind: "real" }] },
  ],
};

function fetchOf(payload: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(payload), { status })) as unknown as typeof fetch;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

describe("BusinessSwitcher", () => {
  it("shows the active shop's business and shop, and switches shop within it", async () => {
    const onSwitch = vi.fn();
    render(<BusinessSwitcher activeShopId="shop-1" fetchImpl={fetchOf(PAYLOAD)} onSwitch={onSwitch} token="t" />);
    const business = await screen.findByRole("button", { name: "Doanh nghiệp: Ory" });
    expect(business).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Shop: Ory Shopee" }));
    expect(screen.getAllByRole("img", { name: "TikTok Shop" }).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /Ory TikTok/ }));
    expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({ id: "shop-2" }), expect.objectContaining({ id: BUSINESS_A }));
  });

  it("switching business opens its first shop", async () => {
    const onSwitch = vi.fn();
    render(<BusinessSwitcher activeShopId="shop-1" fetchImpl={fetchOf(PAYLOAD)} onSwitch={onSwitch} token="t" />);
    await userEvent.click(await screen.findByRole("button", { name: "Doanh nghiệp: Ory" }));
    await userEvent.click(screen.getByRole("button", { name: "Fujiwa" }));
    expect(onSwitch).toHaveBeenCalledWith(expect.objectContaining({ id: "shop-3" }), expect.objectContaining({ id: BUSINESS_B }));
  });

  it("renders nothing with a single shop or a refused call", async () => {
    const single = { data: [{ id: BUSINESS_A, name: "Ory", role: "owner", shops: [{ id: "shop-1", name: "Ory", platform: "shopee", kind: "real" }] }] };
    const fetchSingle = fetchOf(single);
    const { container, unmount } = render(<BusinessSwitcher activeShopId="shop-1" fetchImpl={fetchSingle} token="t" />);
    await waitFor(() => expect(fetchSingle).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=business-switcher]")).toBeNull();
    unmount();
    const refused = fetchOf({ detail: "read_only" }, 403);
    const second = render(<BusinessSwitcher activeShopId="shop-1" fetchImpl={refused} token="t" />);
    await waitFor(() => expect(refused).toHaveBeenCalled());
    expect(second.container.querySelector("[data-testid=business-switcher]")).toBeNull();
  });
});

describe("businesses client and connect", () => {
  it("parses platform, kind and a shop with no business", () => {
    const parsed = parseBusinesses({ data: [{ id: null, name: "Legacy", role: "owner", shops: [{ id: "s", name: "Legacy", platform: "x", kind: "?" }] }] });
    expect(parsed).toEqual([{ id: null, name: "Legacy", role: "owner", shops: [{ id: "s", name: "Legacy", platform: "tiktok", kind: "real" }] }]);
  });

  it("the TikTok connect sends the selected business", async () => {
    storeActiveBusiness(BUSINESS_A);
    expect(readActiveBusiness()).toBe(BUSINESS_A);
    const fetchImpl = fetchOf({ authorize_url: "https://auth.example/x", state_expires_in: 600 });
    await startTikTokConnect("t", fetchImpl);
    const url = (fetchImpl as unknown as { mock: { calls: [string][] } }).mock.calls[0][0];
    expect(url).toContain(`business_id=${BUSINESS_A}`);
    storeActiveBusiness(null);
    await startTikTokConnect("t", fetchImpl);
    const plain = (fetchImpl as unknown as { mock: { calls: [string][] } }).mock.calls[1][0];
    expect(plain).not.toContain("business_id");
  });
});
