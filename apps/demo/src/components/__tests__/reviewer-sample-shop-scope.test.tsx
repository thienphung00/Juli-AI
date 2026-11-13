import { cleanup, configure, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppNavigation } from "../app-shell/app-navigation";
import { SAMPLE_SHOP_SWITCH_LABEL, ShopHeader } from "../app-shell/shop-header";
import { BuilderP92View } from "../shopee-decisions/builder-p92";
import { DecisionsView } from "../shopee-decisions/decisions-view";
import { ProposalsTab } from "../shopee-decisions/product-proposals";
import { hostOf, params } from "../shopee-decisions/__tests__/harness";
import { sampleShopRedirect } from "../../lib/app-navigation";
import { guideCopy } from "../../lib/reviewer/guide-copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import type { ReviewerRecord, ReviewerShopOption } from "../../lib/reviewer/session";
import { sellerLinks } from "../../lib/shopee-analytics/links";
import { P_ZIP, fakeBuilder } from "../../lib/shopee-decisions/__tests__/builder-fixtures";
import { adsCard, fakeReco, promotionCard, summaryOf, voucherCard } from "../../lib/shopee-decisions/__tests__/fixtures";
import type { BuilderP98Api } from "../../lib/shopee-decisions/builder-p98-api";
import { RecoHostProvider, type RecoHost } from "../../lib/shopee-decisions/context";
import type { RecoApi } from "../../lib/shopee-decisions/client";
import type { CardList, CardSummary } from "../../lib/shopee-decisions/types";

/**
 * P100 S2-C: on the reviewer's sample shop ("Dữ liệu mẫu") the rail holds the four Shopee screens and
 * the avatar menu Đổi shop / Đăng xuất. S2-D2 (owner option B): inside those screens the sample shop is
 * the real seller app — every Tự tạo strategy and tool tab, every card. A seller is unchanged.
 */

configure({ asyncUtilTimeout: 4000 });

const SAMPLE: ReviewerRecord = { platform: "shopee", expiresAt: "2026-11-25T00:00:00Z", mode: "sample" };
const MASKED: ReviewerRecord = { platform: "shopee", expiresAt: "2026-11-25T00:00:00Z", mode: "masked" };
const SAMPLE_PIN: ReviewerShopOption = { id: "s-1", name: "Dữ liệu mẫu", mode: "sample", writesEnabled: false };
const SANDBOX_PIN: ReviewerShopOption = { id: "sbx-1", name: "SANDBOX_VN", mode: "sandbox", writesEnabled: true };
const p98 = { combo: vi.fn(), kol: vi.fn(), ads: vi.fn() } as unknown as BuilderP98Api;

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

function withReviewer(reviewer: ReviewerRecord | null, ui: ReactElement, reco: RecoApi = fakeReco(), over: Partial<RecoHost> = {}) {
  return render(
    <StaticReviewerProvider reviewer={reviewer}>
      <RecoHostProvider host={hostOf(reco, over)}>{ui}</RecoHostProvider>
    </StaticReviewerProvider>,
  );
}

const railLabels = () => within(screen.getByRole("navigation", { name: "Điều hướng chính" })).getAllByRole("listitem").map((li) => li.textContent);

describe("S2-C · rail and redirect", () => {
  it("the sample shop's rail lists only Tổng quan · Phân tích · Sản phẩm · Quyết định", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" sampleShop />);
    expect(railLabels()).toEqual(["Tổng quan", "Phân tích", "Sản phẩm", "Quyết định"]);
    expect(document.body.textContent).not.toMatch(/sắp có|demo/i);
  });

  it("a seller's Shopee rail keeps all 8 tabs", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" />);
    expect(railLabels()).toHaveLength(8);
  });

  it("a hidden page, Cài đặt and / (the TikTok Trang chủ) go to Tổng quan; the four screens stay", () => {
    for (const path of ["/", "/tu-khoa", "/quang-cao", "/don-hang", "/luong-san-pham", "/luong-san-pham/x", "/settings"]) {
      expect(sampleShopRedirect(path)).toBe("/tong-quan");
    }
    for (const path of ["/tong-quan", "/phan-tich", "/xep-hang", "/san-pham/BEP-S5", "/decisions"]) {
      expect(sampleShopRedirect(path)).toBeNull();
    }
  });
});

describe("S2-C · avatar menu", () => {
  const state = { status: "ready", token: "t", shop: { id: "s-1", name: "Dữ liệu mẫu" }, envelope: { report: { shop_name: "Dữ liệu mẫu" }, built_at: null } };

  it("the sample shop's menu holds only Đổi shop and Đăng xuất", async () => {
    const onSwitchShop = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ShopHeader googleHref="x" onRefreshDemo={vi.fn()} onSignOut={vi.fn()} onSwitchShop={onSwitchShop} platform="shopee" reviewer reviewerShops={[SAMPLE_PIN, SANDBOX_PIN]} sampleShop state={state as any} />);
    await userEvent.click(screen.getByRole("button", { name: /Menu shop/ }));
    const items = within(screen.getByRole("list")).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual([SAMPLE_SHOP_SWITCH_LABEL, "Đăng xuất"]);
    await userEvent.click(screen.getByText("Đổi shop"));
    expect(onSwitchShop).toHaveBeenCalledWith(SANDBOX_PIN);
  });

  it("another reviewer mode keeps Cài đặt and the labelled switch", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ShopHeader googleHref="x" onRefreshDemo={vi.fn()} onSignOut={vi.fn()} onSwitchShop={vi.fn()} platform="shopee" reviewer reviewerShops={[SANDBOX_PIN, SAMPLE_PIN]} state={{ ...state, shop: { id: "sbx-1", name: "SANDBOX_VN" } } as any} />);
    await userEvent.click(screen.getByRole("button", { name: /Menu shop/ }));
    expect(screen.getByText("Cài đặt")).toBeInTheDocument();
    expect(screen.getByTestId("reviewer-switch-shop").textContent).toMatch(/^Chuyển sang /);
  });
});

describe("S2-D2 · the sample shop is the real seller app", () => {
  async function toKinds() {
    fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
    fireEvent.click(await screen.findByTestId("p2-vnext"));
    return screen.findByTestId("p2-kinds");
  }

  it("Tự tạo offers every strategy and tool tab (Dịch vụ hiển thị included), like a seller", async () => {
    for (const reviewer of [SAMPLE, null, MASKED]) {
      withReviewer(reviewer, <BuilderP92View from="quyet-dinh" p98Api={p98} productId={null} />, fakeReco(), { builder: fakeBuilder() });
      const modes = await screen.findByTestId("p98-modes");
      expect(within(modes).getAllByRole("button").map((b) => b.getAttribute("data-testid"))).toEqual(["p98-mode-single", "p98-mode-combo", "p98-mode-kol", "p98-mode-ads"]);
      const kinds = await toKinds();
      expect(within(kinds).getAllByRole("button")).toHaveLength(13); // P100 w2: Mua kèm + Quà tặng are one "Deal Sốc" kind
      expect(within(kinds).getByTestId("p2-kind-ads")).toBeInTheDocument(); // P100 B.15: edit a running campaign
      cleanup();
    }
  });

  function list(cards: CardSummary[]): CardList {
    return { platform: "shopee", xep_theo: "diem", queue: "all", cards, counts: { family: {}, section: {}, total: cards.length } };
  }
  const item = (_id: string, product: string) => ({ level: "item" as const, product_ids: [product], sku_ids: [], campaign_key: null });
  const title = summaryOf(voucherCard({ id: "c-title", family: "listing", family_label: "Listing", change_kind: "title", scope: item("c-title", "P-1") }), { status: "sent" });
  const ads = summaryOf({ ...adsCard(), id: "c-ads", scope: item("c-ads", "P-4") }, { status: "sent" });
  const promo = summaryOf({ ...promotionCard(), id: "c-promo", scope: item("c-promo", "P-5") }, { status: "approved" });
  const all = [title, ads, promo];
  const tabs = () => within(screen.getByTestId("sd-tabs")).getAllByRole("link").map((a) => a.textContent);

  it("Quyết định lists every card on the sample shop, a running-campaign edit included", async () => {
    for (const reviewer of [SAMPLE, null]) {
      withReviewer(reviewer, <DecisionsView params={params()} />, fakeReco({ list: list(all) }));
      expect(await screen.findByTestId("sq-card-c-ads")).toBeInTheDocument();
      expect(screen.getByTestId("sq-card-c-title")).toBeInTheDocument();
      expect(tabs()).toEqual(["Đề xuất · 2", "Đang thực hiện · 1", "Đo lường · 0"]);
      cleanup();
    }
  });

  it("Sản phẩm › Đề xuất lists every card on the sample shop", () => {
    const mine = [title, { ...promo, status: "sent" as const, product_id: "P-1", product_queue: 2 }];
    render(
      <StaticReviewerProvider reviewer={SAMPLE}>
        <ProposalsTab builderHref="/b" cards={mine} historyHref="/h" links={sellerLinks} reco={fakeReco()} />
      </StaticReviewerProvider>,
    );
    expect(screen.getByTestId("sp-intro").textContent).toMatch(/^2 thẻ/);
  });
});

describe("S2-G · guide copy on the sample shop", () => {
  // Vietnamese-only letters: none may appear outside the app names the guide quotes.
  const VIETNAMESE = /[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i;
  const unquoted = (text: string) => text.replace(/“[^”]*”/g, "");

  it("is English like the rest of P77's guide, about the sample shop, never a seller's hidden shop, never demo", () => {
    const sample = guideCopy(true);
    const prose = [sample.sheetTitle, sample.intro, ...sample.parts.map((p) => p.title), ...sample.steps.slice(0, 4).flatMap((s) => [s.body, s.shortBody])];
    for (const line of prose) expect(unquoted(line)).not.toMatch(VIETNAMESE);
    const text = [sample.title, ...prose, ...sample.steps.slice(0, 4).flatMap((s) => [s.title, s.shortTitle])].join(" ");
    expect(text).toContain("sample Shopee shop");
    expect(text).toContain("nothing is sent to Shopee");
    expect(text).not.toMatch(/shop thật|ẩn tên|names and ids hidden|real seller|Shop TikTok|demo|simulated|mô phỏng/i);
    expect(sample.steps.find((s) => s.id === "propose")?.body).toContain("“Đang thực hiện”");
    expect(sample.steps.map((s) => s.id)).toEqual(guideCopy(false).steps.map((s) => s.id));
    expect(sample.steps.find((s) => s.id === "home")?.href).toBe("/tong-quan");
    expect(sample.steps.find((s) => s.id === "switch")?.shortBody).toContain("Đổi shop");
    // Parts 2 and 3 (the TikTok sandbox) keep the P77 copy
    expect(sample.steps.slice(4)).toEqual(guideCopy(false).steps.slice(4));
    // every other pin keeps the P77 guide
    expect(guideCopy(false).title).toBe("See Juli's live TikTok Shop integration in 8 steps");
  });
});
