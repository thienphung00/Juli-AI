import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { reviewerSampleClients } from "../../lib/reviewer/sample-store";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { QuyetDinhView } from "../quyet-dinh/quyet-dinh-view";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { SignedInRulesSettings } from "../quyet-dinh/settings-rules";

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const seller = (value: unknown) => ({ value, set_by: "seller" as const, set_by_user_id: "u1", set_at: "2026-10-10T03:00:00Z" });

function rules(over: Partial<ShopRules> = {}): ShopRules {
  return {
    stability_band: {}, product_cost: {}, max_discount_pct: {}, min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 }, auto_levers: { ...unset, value: ["title"] }, protected_terms: { ...unset, value: [] },
    band_metrics: ["ctr"], listing_levers: ["title"], sku_cost: {}, default_gross_margin_pct: null, default_max_discount_pct: null, program_fee_pct: null,
    joins_platform_campaigns: null, platform_campaign_note: null, target_roas: null, gmv_max_daily_budget: null, live_schedule: null,
    weekdays: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], ...over,
  };
}

describe("F1.6 · a Shopee shop's rules never say TikTok", () => {
  it("the editor has no TikTok text anywhere", () => {
    const { container } = render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} platform="shopee" rules={rules({ sku_cost: { "1001:2002": seller(65125.13) } })} />);
    expect(container.textContent).not.toMatch(/TikTok/);
    expect(container.textContent).not.toMatch(/GMV Max/);
  });

  it("an unknown platform names neither marketplace", () => {
    const { container } = render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} platform="unknown" rules={rules()} />);
    expect(container.textContent).not.toMatch(/TikTok/);
    expect(container.textContent).not.toMatch(/Shopee/);
  });

  it("the Quyết định rules panel of a Shopee shop has no TikTok text", async () => {
    const clients = reviewerSampleClients();
    const { container } = render(<QuyetDinhView clients={clients} onNavigate={vi.fn()} platform="shopee" query={{ tab: "de-xuat", run: null, rulesOpen: true }} shop={{ id: "s", name: "Shop thử" }} token="t" />);
    const editor = await screen.findByTestId("rules-editor");
    expect(editor.textContent).not.toMatch(/TikTok/);
    expect(container.querySelector('[data-testid="rules-editor"]')).toBe(editor);
  });

  it("cost rows show the product and variation name with VN money", () => {
    render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} platform="shopee" rules={rules({ sku_cost: { "1001:2002": seller(65125.13) } })} scopeNames={{ "1001:2002": "Găng tay thử · Size M" }} />);
    expect(screen.getByText("Găng tay thử · Size M")).toBeInTheDocument();
    expect(screen.getByText(/65\.125 ₫\/sản phẩm/)).toBeInTheDocument();
    expect(screen.queryByText(/1001:2002/)).toBeNull();
  });

  it("the Cài đặt rules page loads names from the catalogue and has no TikTok text", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: RequestInfo | URL) => {
      calls.push(String(url));
      return new Response(JSON.stringify({ item_id: "1001", name: "Găng tay thử", excluded: false, exclude_reason: null, columns: [], margin_basis: "", missing_cost: [], variations: [{ variation_id: "2002", name: "Size M" }] }), { status: 200, headers: { "content-type": "application/json" } });
    }) as unknown as typeof fetch;
    const fetchRules = vi.fn(async () => rules({ sku_cost: { "1001:2002": seller(65125.13) } }));
    const { container } = render(<SignedInRulesSettings auth={{ token: "t", shopId: "s", fetchImpl }} fetchRules={fetchRules} platform="shopee" shopName="Shop thử" />);
    expect(await screen.findByText("Găng tay thử · Size M")).toBeInTheDocument();
    expect(calls.some((u) => u.includes("/builder/products/1001/variations"))).toBe(true);
    expect(container.textContent).not.toMatch(/TikTok/);
  });
});
