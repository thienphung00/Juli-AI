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
  sandboxErrorCopy,
} from "../../lib/reviewer/copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import { SandboxError, type SandboxExecution, type SandboxPlan, type SandboxShop } from "../../lib/reviewer/sandbox-client";
import type { P10DecisionItem } from "../../lib/quyet-dinh/p10-types";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { ReviewerBanner } from "../app-shell/reviewer-banner";
import { SandboxConnectionCard } from "../reviewer/sandbox-connection-card";
import { SandboxTrafficNote } from "../reviewer/sandbox-traffic-note";
import { SandboxDecisionDialog, type SandboxDecisionClient } from "../quyet-dinh/sandbox-decision-dialog";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients } from "../quyet-dinh/signed-in-quyet-dinh";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { sampleEnvelope } from "../../lib/phan-tich/sample-data";
import { envelopeHasNoTraffic } from "../reviewer/sandbox-traffic-note";

/**
 * P64 (D73): the partner reviewer pinned to Juli's live TikTok sandbox shop —
 * live data, real Duyệt / Thực thi with TikTok's read-back, no sample, no
 * simulation, no `/simulate` call.
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
    title: "Tối ưu Demo Product 123",
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
        product_title: "Demo Product 123",
        tiktok_product_id: "demo-product-1a2b3c4d",
      },
      card: {
        seller_sku: null,
        seller_sku_more: 0,
        product_title: "Demo Product 123",
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
  shop: { id: "shop-1", name: "Juli Sandbox", tiktok_shop_id: "7495", platform: "tiktok" },
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

const PLAN: SandboxPlan = {
  change: {
    executor: "juli",
    lever: { code: "title", label: "Tiêu đề" },
    product: { title: "Demo Product 123", tiktok_product_id: "p-1" },
    fields: [{ field: "title", label: "Tiêu đề", before: "Demo Product 123", after: "Tiêu đề Juli đề xuất" }],
  },
  executable: true,
  requires_image: false,
};

const EXECUTION: SandboxExecution = {
  lever: { code: "title", label: "Tiêu đề" },
  tiktok_product_id: "p-1",
  operations: ["edit_product"],
  read_back: {
    confirmed_at: "2026-10-21T03:30:00Z",
    fields: [
      { field: "title", before: "Demo Product 123", after: "Tiêu đề Juli đề xuất", after_source: "tiktok" },
      { field: "description", before: "Mô tả cũ", after: "Mô tả dự kiến", after_source: "intended" },
    ],
    listing: { title: "Tiêu đề Juli đề xuất" },
  },
};

describe("mode switch", () => {
  it("sandbox banner replaces the sample copy and offers no reset", () => {
    render(<ReviewerBanner onReset={vi.fn()} reviewer={SANDBOX} />);
    const banner = screen.getByTestId("reviewer-banner");
    expect(banner).toHaveTextContent(REVIEWER_SANDBOX_BANNER_COPY);
    expect(banner).not.toHaveTextContent("mô phỏng");
    expect(banner).not.toHaveTextContent("dữ liệu mẫu");
    expect(screen.queryByRole("button", { name: REVIEWER_RESET_LABEL })).toBeNull();
  });

  it("the sample reviewer keeps its banner and reset", () => {
    render(<ReviewerBanner onReset={vi.fn()} reviewer={{ platform: "shopee", expiresAt: null, sample: true }} />);
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent(REVIEWER_SAMPLE_BANNER_COPY);
    expect(screen.getByRole("button", { name: REVIEWER_RESET_LABEL })).toBeInTheDocument();
  });

  it("sandbox Duyệt calls the live approve and never /simulate; other writes say read-only", async () => {
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);
    const sandboxClient: SandboxDecisionClient = { approve: vi.fn().mockResolvedValue(PLAN), execute: vi.fn() };
    const c = qdClients();
    render(
      <StaticReviewerProvider reviewer={SANDBOX}>
        <SignedInQuyetDinh
          clients={c}
          onNavigate={vi.fn()}
          query={{ tab: "de-xuat", run: null, rulesOpen: false }}
          sandboxClient={sandboxClient}
          shop={{ id: "shop-1", name: "Juli Sandbox" }}
          token="tok"
        />
      </StaticReviewerProvider>,
    );
    const card = await screen.findByTestId("recommendation-card");
    expect(within(card).getByRole("button", { name: "Từ chối" })).toHaveAttribute("title", REVIEWER_SANDBOX_READ_ONLY_TITLE);
    await userEvent.click(within(card).getByRole("button", { name: "Duyệt" }));
    const dialog = await screen.findByTestId("sandbox-decision");
    expect(await within(dialog).findByTestId("sandbox-plan")).toHaveTextContent("Tiêu đề Juli đề xuất");
    expect(sandboxClient.approve).toHaveBeenCalledWith("card-1");
    expect(screen.queryByTestId("reviewer-simulation")).toBeNull();
    expect(dialog).not.toHaveTextContent("mô phỏng");
    expect(dialog).not.toHaveTextContent("Mô phỏng");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(c.approve).not.toHaveBeenCalled();
  });
});

describe("Thực thi on the sandbox", () => {
  it("shows each field before → after, TikTok's confirmation time and marks an intended value", async () => {
    const client: SandboxDecisionClient = { approve: vi.fn().mockResolvedValue(PLAN), execute: vi.fn().mockResolvedValue(EXECUTION) };
    render(<SandboxDecisionDialog cardId="card-1" client={client} onClose={vi.fn()} />);
    const title = await screen.findByLabelText("Tiêu đề mới");
    expect(title).toHaveValue("Tiêu đề Juli đề xuất");
    await userEvent.clear(title);
    await userEvent.type(title, "Tiêu đề sửa tay");
    await userEvent.click(screen.getByRole("button", { name: "Thực thi" }));
    const result = await screen.findByTestId("sandbox-result");
    expect(client.execute).toHaveBeenCalledWith("card-1", { title: "Tiêu đề sửa tay" });
    expect(result).toHaveTextContent("Demo Product 123");
    expect(result).toHaveTextContent("Tiêu đề Juli đề xuất");
    expect(screen.getByTestId("sandbox-confirmed-at")).toHaveTextContent(/TikTok xác nhận lúc .*21\/10\/2026/);
    // 03:30 UTC is 10:30 in Asia/Ho_Chi_Minh.
    expect(screen.getByTestId("sandbox-confirmed-at")).toHaveTextContent("10:30");
    expect(screen.getAllByTestId("sandbox-intended")).toHaveLength(1);
    expect(screen.getByTestId("sandbox-intended")).toHaveTextContent("chưa được TikTok xác nhận");
  });

  it("12052048 shows the sync-and-retry copy and keeps the form", async () => {
    const execute = vi.fn().mockRejectedValue(new SandboxError(409, "product_not_owned_by_sandbox_seller", 12052048));
    render(<SandboxDecisionDialog cardId="card-1" client={{ approve: vi.fn().mockResolvedValue(PLAN), execute }} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Thực thi" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sản phẩm không thuộc shop sandbox — bấm Đồng bộ ngay rồi thử lại");
    expect(screen.getByRole("button", { name: "Thực thi" })).toBeEnabled();
  });

  it("a cover-image card needs the file before Thực thi and sends it as base64", async () => {
    const plan: SandboxPlan = { ...PLAN, change: { ...PLAN.change, executor: "juli_with_photo", lever: { code: "cover_image", label: "Ảnh bìa" }, fields: [] }, requires_image: true };
    const execute = vi.fn().mockResolvedValue({ ...EXECUTION, read_back: { ...EXECUTION.read_back, fields: [] } });
    render(<SandboxDecisionDialog cardId="card-1" client={{ approve: vi.fn().mockResolvedValue(plan), execute }} onClose={vi.fn()} />);
    const button = await screen.findByRole("button", { name: "Thực thi" });
    expect(button).toBeDisabled();
    await userEvent.upload(screen.getByLabelText("Ảnh bìa mới"), new File(["abc"], "a.png", { type: "image/png" }));
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await waitFor(() => expect(execute).toHaveBeenCalledWith("card-1", { image_base64: "YWJj" }));
  });

  it("maps every error code to Vietnamese copy", () => {
    for (const code of ["not_executable_by_juli", "no_product", "image_required", "image_invalid", "no_content", "write_refused", "tiktok_error", "tiktok_unconfigured"]) {
      expect(sandboxErrorCopy(code, null, 400)).toMatch(/\S/);
      expect(sandboxErrorCopy(code, null, 400)).not.toContain(code);
    }
  });
});

describe("connection card", () => {
  it("shows the shop, Đã kết nối, authorisation, scopes and the sync time", async () => {
    render(<SandboxConnectionCard fetchShop={vi.fn().mockResolvedValue(SHOP)} sync={vi.fn()} token="t" />);
    const card = await screen.findByText("Juli Sandbox");
    expect(card).toBeInTheDocument();
    expect(screen.getByTestId("sandbox-connection-status")).toHaveTextContent("Đã kết nối");
    expect(screen.getByTestId("sandbox-connection")).toHaveTextContent("Ủy quyền lúc");
    expect(screen.getByTestId("sandbox-connection")).toHaveTextContent("7495");
    expect(screen.getByTestId("sandbox-synced-at")).toHaveTextContent(/Đồng bộ lúc .*\(5 phút trước\)/);
    expect(screen.getByText("product.write")).toBeInTheDocument();
  });

  it("Đồng bộ ngay: queued, then a 429 disables the button with a countdown that expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchShop = vi.fn().mockResolvedValue(SHOP);
    const sync = vi
      .fn()
      .mockResolvedValueOnce({ status: "queued", syncedAt: SHOP.synced_at, retryAfterSeconds: 3 })
      .mockResolvedValueOnce({ status: "rate_limited", retryAfterSeconds: 2 });
    render(<SandboxConnectionCard fetchShop={fetchShop} refreshMs={10_000} sync={sync} token="t" />);
    const button = await screen.findByRole("button", { name: "Đồng bộ ngay" });
    await act(async () => {
      button.click();
    });
    expect(await screen.findByText(/Đã xếp lịch đồng bộ/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Đồng bộ ngay \(3s\)/ })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(screen.getByRole("button", { name: "Đồng bộ ngay" })).toBeEnabled();
    // The shop is re-read ~10 s after a queued sync.
    expect(fetchShop).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(7000);
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
