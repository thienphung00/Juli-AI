import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sampleEnvelope } from "../phan-tich/sample-data";
import { ShopReportProvider, useShopReport } from "../shop-report/shop-report-context";
import { ACTIVE_SHOP_STORAGE_KEY } from "../shop-session";
import { AUTH_SESSION_STORAGE_KEY } from "../supabase-auth";

let shopN = 0; // each test is its own shop: the platform answer is cached per shop id

function Status() {
  return <span data-testid="status">{useShopReport().state.status}</span>;
}

function stubPlatform(platform: unknown) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const body = String(input).endsWith("/v1/shops/me") ? { platform } : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

beforeEach(() => {
  shopN += 1;
  delete process.env.NEXT_PUBLIC_TIKTOK_ADR108_SCREENS;
  window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
  window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: `sw-${shopN}`, name: "Shop" }));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete process.env.NEXT_PUBLIC_TIKTOK_ADR108_SCREENS;
  window.sessionStorage.clear();
  window.localStorage.clear(); // the active shop is mirrored there
});

describe("W3 · the shell's report read for a TikTok shop", () => {
  it("does not read the ADR-108 report while the switch is off, and does not wait for it", async () => {
    stubPlatform("tiktok");
    const loadAnalysis = vi.fn().mockResolvedValue(sampleEnvelope());
    render(
      <ShopReportProvider loadAnalysis={loadAnalysis}>
        <Status />
      </ShopReportProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty"));
    expect(loadAnalysis).not.toHaveBeenCalled();
  });

  it("reads it behind the switch", async () => {
    process.env.NEXT_PUBLIC_TIKTOK_ADR108_SCREENS = "1";
    stubPlatform("tiktok");
    const loadAnalysis = vi.fn().mockResolvedValue(sampleEnvelope());
    render(
      <ShopReportProvider loadAnalysis={loadAnalysis}>
        <Status />
      </ShopReportProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(loadAnalysis).toHaveBeenCalledTimes(1);
  });

  it("an unknown platform is an error to retry, never a TikTok read", async () => {
    process.env.NEXT_PUBLIC_TIKTOK_ADR108_SCREENS = "1";
    stubPlatform(undefined);
    const loadAnalysis = vi.fn().mockResolvedValue(sampleEnvelope());
    render(
      <ShopReportProvider loadAnalysis={loadAnalysis}>
        <Status />
      </ShopReportProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("error"));
    expect(loadAnalysis).not.toHaveBeenCalled();
  });
});
