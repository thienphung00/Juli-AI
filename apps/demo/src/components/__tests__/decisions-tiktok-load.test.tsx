import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PLATFORM_ATTEMPTS, PLATFORM_BACKOFF_MS, PLATFORM_READ_TIMEOUT_MS } from "../../lib/shopee-analytics/platform";
import { ShopReportProvider } from "../../lib/shop-report/shop-report-context";
import { ACTIVE_SHOP_STORAGE_KEY } from "../../lib/shop-session";
import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { DecisionsPageClient } from "../decisions-page-client";

/** W3 U-3: Quyết định of a TikTok shop must leave "Đang tải đề xuất…" (it sat there). */
vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
  window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "tt-shop-1", name: "Shop TikTok" }));
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
  window.localStorage.clear(); // the active shop is mirrored there
});

describe("Quyết định · a TikTok shop", () => {
  it("leaves the loading line once /v1/shops/me says tiktok", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/shops/me")) return json({ platform: "tiktok" });
      return json([]);
    });
    render(
      <ShopReportProvider loadAnalysis={vi.fn().mockResolvedValue(null)}>
        <DecisionsPageClient />
      </ShopReportProvider>,
    );
    await waitFor(() => expect(screen.queryByText("Đang tải đề xuất…")).toBeNull(), { timeout: 3000 });
  });

  it("a stalled shops/me does not render TikTok screens: neutral loading, then an error with a retry (the cause of the stuck line)", async () => {
    vi.useFakeTimers();
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "tt-shop-stalled", name: "Shop TikTok" }));
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => undefined));
    render(
      <ShopReportProvider loadAnalysis={vi.fn().mockResolvedValue(null)}>
        <DecisionsPageClient />
      </ShopReportProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(screen.getByText("Đang tải đề xuất…")).toBeInTheDocument();
    const total = PLATFORM_ATTEMPTS * PLATFORM_READ_TIMEOUT_MS + PLATFORM_BACKOFF_MS.reduce((a, b) => a + b, 0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(total + 100);
    });
    // Ended: not the endless loading line, and no TikTok / Shopee decision screen either.
    expect(screen.queryByText("Đang tải đề xuất…")).toBeNull();
    expect(screen.getByTestId("platform-error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
    expect(fetchSpy.mock.calls.every(([url]) => String(url).endsWith("/v1/shops/me"))).toBe(true);
    vi.useRealTimers();
  });
});
