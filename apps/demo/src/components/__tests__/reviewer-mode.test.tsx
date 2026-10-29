import type { DemoDecisionItem } from "@juli/contracts";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmailSignInPage from "../../app/auth/email/page";
import type { SimulationResult } from "../../lib/reviewer/api-client";
import { REVIEWER_BANNER_COPY, REVIEWER_READ_ONLY_TITLE, REVIEWER_SIMULATED_LABEL } from "../../lib/reviewer/copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import { ReviewerProvider } from "../../lib/reviewer/reviewer-context";
import { REVIEWER_STORAGE_KEY, readReviewerRecord, storeReviewerRecord } from "../../lib/reviewer/session";
import type { P10DecisionItem } from "../../lib/quyet-dinh/p10-types";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { ACTIVE_SHOP_STORAGE_KEY, readActiveShop } from "../../lib/shop-session";
import { AUTH_SESSION_STORAGE_KEY, PASSWORD_SIGN_IN_ERROR_COPY, readAuthSession, storeAuthSession } from "../../lib/supabase-auth";
import { NoShopSampleStrip } from "../app-shell/no-shop-sample-strip";
import { ReviewerBanner } from "../app-shell/reviewer-banner";
import { ShopHeader } from "../app-shell/shop-header";
import { PartnerSignIn, denialFromLocation } from "../partner-sign-in";
import { ReviewerSimulation } from "../quyet-dinh/reviewer-simulation";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients } from "../quyet-dinh/signed-in-quyet-dinh";

/**
 * P32-A (AC-32.2 / AC-32.7): the partner trial account in the demo — the
 * password form, the banner, no connect entry, and Duyệt → Thực thi as a
 * simulation that never calls the real approve.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const REVIEWER = { platform: "shopee", expiresAt: "2026-11-13T00:00:00Z" };

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

const SIMULATION_APPROVE: SimulationResult = {
  simulated: true,
  step: "approve",
  action_card_id: "card-1",
  label: REVIEWER_SIMULATED_LABEL,
  steps: [
    { key: "approve", label: "Duyệt", done: true },
    { key: "execute", label: "Thực thi", done: false },
  ],
  change: {
    executor: "juli",
    lever: { code: "title", label: "Tiêu đề" },
    product: { title: "Sản phẩm 123", tiktok_product_id: "an-product-1a2b3c4d" },
    request: { method: "PUT", path: "/product/202309/products/{product_id}", operation: "update_product_listing", fields: ["title"] },
    fields: [{ field: "title", label: "Tiêu đề", before: "Sản phẩm 123", after: "Juli soạn nội dung mới sau khi duyệt" }],
    note: "Nội dung mới do Juli soạn sau khi duyệt.",
  },
  enqueued: false,
  tiktok_write: false,
};
const SIMULATION_EXECUTE: SimulationResult = {
  ...SIMULATION_APPROVE,
  step: "execute",
  steps: SIMULATION_APPROVE.steps.map((s) => ({ ...s, done: true })),
};

describe("password sign-in (Tài khoản đối tác)", () => {
  async function open(props: Parameters<typeof PartnerSignIn>[0]) {
    render(<PartnerSignIn {...props} />);
    await userEvent.type(screen.getByLabelText("Email"), "shopee-review@app-juli.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
  }

  it("a reviewer: session, reference shop and reviewer record stored, then Trang chủ", async () => {
    const signIn = vi.fn().mockResolvedValue({ ok: true, session: { accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" } });
    const fetchMe = vi.fn().mockResolvedValue({
      status: "reviewer",
      me: { reviewer: true, platform: "shopee", expiresAt: REVIEWER.expiresAt, shop: { id: "alias-1", name: "Shop TikTok (ẩn danh)" } },
    });
    const onSignedIn = vi.fn();
    await open({ signIn, fetchMe, onSignedIn });
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(signIn).toHaveBeenCalledWith("shopee-review@app-juli.com", "s3cret");
    expect(fetchMe).toHaveBeenCalledWith("at");
    expect(readAuthSession()?.accessToken).toBe("at");
    expect(readActiveShop()).toEqual({ id: "alias-1", name: "Shop TikTok (ẩn danh)" });
    expect(readReviewerRecord()).toEqual(REVIEWER);
  });

  it.each([
    [{ status: "denied", denial: "expired" }, PASSWORD_SIGN_IN_ERROR_COPY.expired],
    [{ status: "denied", denial: "revoked" }, PASSWORD_SIGN_IN_ERROR_COPY.revoked],
    [{ status: "not_reviewer" }, PASSWORD_SIGN_IN_ERROR_COPY.not_trial],
  ])("signs out again on %j", async (me, copy) => {
    const signIn = vi.fn().mockResolvedValue({ ok: true, session: { accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" } });
    const onSignedIn = vi.fn();
    await open({ signIn, fetchMe: vi.fn().mockResolvedValue(me), onSignedIn });
    expect(await screen.findByText(copy)).toBeInTheDocument();
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_SHOP_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(REVIEWER_STORAGE_KEY)).toBeNull();
  });

  it("a wrong password shows the Vietnamese error and never asks the API", async () => {
    const fetchMe = vi.fn();
    await open({ signIn: vi.fn().mockResolvedValue({ ok: false, error: "wrong" }), fetchMe });
    expect(await screen.findByText("Sai email hoặc mật khẩu.")).toBeInTheDocument();
    expect(fetchMe).not.toHaveBeenCalled();
  });

  it("D47.6: a reviewer reaches this form from the entry at the top of /auth/email, no scrolling to the footer", async () => {
    window.history.replaceState(null, "", "/auth/email");
    const user = userEvent.setup();
    render(<EmailSignInPage />);

    const top = screen.getByRole("link", { name: "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác" });
    // The first control of the column, ahead of the seller heading.
    expect(
      top.compareDocumentPosition(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await user.click(top);

    expect(screen.getByRole("form", { name: "Đăng nhập bằng mật khẩu" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("autocomplete", "current-password");
    window.history.replaceState(null, "", "/");
  });

  it("offers no sign-up and no password reset", async () => {
    render(<PartnerSignIn />);
    expect(screen.queryByText(/đăng ký/i)).toBeNull();
    expect(screen.queryByText(/quên mật khẩu/i)).toBeNull();
  });

  it("reads the shell's denial from the URL", () => {
    expect(denialFromLocation("?doi-tac=expired")).toBe("expired");
    expect(denialFromLocation("?doi-tac=revoked")).toBe("revoked");
    expect(denialFromLocation("")).toBeNull();
  });
});

describe("reviewer mode in the shell", () => {
  it("the banner carries the exact copy, the platform and the expiry", () => {
    render(<ReviewerBanner reviewer={REVIEWER} />);
    const banner = screen.getByTestId("reviewer-banner");
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveTextContent(REVIEWER_BANNER_COPY);
    expect(banner).toHaveTextContent("Tài khoản đối tác · dữ liệu shop thật đã ẩn tên · chỉ xem, duyệt chỉ mô phỏng");
    expect(banner).toHaveTextContent("Đối tác Shopee");
    expect(banner).toHaveTextContent("Hết hạn 13/11/2026");
  });

  it("no connect entry: the no-shop strip and the header's connect item are gone", async () => {
    const state = { status: "ready", token: "t", shop: { id: "alias-1", name: "Shop TikTok (ẩn danh)" }, envelope: { report: { shop_name: "Shop TikTok (ẩn danh)" }, built_at: null } };
    const { rerender } = render(
      <StaticReviewerProvider reviewer={REVIEWER}>
        <NoShopSampleStrip />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <ShopHeader googleHref="x" onRefreshDemo={vi.fn()} onSignOut={vi.fn()} reviewer state={state as any} />
      </StaticReviewerProvider>,
    );
    expect(screen.queryByTestId("no-shop-sample-strip")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Menu shop/ }));
    expect(screen.queryByText("Đổi shop")).toBeNull();
    expect(screen.getByText("Đăng xuất")).toBeInTheDocument();
    rerender(
      <StaticReviewerProvider reviewer={null}>
        <NoShopSampleStrip />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <ShopHeader googleHref="x" onRefreshDemo={vi.fn()} onSignOut={vi.fn()} state={state as any} />
      </StaticReviewerProvider>,
    );
    expect(screen.getByTestId("no-shop-sample-strip")).toBeInTheDocument();
    expect(screen.getByText("Đổi shop")).toBeInTheDocument();
  });

  it("ReviewerProvider: a seller is no reviewer; an expired reviewer is signed out and sent to the password form", async () => {
    const fetchMe = vi.fn();
    const redirect = vi.fn();
    function Probe() {
      return <span data-testid="probe">{String(Boolean(window.localStorage.getItem(REVIEWER_STORAGE_KEY)))}</span>;
    }
    render(
      <ReviewerProvider fetchMe={fetchMe} redirect={redirect}>
        <Probe />
      </ReviewerProvider>,
    );
    expect(fetchMe).not.toHaveBeenCalled();
    cleanup();

    storeAuthSession({ accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
    storeReviewerRecord(REVIEWER);
    const denied = vi.fn().mockResolvedValue({ status: "denied", denial: "expired" });
    render(
      <ReviewerProvider fetchMe={denied} redirect={redirect}>
        <Probe />
      </ReviewerProvider>,
    );
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/auth/email?doi-tac=expired#doi-tac"));
    expect(readAuthSession()).toBeNull();
    expect(readReviewerRecord()).toBeNull();
  });

  it("ReviewerProvider: a pin added since sign-in (P64 sandbox) is stored as the active shop and the page reloads", async () => {
    storeAuthSession({ accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
    storeReviewerRecord({ ...REVIEWER, sample: true });
    const redirect = vi.fn();
    const pinned = vi.fn().mockResolvedValue({
      status: "reviewer",
      me: { reviewer: true, platform: "shopee", expiresAt: REVIEWER.expiresAt, shop: { id: "sbx-1", name: "SANDBOX_VN" }, mode: "sandbox", writesEnabled: true },
    });
    render(
      <ReviewerProvider fetchMe={pinned} redirect={redirect}>
        <span />
      </ReviewerProvider>,
    );
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/"));
    expect(readActiveShop()).toEqual({ id: "sbx-1", name: "SANDBOX_VN" });
    expect(readReviewerRecord()?.mode).toBe("sandbox");
    expect(readReviewerRecord()?.sample).not.toBe(true);

    // Already on the pinned shop: no reload loop.
    cleanup();
    redirect.mockClear();
    render(
      <ReviewerProvider fetchMe={pinned} redirect={redirect}>
        <span />
      </ReviewerProvider>,
    );
    await waitFor(() => expect(pinned).toHaveBeenCalledTimes(2));
    expect(redirect).not.toHaveBeenCalled();
  });
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

describe("Quyết định for a reviewer: simulated Duyệt → Thực thi", () => {
  it("the simulation panel walks Duyệt → Thực thi and shows the change that would be sent", async () => {
    const simulate = vi.fn(async (_id: string, step: "approve" | "execute") => (step === "approve" ? SIMULATION_APPROVE : SIMULATION_EXECUTE));
    const onClose = vi.fn();
    render(<ReviewerSimulation cardId="card-1" onClose={onClose} shopId="alias-1" simulate={simulate} token="t" />);
    const panel = screen.getByTestId("reviewer-simulation");
    expect(panel).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
    expect(await within(panel).findByText("Đã duyệt (mô phỏng)")).toBeInTheDocument();
    expect(simulate).toHaveBeenCalledWith("card-1", "approve");
    await userEvent.click(within(panel).getByRole("button", { name: "Thực thi (mô phỏng)" }));
    const change = await within(panel).findByTestId("reviewer-simulation-change");
    expect(simulate).toHaveBeenLastCalledWith("card-1", "execute");
    expect(change).toHaveTextContent("Juli soạn nội dung mới sau khi duyệt");
    // P41 (D47.7): no endpoint, method or operation name; the label is the only disclaimer.
    expect(panel).not.toHaveTextContent("/product/");
    expect(panel).not.toHaveTextContent("PUT");
    expect(panel).not.toHaveTextContent("update_product_listing");
    expect(panel).not.toHaveTextContent("Không có tác vụ nào được tạo");
    expect(change).toHaveTextContent(SIMULATION_EXECUTE.change.note!);
    expect(panel).toHaveTextContent("Sản phẩm 123");
    await userEvent.click(within(panel).getByRole("button", { name: "Đóng" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("a promotion lever: no TikTok request at all", async () => {
    const promo: SimulationResult = {
      ...SIMULATION_EXECUTE,
      change: { ...SIMULATION_EXECUTE.change, executor: "seller_center", lever: { code: "flash_sale", label: "Flash sale" }, request: null, fields: [] },
    };
    const simulate = vi.fn(async (_id: string, step: "approve" | "execute") => (step === "approve" ? SIMULATION_APPROVE : promo));
    render(<ReviewerSimulation cardId="card-1" onClose={vi.fn()} shopId="alias-1" simulate={simulate} token="t" />);
    await userEvent.click(await screen.findByRole("button", { name: "Thực thi (mô phỏng)" }));
    const change = await screen.findByTestId("reviewer-simulation-change");
    expect(change).toHaveTextContent("Nội dung mới do Juli soạn sau khi duyệt.");
    expect(change).not.toHaveTextContent("Không có lệnh ghi");
  });

  it("Duyệt on a card opens the simulation and never calls the real approve; other writes are read-only", async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      expect(url).toBe("/v1/reviewer/decisions/card-1/simulate");
      return new Response(JSON.stringify(SIMULATION_APPROVE), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchImpl);
    // The stability-band gate protects real writes; a simulation is not blocked by it.
    const c = qdClients({ fetchRules: vi.fn().mockResolvedValue(noBands()) });
    render(
      <StaticReviewerProvider reviewer={REVIEWER}>
        <SignedInQuyetDinh
          clients={c}
          onNavigate={vi.fn()}
          query={{ tab: "de-xuat", run: null, rulesOpen: false }}
          shop={{ id: "alias-1", name: "Shop TikTok (ẩn danh)" }}
          token="tok"
        />
      </StaticReviewerProvider>,
    );
    const card = await screen.findByTestId("recommendation-card");
    const reject = within(card).getByRole("button", { name: "Từ chối" });
    expect(reject).toBeDisabled();
    expect(reject).toHaveAttribute("title", REVIEWER_READ_ONLY_TITLE);
    const approve = within(card).getByRole("button", { name: "Duyệt" });
    expect(approve).toBeEnabled();
    await userEvent.click(approve);
    expect(await screen.findByTestId("reviewer-simulation")).toBeInTheDocument();
    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(c.approve).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("a seller's Quyết định is unchanged: the real approve runs", async () => {
    const c = qdClients();
    render(
      <SignedInQuyetDinh
        clients={c}
        onNavigate={vi.fn()}
        query={{ tab: "de-xuat", run: null, rulesOpen: false }}
        shop={{ id: "shop-1", name: "Shop" }}
        token="tok"
      />,
    );
    const card = await screen.findByTestId("recommendation-card");
    await userEvent.click(within(card).getByRole("button", { name: "Duyệt" }));
    await waitFor(() => expect(c.approve).toHaveBeenCalledWith("card-1", { token: "tok", shopId: "shop-1" }));
    expect(screen.queryByTestId("reviewer-simulation")).toBeNull();
  });
});
