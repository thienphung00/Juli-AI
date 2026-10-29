import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchReviewerMe } from "../../lib/reviewer/api-client";
import { REVIEWER_SANDBOX_SHOP_LABEL, reviewerShopLabel } from "../../lib/reviewer/copy";
import { ReviewerProvider } from "../../lib/reviewer/reviewer-context";
import { readReviewerRecord, storeReviewerRecord, type ReviewerShopOption } from "../../lib/reviewer/session";
import { readActiveShop, storeActiveShop } from "../../lib/shop-session";
import { storeAuthSession } from "../../lib/supabase-auth";
import { ShopHeader } from "../app-shell/shop-header";

/**
 * P74-A (D77): the reviewer holds two pinned shops — the masked production shop
 * (default, read-only, simulated) and Juli's sandbox shop (real writes). The
 * shop menu switches between them; "me" follows the active shop and falls back
 * to the FIRST pin, never the newest.
 */

const MASKED: ReviewerShopOption = { id: "alias-1", name: "Shop TikTok (ẩn danh)", mode: "masked", writesEnabled: false };
const SANDBOX: ReviewerShopOption = { id: "sbx-1", name: "SANDBOX_VN", mode: "sandbox", writesEnabled: true };
const REVIEWER = { platform: "shopee", expiresAt: "2026-11-13T00:00:00Z" };

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

function me(shop: ReviewerShopOption) {
  return {
    status: "reviewer" as const,
    me: {
      reviewer: true as const,
      platform: "shopee",
      expiresAt: REVIEWER.expiresAt,
      shop: { id: shop.id, name: shop.name },
      mode: shop.mode,
      ...(shop.writesEnabled ? { writesEnabled: true } : {}),
      shops: [MASKED, SANDBOX],
    },
  };
}

describe("P74-A reviewer with two pinned shops", () => {
  it("fetchReviewerMe sends the active shop and parses the shop list", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          reviewer: true,
          platform: "shopee",
          expires_at: REVIEWER.expiresAt,
          shop: { id: "alias-1", name: "Shop TikTok (ẩn danh)" },
          mode: "masked",
          writes_enabled: false,
          shops: [
            { id: "alias-1", name: "Shop TikTok (ẩn danh)", mode: "masked", writes_enabled: false },
            { id: "sbx-1", name: "SANDBOX_VN", mode: "sandbox", writes_enabled: true },
            { id: "", mode: "masked" },
          ],
        }),
        { status: 200 },
      ),
    );
    const result = await fetchReviewerMe("at", fetchImpl, "sbx-1");
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)["X-Shop-Id"]).toBe("sbx-1");
    expect(result.status === "reviewer" && result.me.shops).toEqual([MASKED, SANDBOX]);
  });

  it("the menu offers the other pinned shop, labelled by its mode", async () => {
    const onSwitchShop = vi.fn();
    const state = { status: "ready", token: "t", shop: { id: "alias-1", name: MASKED.name }, envelope: { report: { shop_name: MASKED.name }, built_at: null } };
    render(
      <ShopHeader
        googleHref="x"
        onRefreshDemo={vi.fn()}
        onSignOut={vi.fn()}
        onSwitchShop={onSwitchShop}
        reviewer
        reviewerShops={[MASKED, SANDBOX]}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        state={state as any}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Menu shop/ }));
    const items = screen.getAllByTestId("reviewer-switch-shop");
    expect(items.map((item) => item.textContent)).toEqual([`Chuyển sang ${REVIEWER_SANDBOX_SHOP_LABEL}`]);
    await userEvent.click(items[0]);
    expect(onSwitchShop).toHaveBeenCalledWith(SANDBOX);
    expect(reviewerShopLabel(MASKED)).toBe("Shop TikTok (ẩn danh) · chỉ xem");
    expect(screen.queryByText("Đổi shop")).toBeNull();
  });

  it("one pinned shop: no switch entry", async () => {
    const state = { status: "ready", token: "t", shop: { id: "alias-1", name: MASKED.name }, envelope: { report: { shop_name: MASKED.name }, built_at: null } };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ShopHeader googleHref="x" onRefreshDemo={vi.fn()} onSignOut={vi.fn()} onSwitchShop={vi.fn()} reviewer reviewerShops={[MASKED]} state={state as any} />);
    await userEvent.click(screen.getByRole("button", { name: /Menu shop/ }));
    expect(screen.queryByTestId("reviewer-switch-shop")).toBeNull();
  });

  it("ReviewerProvider keeps a switched-to shop and records its mode", async () => {
    storeAuthSession({ accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
    storeReviewerRecord({ ...REVIEWER, mode: "sandbox", writesEnabled: true });
    storeActiveShop({ id: SANDBOX.id, name: "label" });
    const redirect = vi.fn();
    const fetchMe = vi.fn().mockResolvedValue(me(SANDBOX));
    render(
      <ReviewerProvider fetchMe={fetchMe} redirect={redirect}>
        <span />
      </ReviewerProvider>,
    );
    await waitFor(() => expect(readReviewerRecord()?.shops).toEqual([MASKED, SANDBOX]));
    expect(fetchMe).toHaveBeenCalledWith("at", SANDBOX.id);
    expect(redirect).not.toHaveBeenCalled();
    expect(readActiveShop()).toEqual({ id: SANDBOX.id, name: SANDBOX.name });
    expect(readReviewerRecord()?.mode).toBe("sandbox");
  });

  it("ReviewerProvider falls back to the default (first) pin when the active shop is no pin", async () => {
    storeAuthSession({ accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
    storeReviewerRecord({ ...REVIEWER, mode: "sandbox", writesEnabled: true });
    storeActiveShop({ id: "stale", name: "old" });
    const redirect = vi.fn();
    render(
      <ReviewerProvider fetchMe={vi.fn().mockResolvedValue(me(MASKED))} redirect={redirect}>
        <span />
      </ReviewerProvider>,
    );
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/"));
    expect(readActiveShop()).toEqual({ id: MASKED.id, name: MASKED.name });
    expect(readReviewerRecord()?.mode).toBe("masked");
    expect(readReviewerRecord()?.writesEnabled).toBeUndefined();
  });
});
