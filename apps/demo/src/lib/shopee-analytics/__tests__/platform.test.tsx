import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopReportState } from "../../shop-report/shop-report-context";
import {
  PLATFORM_ATTEMPTS,
  PLATFORM_BACKOFF_MS,
  PLATFORM_READ_TIMEOUT_MS,
  probeShopPlatform,
  resetShopPlatformCache,
  useShopPlatformState,
} from "../platform";

function respond(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
}
const calls = (f: typeof fetch) => (f as unknown as ReturnType<typeof vi.fn>).mock.calls as [string, RequestInit][];

beforeEach(() => resetShopPlatformCache());
afterEach(() => vi.useRealTimers());

describe("which marketplace the acting shop is on (only /v1/shops/me says)", () => {
  it("shops/me carrying a platform decides, with exactly one read", async () => {
    const f = respond(200, { platform: "shopee" });
    expect(await probeShopPlatform("t", "s0", f)).toBe("shopee");
    expect(calls(f)).toHaveLength(1);
    expect(calls(f)[0]![0]).toBe("/v1/shops/me");
    expect(calls(f)[0]![1].headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s0" });
    expect(await probeShopPlatform("t", "s0b", respond(200, { platform: "tiktok" }))).toBe("tiktok");
  });

  it("never probes a Shopee read route: those answer TikTok shops too", async () => {
    const f = respond(200, { id: "s1" });
    expect(await probeShopPlatform("t", "s1", f)).toBeNull();
    expect(await probeShopPlatform("t", "s1", respond(409, { detail: { code: "no_shopee_data" } }))).toBeNull();
    expect(calls(f).map(([url]) => url)).toEqual(["/v1/shops/me"]);
  });

  it("an unclear answer is unknown, not remembered and not TikTok", async () => {
    expect(await probeShopPlatform("t", "s4", respond(500, {}))).toBeNull();
    expect(await probeShopPlatform("t", "s4", respond(200, { platform: "other" }))).toBeNull();
    expect(await probeShopPlatform("t", "s4", respond(200, { platform: "shopee" }))).toBe("shopee");
  });

  it("remembers the answer per shop", async () => {
    const f = respond(200, { platform: "shopee" });
    await probeShopPlatform("t", "s5", f);
    await probeShopPlatform("t", "s5", f);
    expect(calls(f)).toHaveLength(1);
  });

  it("a stalled read ends as unknown after the timeout", async () => {
    vi.useFakeTimers();
    const stalled = vi.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch;
    const pending = probeShopPlatform("t", "s6", stalled);
    await vi.advanceTimersByTimeAsync(PLATFORM_READ_TIMEOUT_MS + 1);
    expect(await pending).toBeNull();
  });
});

describe("the platform phase the screens wait on", () => {
  const loading = (id: string): ShopReportState => ({ status: "loading", token: "t", shop: { id, name: "Shop" } });
  function Phase({ state, f }: { state: ShopReportState; f: typeof fetch }) {
    const s = useShopPlatformState(state, f);
    return (
      <>
        <span data-testid="p">{`${s.phase}:${String(s.platform)}`}</span>
        <button onClick={s.retry} type="button">
          retry
        </button>
      </>
    );
  }

  it("TikTok resolves from shops/me", async () => {
    render(<Phase f={respond(200, { platform: "tiktok" })} state={loading("t1")} />);
    expect(screen.getByTestId("p")).toHaveTextContent("loading:null");
    await waitFor(() => expect(screen.getByTestId("p")).toHaveTextContent("ready:tiktok"));
  });

  it("Shopee resolves from shops/me", async () => {
    render(<Phase f={respond(200, { platform: "shopee" })} state={loading("t2")} />);
    await waitFor(() => expect(screen.getByTestId("p")).toHaveTextContent("ready:shopee"));
  });

  it("a stalled shops/me never renders TikTok: loading, bounded retries, then an error with a retry", async () => {
    vi.useFakeTimers();
    const stalled = vi.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch;
    render(<Phase f={stalled} state={loading("t3")} />);
    expect(screen.getByTestId("p")).toHaveTextContent("loading:null");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PLATFORM_READ_TIMEOUT_MS + 1);
    });
    expect(screen.getByTestId("p")).toHaveTextContent("loading:null"); // retrying, still neutral
    const total = PLATFORM_ATTEMPTS * PLATFORM_READ_TIMEOUT_MS + PLATFORM_BACKOFF_MS.reduce((a, b) => a + b, 0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(total);
    });
    expect(screen.getByTestId("p")).toHaveTextContent("error:null");
    expect(calls(stalled)).toHaveLength(PLATFORM_ATTEMPTS);
    // The retry button asks again from the start.
    await act(async () => {
      screen.getByRole("button", { name: "retry" }).click();
    });
    expect(screen.getByTestId("p")).toHaveTextContent("loading:null");
    expect(calls(stalled)).toHaveLength(PLATFORM_ATTEMPTS + 1);
  });

  it("a failing shops/me that recovers on a retry resolves", async () => {
    vi.useFakeTimers();
    const f = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValue(new Response(JSON.stringify({ platform: "shopee" }), { status: 200 })) as unknown as typeof fetch;
    render(<Phase f={f} state={loading("t4")} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PLATFORM_BACKOFF_MS[0]! + 10);
    });
    expect(screen.getByTestId("p")).toHaveTextContent("ready:shopee");
  });

  it("anonymous visitors and sessions without a shop never read it", () => {
    const f = respond(200, {});
    render(<Phase f={f} state={{ status: "anonymous", envelope: null }} />);
    expect(f).not.toHaveBeenCalled();
    expect(screen.getByTestId("p")).toHaveTextContent("none:tiktok");
  });

  it("is loading while the shell resolves who the shop is", () => {
    render(<Phase f={respond(200, {})} state={{ status: "resolving" }} />);
    expect(screen.getByTestId("p")).toHaveTextContent("loading:null");
  });
});
