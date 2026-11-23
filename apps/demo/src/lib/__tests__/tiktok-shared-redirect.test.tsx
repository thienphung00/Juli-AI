import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopReportState } from "../shop-report/shop-report-context";
import { tiktokLegacyScreens } from "../tiktok-screens";
import { useTiktokSharedRedirect } from "../use-tiktok-shared-redirect";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

function platformFetch(platform: "tiktok" | "shopee"): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify({ platform }), { status: 200 })) as unknown as typeof fetch;
}

function Probe({ state }: { state: ShopReportState }) {
  return <span data-testid="leaving">{String(useTiktokSharedRedirect(state, "/tong-quan"))}</span>;
}

const shop = (id: string): ShopReportState => ({ status: "loading", token: "t", shop: { id, name: "Shop" } });

beforeEach(() => {
  replace.mockReset();
  window.history.replaceState(null, "", "/");
});

describe("W3 U-4 · the one switch for a TikTok shop's ADR-108 screens", () => {
  it("is off by default and on only by ?adr108=1 (no build-wide env switch)", () => {
    expect(tiktokLegacyScreens()).toBe(false);
    expect(tiktokLegacyScreens(null)).toBe(false);
    expect(tiktokLegacyScreens(new URLSearchParams(""))).toBe(false);
    expect(tiktokLegacyScreens(new URLSearchParams("adr108=1"))).toBe(true);
    expect(tiktokLegacyScreens(new URLSearchParams("adr108=0"))).toBe(false);
  });

  it("without the switch, a TikTok shop is sent to the shared screen", async () => {
    const f = platformFetch("tiktok");
    const original = globalThis.fetch;
    globalThis.fetch = f;
    try {
      render(<Probe state={shop("u1")} />);
      await waitFor(() => expect(replace).toHaveBeenCalledWith("/tong-quan"));
      expect(screen.getByTestId("leaving")).toHaveTextContent("true");
    } finally {
      globalThis.fetch = original;
    }
  });

  it("with ?adr108=1 the old screen stays and nothing redirects", async () => {
    window.history.replaceState(null, "", "/?adr108=1");
    const original = globalThis.fetch;
    globalThis.fetch = platformFetch("tiktok");
    try {
      render(<Probe state={shop("u2")} />);
      await waitFor(() => expect(screen.getByTestId("leaving")).toHaveTextContent("false"));
      expect(replace).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = original;
    }
  });

  it("a Shopee shop and a visitor without a shop are never redirected", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = platformFetch("shopee");
    try {
      render(<Probe state={shop("u3")} />);
      await waitFor(() => expect(screen.getByTestId("leaving")).toHaveTextContent("false"));
      render(<Probe state={{ status: "anonymous", envelope: null }} />);
      expect(replace).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = original;
    }
  });
});
