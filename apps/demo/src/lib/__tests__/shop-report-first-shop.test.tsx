import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShopHeader } from "../../components/app-shell/shop-header";
import { DemoStateProvider } from "../../components/demo-state";
import { CONNECT_SHOP_HREF } from "../app-navigation";
import { ShopReportProvider, useShopReport } from "../shop-report/shop-report-context";
import { ACTIVE_SHOP_STORAGE_KEY, readActiveShop } from "../shop-session";
import type { Shop } from "../shops-client";
import { seedShopPlatform } from "../shopee-analytics/__tests__/platform-test-helpers";
import { AUTH_SESSION_STORAGE_KEY } from "../supabase-auth";

/** Owner #104: signed in with no saved shop → the first shop GET /v1/shops returns, never the no-shop chrome. */

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

await seedShopPlatform("first-shopee", "shopee");
await seedShopPlatform("saved-tiktok", "tiktok");

const shop = (id: string, name: string): Shop => ({ id, shop_name: name, tiktok_shop_id: null, is_active: true });

function Status() {
  const { state } = useShopReport();
  return <p data-testid="status">{state.status}{"shop" in state ? ` ${state.shop.id}` : ""}</p>;
}

function Header() {
  const { state } = useShopReport();
  return <ShopHeader googleHref={null} onRefreshDemo={() => undefined} onSignOut={() => undefined} state={state} />;
}

function renderShell(loadShops: (token: string) => Promise<Shop[]>, page: React.ReactNode = <Status />) {
  render(
    <DemoStateProvider>
      <ShopReportProvider loadAnalysis={vi.fn()} loadShops={loadShops}>{page}</ShopReportProvider>
    </DemoStateProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
});

describe("no saved shop (owner #104)", () => {
  it("acts as the first shop the account has, and saves it", async () => {
    const loadShops = vi.fn().mockResolvedValue([shop("first-shopee", "Shop A"), shop("second", "Shop B")]);
    renderShell(loadShops);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty first-shopee"));
    expect(loadShops).toHaveBeenCalledWith("token-1");
    expect(readActiveShop()).toEqual({ id: "first-shopee", name: "Shop A" });
  });

  it("an account with no shop keeps the sample", async () => {
    renderShell(vi.fn().mockResolvedValue([]));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("no-shop"));
    expect(readActiveShop()).toBeNull();
  });

  it("a failed shop list keeps the sample", async () => {
    renderShell(vi.fn().mockRejectedValue(new Error("offline")));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("no-shop"));
  });

  it("a saved shop is used as it is, without the list", async () => {
    window.localStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "saved-tiktok", name: "Shop C" }));
    const loadShops = vi.fn();
    renderShell(loadShops);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty saved-tiktok"));
    expect(loadShops).not.toHaveBeenCalled();
  });
});

describe("shop menu (owner #104)", () => {
  it("no shop: 'Kết nối shop'", async () => {
    renderShell(vi.fn().mockResolvedValue([]), <Header />);
    const header = await screen.findByTestId("shop-header");
    expect(await within(header).findByRole("link", { name: "Kết nối shop", hidden: true })).toHaveAttribute("href", CONNECT_SHOP_HREF);
    expect(header).not.toHaveTextContent("Kết nối TikTok Shop");
  });

  it("with a shop: 'Đổi shop'", async () => {
    renderShell(vi.fn().mockResolvedValue([shop("first-shopee", "Shop A")]), <Header />);
    const header = await screen.findByTestId("shop-header");
    expect(await within(header).findByRole("link", { name: "Đổi shop", hidden: true })).toHaveAttribute("href", CONNECT_SHOP_HREF);
    expect(header).not.toHaveTextContent("Kết nối TikTok Shop");
  });
});
