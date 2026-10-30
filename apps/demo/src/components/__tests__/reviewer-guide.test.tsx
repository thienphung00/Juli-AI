import type { DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useGuideMark, ReviewerGuideProvider } from "../../lib/reviewer/guide-context";
import { GUIDE_STEPS, type GuideStepId } from "../../lib/reviewer/guide-copy";
import { GUIDE_STORAGE_PREFIX, readGuideState } from "../../lib/reviewer/guide-store";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import type { ReviewerRecord } from "../../lib/reviewer/session";
import type { SandboxShop } from "../../lib/reviewer/sandbox-client";
import { storeAuthSession } from "../../lib/supabase-auth";
import { SandboxConnectionCard } from "../reviewer/sandbox-connection-card";
import { ReviewerGuide } from "../reviewer/reviewer-guide";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients } from "../quyet-dinh/signed-in-quyet-dinh";
import type { P10DecisionItem } from "../../lib/quyet-dinh/p10-types";
import type { ShopRules } from "../../lib/quyet-dinh/types";

/**
 * P77: the partner reviewer guide -- shown to a reviewer only, open on the
 * first visit, collapsible to a pill, progress per user id in localStorage,
 * steps tick on their own and by hand.
 */

const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const MASKED: ReviewerRecord = { platform: "shopee", expiresAt: null, mode: "masked" };
const SANDBOX: ReviewerRecord = { platform: "shopee", expiresAt: null, mode: "sandbox", writesEnabled: true };

function jwt(sub: string): string {
  const b64 = (value: object) => btoa(JSON.stringify(value)).replace(/=+$/, "");
  return `${b64({ alg: "none" })}.${b64({ sub })}.sig`;
}
function signIn(sub = "user-1") {
  storeAuthSession({ accessToken: jwt(sub), refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
}
const KEY = (sub = "user-1") => GUIDE_STORAGE_PREFIX + sub;

function setNarrow(narrow: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: narrow,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

function app(reviewer: ReviewerRecord | null, children: React.ReactNode = null, onSwitch?: () => void) {
  return (
    <StaticReviewerProvider reviewer={reviewer}>
      <ReviewerGuideProvider>
        {children}
        <ReviewerGuide onSwitchToSandbox={onSwitch} />
      </ReviewerGuideProvider>
    </StaticReviewerProvider>
  );
}

function doneIds(): GuideStepId[] {
  return [...readGuideState("user-1").done];
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  nav.pathname = "/";
  setNarrow(false);
  signIn();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("visibility and persistence", () => {
  it("is not shown to a seller", () => {
    render(app(null));
    expect(screen.queryByTestId("reviewer-guide")).toBeNull();
    expect(screen.queryByTestId("guide-pill")).toBeNull();
  });

  it("is shown open to a reviewer on the first load, with 8 steps in 3 parts", () => {
    nav.pathname = "/settings";
    render(app(MASKED));
    const panel = screen.getByTestId("reviewer-guide");
    expect(within(panel).getByRole("heading", { name: /8 steps/ })).toBeInTheDocument();
    expect(within(panel).getAllByRole("button", { pressed: false })).toHaveLength(8);
    expect(within(panel).getByText("0 of 8 done")).toBeInTheDocument();
    expect(panel.textContent ?? "").not.toMatch(/demo/i);
  });

  it("collapses with the x button, shows the pill, and the pill reopens it", async () => {
    nav.pathname = "/settings";
    render(app(MASKED));
    await userEvent.click(screen.getByRole("button", { name: "Collapse the guide" }));
    expect(screen.queryByTestId("reviewer-guide")).toBeNull();
    const pill = screen.getByTestId("guide-pill");
    expect(pill).toHaveTextContent("Reviewer guide · 0/8");
    expect(pill).toHaveFocus();
    await userEvent.click(pill);
    expect(screen.getByTestId("reviewer-guide")).toBeInTheDocument();
  });

  it("Esc collapses the panel", async () => {
    nav.pathname = "/settings";
    render(app(MASKED));
    screen.getByRole("button", { name: "Collapse the guide" }).focus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByTestId("reviewer-guide")).toBeNull();
    expect(screen.getByTestId("guide-pill")).toBeInTheDocument();
  });

  it("keeps progress and the collapsed state per user id across a remount", async () => {
    nav.pathname = "/settings";
    const first = render(app(MASKED));
    await userEvent.click(screen.getByTestId("guide-step-propose"));
    await userEvent.click(screen.getByRole("button", { name: "Collapse the guide" }));
    first.unmount();
    render(app(MASKED));
    expect(screen.queryByTestId("reviewer-guide")).toBeNull();
    expect(screen.getByTestId("guide-pill")).toHaveTextContent("1/8");
    expect(JSON.parse(window.localStorage.getItem(KEY()) ?? "{}")).toEqual({ open: false, done: ["propose"] });
  });

  it("another user id starts fresh", () => {
    nav.pathname = "/settings";
    window.localStorage.setItem(KEY("user-1"), JSON.stringify({ open: false, done: ["home"] }));
    signIn("user-2");
    render(app(MASKED));
    expect(screen.getByTestId("reviewer-guide")).toBeInTheDocument();
    expect(screen.getByText("0 of 8 done")).toBeInTheDocument();
  });

  it("works when storage throws", async () => {
    nav.pathname = "/settings";
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    render(app(MASKED));
    await userEvent.click(screen.getByTestId("guide-step-analysis"));
    expect(screen.getByText("1 of 8 done")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Collapse the guide" }));
    expect(screen.getByTestId("guide-pill")).toHaveTextContent("1/8");
  });

  it("a manual tick toggles on and off (aria-pressed), and Start over clears all", async () => {
    nav.pathname = "/settings";
    render(app(MASKED));
    const step = screen.getByTestId("guide-step-sync");
    await userEvent.click(step);
    expect(step).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(step);
    expect(step).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(step);
    await userEvent.click(screen.getByTestId("guide-step-undo"));
    expect(screen.getByText("2 of 8 done")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(screen.getByText("0 of 8 done")).toBeInTheDocument();
    expect(doneIds()).toEqual([]);
  });
});

describe("CTA and links", () => {
  it("continues with the first open step and links to it", async () => {
    nav.pathname = "/settings";
    render(app(MASKED));
    expect(screen.getByTestId("guide-cta")).toHaveTextContent("Continue with step 1");
    expect(screen.getByTestId("guide-cta")).toHaveAttribute("href", "/");
    await userEvent.click(screen.getByTestId("guide-step-home"));
    expect(screen.getByTestId("guide-cta")).toHaveTextContent("Continue with step 2");
    expect(screen.getByTestId("guide-cta")).toHaveAttribute("href", "/analytics");
    expect(screen.getByRole("link", { name: "Quyết định › Đo lường" })).toHaveAttribute("href", "/decisions?tab=do-luong");
  });

  it("step 4 reuses the shop switch handler (link and CTA)", async () => {
    nav.pathname = "/settings";
    const onSwitch = vi.fn();
    render(app(MASKED, null, onSwitch));
    await userEvent.click(screen.getByTestId("guide-switch-shop"));
    expect(onSwitch).toHaveBeenCalledTimes(1);
    for (const id of ["home", "analysis", "propose"]) await userEvent.click(screen.getByTestId(`guide-step-${id}`));
    expect(screen.getByTestId("guide-cta")).toHaveTextContent("Continue with step 4");
    await userEvent.click(screen.getByTestId("guide-cta"));
    expect(onSwitch).toHaveBeenCalledTimes(2);
  });

  it("reads 'Done' when all 8 are done", () => {
    nav.pathname = "/settings";
    window.localStorage.setItem(KEY(), JSON.stringify({ open: true, done: GUIDE_STEPS.map((step) => step.id) }));
    render(app(MASKED));
    expect(screen.getByTestId("guide-cta")).toHaveTextContent("Done: you have seen read and write");
    expect(screen.getByText("8 of 8 done")).toBeInTheDocument();
  });
});

describe("auto-ticks", () => {
  it("visiting Trang chủ and Phân tích on the masked shop", () => {
    nav.pathname = "/";
    const view = render(app(MASKED));
    expect(doneIds()).toEqual(["home"]);
    nav.pathname = "/analytics";
    view.rerender(app(MASKED));
    expect(doneIds()).toEqual(["home", "analysis"]);
  });

  it("does not tick route visits on the sandbox shop", () => {
    nav.pathname = "/";
    render(app({ ...SANDBOX, shops: [] }));
    expect(doneIds()).not.toContain("home");
  });

  it("a sandbox-only account has no switch to make: step 4 ticks", () => {
    render(app(SANDBOX));
    expect(doneIds()).toContain("switch");
  });

  it("the shop switch marks step 4 (the mark a handler makes before reload)", () => {
    nav.pathname = "/settings";
    function Switcher() {
      const mark = useGuideMark();
      useEffect(() => mark("switch"), [mark]);
      return null;
    }
    render(app(MASKED, <Switcher />));
    expect(doneIds()).toEqual(["switch"]);
  });

  it("pressing Đồng bộ ngay on the connection card ticks step 5", async () => {
    nav.pathname = "/settings";
    const shop: SandboxShop = {
      shop: { id: "s", name: "Juli Sandbox", tiktok_shop_code: null, platform: "tiktok" },
      mode: "sandbox",
      writes_enabled: true,
      connection: { status: "active", capability: "write", authorized_at: null, last_refreshed_at: null, token_expires_at: null, scopes: [] },
      synced_at: null,
      sync_endpoints: [],
      sync_interval_seconds: 60,
    };
    const fetchShop = vi.fn().mockResolvedValue(shop);
    render(
      app(
        { ...SANDBOX, shops: [] },
        <SandboxConnectionCard fetchShop={fetchShop} sync={vi.fn().mockResolvedValue({ status: "unavailable" })} token="t" />,
      ),
    );
    const button = await screen.findByRole("button", { name: "Đồng bộ ngay" });
    await act(async () => {
      button.click();
    });
    expect(doneIds()).toContain("sync");
  });
});

// -- Quyết định triggers ------------------------------------------------------------

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

function confirmedRun(): WorkflowRunListItem {
  return {
    id: "run-edit",
    status: "completed",
    stop_reason: "final_response",
    product_name: "Áo thun cotton",
    created_at: "2026-10-28T02:00:00Z",
    completed_at: "2026-10-28T02:10:00Z",
    running_seconds_elapsed: 60,
    latest_narration: null,
    decision_summary: null,
    awaiting: null,
    simulated: false,
    started_by_viewer: true,
    confirmed_write: {
      kind: "listing_edit",
      tiktok_id: "1736363193934775939",
      confirmed_at: "2026-10-28T02:09:00Z",
      discount_pct: null,
      fields: ["title"],
    },
  } as unknown as WorkflowRunListItem;
}

function qdClients(over: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([decision("card-1")] as unknown as DemoDecisionItem[]),
    approve: vi.fn().mockResolvedValue({ runId: "run-1" }),
    reject: vi.fn(),
    fetchRuns: vi.fn().mockResolvedValue([]),
    fetchRules: vi.fn().mockResolvedValue(rules()),
    fetchChanges: vi.fn().mockResolvedValue(null),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
    ...over,
  };
}

function qd(reviewer: ReviewerRecord, tab: "de-xuat" | "do-luong", clients: QdClients, extra?: { simulate?: boolean }) {
  return app(
    reviewer,
    <SignedInQuyetDinh
      clients={clients}
      onNavigate={vi.fn()}
      query={{ tab, run: null, rulesOpen: false }}
      shop={{ id: "shop-1", name: "Shop" }}
      token="tok"
      {...(extra?.simulate ? {} : {})}
    />,
  );
}

describe("auto-ticks inside Quyết định", () => {
  it("Đề xuất on the masked shop ticks step 3", async () => {
    nav.pathname = "/decisions";
    render(qd(MASKED, "de-xuat", qdClients()));
    await screen.findByTestId("recommendation-card");
    expect(doneIds()).toContain("propose");
  });

  it("Đề xuất on the sandbox shop does not", async () => {
    nav.pathname = "/decisions";
    render(qd({ ...SANDBOX, shops: [] }, "de-xuat", qdClients()));
    await screen.findByTestId("recommendation-card");
    expect(doneIds()).not.toContain("propose");
  });

  it("Đo lường on the sandbox shop ticks step 7; a confirmed write ticks step 6", async () => {
    nav.pathname = "/decisions";
    render(qd(SANDBOX, "do-luong", qdClients({ fetchRuns: vi.fn().mockResolvedValue([confirmedRun()]) })));
    await screen.findByTestId("measure-panel");
    expect(doneIds()).toEqual(expect.arrayContaining(["measure", "write"]));
  });

  it("no confirmed write, no step 6", async () => {
    nav.pathname = "/decisions";
    render(qd(SANDBOX, "do-luong", qdClients()));
    await waitFor(() => expect(doneIds()).toContain("measure"));
    expect(doneIds()).not.toContain("write");
  });

  it("starting a Hoàn tác ticks step 8", async () => {
    nav.pathname = "/decisions";
    const startRevert = vi.fn().mockResolvedValue({ runId: "run-revert" });
    render(qd(SANDBOX, "do-luong", qdClients({ fetchRuns: vi.fn().mockResolvedValue([confirmedRun()]), startRevert })));
    const panel = await screen.findByTestId("measure-panel");
    await userEvent.click(within(panel).getByRole("button", { name: "Hoàn tác" }));
    expect(doneIds()).not.toContain("undo");
    await userEvent.click(screen.getByRole("radio", { name: "Không hợp giọng thương hiệu" }));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu hoàn tác" }));
    expect(startRevert).toHaveBeenCalled();
    expect(doneIds()).toContain("undo");
  });
});

describe("phone layout", () => {
  it("renders a bottom sheet with Read / Write / Check tabs and the matching steps", async () => {
    nav.pathname = "/settings";
    setNarrow(true);
    render(app(MASKED));
    const sheet = await screen.findByRole("dialog", { name: /Read a real shop/ });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    for (const label of ["Read", "Write", "Check"]) expect(within(sheet).getByRole("button", { name: label })).toBeInTheDocument();
    expect(within(sheet).getByTestId("guide-step-home")).toBeInTheDocument();
    expect(within(sheet).queryByTestId("guide-step-sync")).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: "Write" }));
    expect(within(sheet).getByTestId("guide-step-sync")).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Check" }));
    expect(within(sheet).getByTestId("guide-step-undo")).toBeInTheDocument();
  });

  it("traps focus while open, and Esc closes to the pill", async () => {
    nav.pathname = "/settings";
    setNarrow(true);
    render(app(MASKED));
    const sheet = await screen.findByRole("dialog");
    expect(screen.getByRole("button", { name: "Close the guide" })).toHaveFocus();
    for (let i = 0; i < 20; i += 1) {
      await userEvent.tab();
      expect(sheet.contains(document.activeElement)).toBe(true);
    }
    await userEvent.tab({ shift: true });
    expect(sheet.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("guide-pill")).toBeInTheDocument();
  });
});
