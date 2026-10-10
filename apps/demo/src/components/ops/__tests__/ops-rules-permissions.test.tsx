import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { PermissionStrip } from "../../app-shell/permission-strip";
import { OpsOverview } from "../ops-overview";
import { OpsRules } from "../ops-rules";
import { ME, OVERVIEW, SHOP_ID } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const RULES = {
  stability_band: {},
  product_cost: {},
  max_discount_pct: {},
  min_margin_pct: null,
  max_open_cards: { ...unset, value: 30 },
  auto_levers: { ...unset, value: ["title"] },
  protected_terms: { ...unset, value: [] },
  band_metrics: ["ctr"],
  listing_levers: ["title", "description", "attributes", "image"],
  content_tone: null,
  banned_terms: null,
};

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Quy tắc in Cài đặt shop (D25.14)", () => {
  it("edits the seller's rules through the ops API, always as the team", async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const base = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return new Response(JSON.stringify({ data: RULES }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    render(<OpsRules baseFetch={base as unknown as typeof fetch} canEdit shopId={SHOP_ID} />);
    const section = await screen.findByTestId("ops-rules");
    await within(section).findByTestId("rules-editor");
    expect(within(section).queryByText(/Đội ngũ Juli đặt thay seller|Tôi là đội ngũ/)).toBeNull();
    const tone = within(section).getByTestId("rule-content_tone");
    fireEvent.change(within(tone).getByRole("textbox"), { target: { value: "Thân thiện" } });
    fireEvent.click(within(tone).getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(calls.some(([u, i]) => u === `/v1/ops/shops/${SHOP_ID}/rules/content_tone` && i?.method === "PUT")).toBe(true));
    const put = calls.find(([u, i]) => u.endsWith("/rules/content_tone") && i?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ value: "Thân thiện", set_by: "team" });
    expect(within(section).getByTestId("rule-banned_terms")).toBeInTheDocument();
    expect(calls[0][0]).toBe(`/v1/ops/shops/${SHOP_ID}/rules`);
  });

  it("is read-only for Xem", async () => {
    const base = vi.fn(async () => new Response(JSON.stringify({ data: RULES }), { status: 200 }));
    render(<OpsRules baseFetch={base as unknown as typeof fetch} canEdit={false} shopId={SHOP_ID} />);
    const section = await screen.findByTestId("ops-rules");
    await within(section).findByTestId("rules-editor");
    expect(section.querySelector("fieldset")).toBeDisabled();
  });
});

describe("permission status (D25.15)", () => {
  it("Ops overview shows Đủ quyền / Thiếu N quyền / chưa rõ", async () => {
    const shops = [
      { ...OVERVIEW.shops[0], permissions: { status: "missing" as const, missing: [{ scope: "seller.finance.info", used_for: "x" }], needs_reconnect: true } },
      { ...OVERVIEW.shops[1], permissions: { status: "complete" as const, missing: [], needs_reconnect: false } },
      OVERVIEW.shops[2],
    ];
    render(<OpsOverview api={{ overview: async () => ({ ...OVERVIEW, shops }), disconnect: vi.fn() }} me={ME} />);
    expect(await screen.findByTestId("missing-scopes")).toHaveTextContent("Thiếu 1 quyền");
    expect(screen.getByText("Đủ quyền")).toBeInTheDocument();
  });

  it("the seller sees the reconnect strip only when a scope is missing", async () => {
    const yes = vi.fn(async () => new Response(JSON.stringify({ data: { needs_reconnect: true } }), { status: 200 }));
    const { unmount } = render(<PermissionStrip fetchImpl={yes as unknown as typeof fetch} shopId="s" token="t" />);
    expect(await screen.findByTestId("permission-strip")).toHaveTextContent("Kết nối lại TikTok Shop để cấp quyền mới");
    expect(screen.getByRole("link", { name: "Kết nối lại ›" })).toHaveAttribute("href", "/auth/connect-shop");
    unmount();
    const no = vi.fn(async () => new Response(JSON.stringify({ data: { needs_reconnect: false } }), { status: 200 }));
    render(<PermissionStrip fetchImpl={no as unknown as typeof fetch} shopId="s" token="t" />);
    await waitFor(() => expect(no).toHaveBeenCalledWith("/v1/shops/me/permissions", expect.anything()));
    expect(screen.queryByTestId("permission-strip")).toBeNull();
  });
});
