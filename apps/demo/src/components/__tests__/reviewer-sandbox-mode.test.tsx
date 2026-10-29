import type { DemoDecisionItem } from "@juli/contracts";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  REVIEWER_SANDBOX_BANNER_COPY,
  REVIEWER_SANDBOX_READ_ONLY_TITLE,
  REVIEWER_SAMPLE_BANNER_COPY,
  REVIEWER_RESET_LABEL,
  SANDBOX_NO_TRAFFIC_COPY,
} from "../../lib/reviewer/copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import type { SandboxShop } from "../../lib/reviewer/sandbox-client";
import type { P10DecisionItem } from "../../lib/quyet-dinh/p10-types";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { ReviewerBanner } from "../app-shell/reviewer-banner";
import { SandboxConnectionCard } from "../reviewer/sandbox-connection-card";
import { SandboxTrafficNote } from "../reviewer/sandbox-traffic-note";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients } from "../quyet-dinh/signed-in-quyet-dinh";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { sampleEnvelope } from "../../lib/phan-tich/sample-data";
import { envelopeHasNoTraffic } from "../reviewer/sandbox-traffic-note";

/**
 * P64 (D73): the partner reviewer pinned to Juli's live TikTok sandbox shop —
 * live data, no sample, no simulation, no `/simulate` call. D73.4: Duyệt is the
 * seller's own approve (an agent run, opened in "Đang thực hiện" over SSE).
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const SANDBOX = { platform: "shopee", expiresAt: "2026-11-13T00:00:00Z", mode: "sandbox", writesEnabled: true } as const;

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function decision(id: string): P10DecisionItem {
  return {
    id,
    title: "Tối ưu Sản phẩm 123",
    description: "",
    severity: "high",
    priority: 1,
    computed_at: null,
    surfaced_at: null,
    is_executable: true,
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: "2026-10-09",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: { code: "card", label: "Hiển thị → Lượt nhấp" },
        lever: { code: "title", label: "Tiêu đề", action: "Viết lại tiêu đề" },
        main_kpi: { key: "ctr", label: "CTR", value: "1,2 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: 70_000,
        product_title: "Sản phẩm 123",
        tiktok_product_id: "an-product-1a2b3c4d",
      },
      card: {
        seller_sku: null,
        seller_sku_more: 0,
        product_title: "Sản phẩm 123",
        workflow_label: "Tối ưu sản phẩm",
        updated_at: new Date().toISOString(),
        status: "pending",
        main_kpi: { key: "ctr", label: "CTR - Thẻ sản phẩm", current: 0.012, target: 0.015, unit: "ratio" },
        expected_gmv_per_month: 2_100_000,
        reason_short: "Ít người bấm vào sản phẩm",
        reason_full: "CTR thấp hơn trung vị shop.",
        tiktok_codes: [],
        lever: { code: "title", label: "Tiêu đề", executor: "juli" },
        change_fields: [{ field: "title", label: "Tiêu đề" }],
        before_after: [],
        gmv_method: null,
      },
    },
  } as unknown as P10DecisionItem;
}

function rules(): ShopRules {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  return {
    stability_band: { ctr: { value: 3, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T00:00:00Z" } },
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 },
    auto_levers: { ...unset, value: [] },
    protected_terms: { ...unset, value: [] },
    band_metrics: ["ctr"],
    listing_levers: ["title", "description"],
  } as ShopRules;
}

function noBands(): ShopRules {
  return { ...rules(), stability_band: {} } as ShopRules;
}

function qdClients(over: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([decision("card-1")] as unknown as DemoDecisionItem[]),
    approve: vi.fn().mockResolvedValue({ runId: "run-1" }),
    reject: vi.fn(),
    fetchRuns: vi.fn().mockResolvedValue([]),
    fetchRules: vi.fn().mockResolvedValue(rules()),
    fetchChanges: vi.fn(),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
    ...over,
  };
}


const SHOP: SandboxShop = {
  shop: { id: "shop-1", name: "Juli Sandbox", tiktok_shop_code: "VNLCJ7495", platform: "tiktok" },
  mode: "sandbox",
  writes_enabled: true,
  connection: {
    status: "active",
    capability: "write",
    authorized_at: "2026-10-01T03:00:00Z",
    last_refreshed_at: null,
    token_expires_at: null,
    scopes: ["product.read", "product.write"],
  },
  synced_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  sync_endpoints: [],
  sync_interval_seconds: 60,
};

describe("mode switch", () => {
  it("sandbox banner replaces the sample copy and offers no reset", () => {
    render(<ReviewerBanner onReset={vi.fn()} reviewer={SANDBOX} />);
    const banner = screen.getByTestId("reviewer-banner");
    expect(banner).toHaveTextContent(REVIEWER_SANDBOX_BANNER_COPY);
    expect(banner).toHaveTextContent(/^Tài khoản đối tác .* · shop sandbox TikTok/);
    expect(banner.textContent ?? "").not.toContain("ghi thật");
    expect(banner.textContent ?? "").not.toContain("Đối tác Shopee");
    expect(banner).not.toHaveTextContent("mô phỏng");
    expect(banner).not.toHaveTextContent("dữ liệu mẫu");
    expect(screen.queryByRole("button", { name: REVIEWER_RESET_LABEL })).toBeNull();
  });

  it("the sample reviewer keeps its banner and reset", () => {
    render(<ReviewerBanner onReset={vi.fn()} reviewer={{ platform: "shopee", expiresAt: null, sample: true }} />);
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent(REVIEWER_SAMPLE_BANNER_COPY);
    expect(screen.getByRole("button", { name: REVIEWER_RESET_LABEL })).toBeInTheDocument();
  });

  it("sandbox Duyệt is the seller's approve and opens the run; other writes say read-only", async () => {
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);
    const onNavigate = vi.fn();
    const c = qdClients();
    render(
      <StaticReviewerProvider reviewer={SANDBOX}>
        <SignedInQuyetDinh
          clients={c}
          onNavigate={onNavigate}
          query={{ tab: "de-xuat", run: null, rulesOpen: false }}
          shop={{ id: "shop-1", name: "Juli Sandbox" }}
          token="tok"
        />
      </StaticReviewerProvider>,
    );
    const card = await screen.findByTestId("recommendation-card");
    expect(within(card).getByRole("button", { name: "Từ chối" })).toHaveAttribute("title", REVIEWER_SANDBOX_READ_ONLY_TITLE);
    const approve = within(card).getByRole("button", { name: "Duyệt" });
    expect(approve).toBeEnabled();
    await userEvent.click(approve);
    await waitFor(() => expect(c.approve).toHaveBeenCalledWith("card-1", { token: "tok", shopId: "shop-1" }));
    // The run Duyệt started opens in "Đang thực hiện" (its SSE stream, like a seller's).
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith(expect.stringContaining("run=run-1")));
    expect(onNavigate.mock.calls.at(-1)?.[0]).toContain("dang-thuc-hien");
    expect(screen.queryByTestId("reviewer-simulation")).toBeNull();
    expect(screen.queryByTestId("sandbox-decision")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("without stability bands the sandbox Duyệt waits like a seller's", async () => {
    const c = qdClients({ fetchRules: vi.fn().mockResolvedValue(noBands()) });
    render(
      <StaticReviewerProvider reviewer={SANDBOX}>
        <SignedInQuyetDinh
          clients={c}
          onNavigate={vi.fn()}
          query={{ tab: "de-xuat", run: null, rulesOpen: false }}
          shop={{ id: "shop-1", name: "Juli Sandbox" }}
          token="tok"
        />
      </StaticReviewerProvider>,
    );
    const card = await screen.findByTestId("recommendation-card");
    await waitFor(() => expect(within(card).getByRole("button", { name: "Duyệt" })).toBeDisabled());
    expect(c.approve).not.toHaveBeenCalled();
  });
});

describe("connection card", () => {
  it("shows the shop, Đã kết nối, authorisation, scopes and the sync time", async () => {
    render(<SandboxConnectionCard fetchShop={vi.fn().mockResolvedValue(SHOP)} sync={vi.fn()} token="t" />);
    const card = await screen.findByText("Juli Sandbox");
    expect(card).toBeInTheDocument();
    expect(screen.getByTestId("sandbox-connection-status")).toHaveTextContent("Đã kết nối");
    expect(screen.getByTestId("sandbox-connection")).toHaveTextContent("Ủy quyền lúc");
    expect(screen.getByTestId("sandbox-connection")).toHaveTextContent("Mã shop TikTokVNLCJ7495");
    expect(screen.getByTestId("sandbox-synced-at")).toHaveTextContent(/Đồng bộ lúc .*\(5 phút trước\)/);
    expect(screen.getByText("product.write")).toBeInTheDocument();
  });

  it("hides the Mã shop TikTok row when the shop code is unknown (never the internal id)", async () => {
    const shop: SandboxShop = { ...SHOP, shop: { ...SHOP.shop, tiktok_shop_code: null } };
    render(<SandboxConnectionCard fetchShop={vi.fn().mockResolvedValue(shop)} sync={vi.fn()} token="t" />);
    await screen.findByText("Juli Sandbox");
    expect(screen.getByTestId("sandbox-connection")).not.toHaveTextContent("Mã shop TikTok");
  });

  it("Đồng bộ ngay: queued, then a 429 disables the button with a countdown that expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchShop = vi.fn().mockResolvedValue(SHOP);
    const sync = vi
      .fn()
      .mockResolvedValueOnce({ status: "queued", syncedAt: SHOP.synced_at, retryAfterSeconds: 3 })
      .mockResolvedValueOnce({ status: "rate_limited", retryAfterSeconds: 2 });
    render(<SandboxConnectionCard fetchShop={fetchShop} refreshMs={5_000} sync={sync} token="t" />);
    const button = await screen.findByRole("button", { name: "Đồng bộ ngay" });
    await act(async () => {
      button.click();
    });
    expect(await screen.findByText("Đang đồng bộ…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Đồng bộ ngay \(3s\)/ })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(screen.getByRole("button", { name: "Đồng bộ ngay" })).toBeEnabled();
    // The shop is re-read every ~5 s after a queued sync.
    expect(fetchShop).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchShop).toHaveBeenCalledTimes(2);
    await act(async () => {
      screen.getByRole("button", { name: "Đồng bộ ngay" }).click();
    });
    const limited = await screen.findByRole("button", { name: /Đồng bộ ngay \(2s\)/ });
    expect(limited).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByRole("button", { name: "Đồng bộ ngay" })).toBeEnabled();
  });
});

describe("connection card sync refresh", () => {
  it("polls every 5 s until the sync time changes, then stops and drops 'Đang đồng bộ…'", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const later = { ...SHOP, synced_at: new Date().toISOString() };
    const fetchShop = vi
      .fn()
      .mockResolvedValueOnce(SHOP)
      .mockResolvedValueOnce(SHOP)
      .mockResolvedValue(later);
    const sync = vi.fn().mockResolvedValue({ status: "queued", syncedAt: SHOP.synced_at, retryAfterSeconds: 60 });
    render(<SandboxConnectionCard fetchShop={fetchShop} sync={sync} token="t" />);
    const button = await screen.findByRole("button", { name: "Đồng bộ ngay" });
    await act(async () => {
      button.click();
    });
    expect(await screen.findByText("Đang đồng bộ…")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100);
    });
    expect(screen.getByText("Đang đồng bộ…")).toBeInTheDocument(); // same time: keep polling
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100);
    });
    expect(screen.queryByText("Đang đồng bộ…")).toBeNull();
    expect(screen.getByTestId("sandbox-synced-at")).toHaveTextContent(/\(vừa xong\)/);
    const calls = fetchShop.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetchShop).toHaveBeenCalledTimes(calls);
  });

  it("gives up after the maximum poll time when the sync time never changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchShop = vi.fn().mockResolvedValue(SHOP);
    const sync = vi.fn().mockResolvedValue({ status: "queued", syncedAt: SHOP.synced_at, retryAfterSeconds: 60 });
    render(<SandboxConnectionCard fetchShop={fetchShop} maxPollMs={90_000} refreshMs={5_000} sync={sync} token="t" />);
    const button = await screen.findByRole("button", { name: "Đồng bộ ngay" });
    await act(async () => {
      button.click();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(95_000);
    });
    expect(screen.queryByText("Đang đồng bộ…")).toBeNull();
    const calls = fetchShop.mock.calls.length;
    expect(calls).toBeGreaterThan(10);
    expect(calls).toBeLessThanOrEqual(20);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchShop).toHaveBeenCalledTimes(calls);
  });
});

describe("empty analytics", () => {
  it("renders nothing for a non-sandbox reviewer and no note when the envelope is not buildable", () => {
    const { container } = render(
      <StaticReviewerProvider reviewer={{ platform: "shopee", expiresAt: null }}>
        <SandboxTrafficNote envelope={{} as ShopAnalysisEnvelope} />
      </StaticReviewerProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("no stream with a view shows the note in sandbox mode; a shop with traffic does not", () => {
    const withTraffic = sampleEnvelope();
    expect(envelopeHasNoTraffic(withTraffic)).toBe(false);
    const empty = { ...withTraffic, report: { ...withTraffic.report, channels: [], affiliate_rows: [] } } as unknown as ShopAnalysisEnvelope;
    expect(envelopeHasNoTraffic(empty)).toBe(true);
    render(
      <StaticReviewerProvider reviewer={SANDBOX}>
        <SandboxTrafficNote envelope={empty} />
      </StaticReviewerProvider>,
    );
    expect(screen.getByTestId("sandbox-no-traffic")).toHaveTextContent(SANDBOX_NO_TRAFFIC_COPY);
  });

  it("copy is the agreed honest empty state", () => {
    expect(SANDBOX_NO_TRAFFIC_COPY).toBe(
      "TikTok sandbox chưa có lượt xem/traffic — số liệu đơn hàng và sản phẩm vẫn lấy trực tiếp từ TikTok",
    );
  });
});
