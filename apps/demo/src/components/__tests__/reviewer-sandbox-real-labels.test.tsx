import type { AgentEvent, DemoDecisionItem } from "@juli/contracts";
import { validateAgentEvent } from "@juli/contracts";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cardStatusLabel } from "../../lib/quyet-dinh/card-model";
import type { P10DecisionItem, QdRun } from "../../lib/quyet-dinh/p10-types";
import { listChip, runChip } from "../../lib/quyet-dinh/run-model";
import { SANDBOX_WRITTEN_LABEL, SIMULATED_RUN_LABEL } from "../../lib/quyet-dinh/simulated-copy";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { sampleEnvelope } from "../../lib/phan-tich/sample-data";
import { REVIEWER_SANDBOX_READ_ONLY_TITLE } from "../../lib/reviewer/copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import type { SandboxShop } from "../../lib/reviewer/sandbox-client";
import { ReviewerBanner } from "../app-shell/reviewer-banner";
import { HomeOverview } from "../home/home-overview";
import { SandboxConnectionCard } from "../reviewer/sandbox-connection-card";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients, type QdQuery } from "../quyet-dinh/signed-in-quyet-dinh";

/**
 * P64 integration (D73.4): the Shopee reviewer pinned to Juli's live TikTok sandbox shop
 * sees what really happened — the run wrote to the sandbox shop on TikTok — never a
 * "chạy thử" / "Mô phỏng" / sample label, on Quyết định, Đang thực hiện and Trang chủ.
 * And the reviewer can set the stability bands ("Đặt ngưỡng") Duyệt waits for.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const SANDBOX = { platform: "shopee", expiresAt: "2026-11-13T00:00:00Z", mode: "sandbox", writesEnabled: true } as const;
/** No simulation / dry-run / sample wording anywhere the sandbox reviewer looks. */
const SIMULATION_WORDS = /chạy thử|mô phỏng|mẫu|minh họa/i;

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function decision(id: string, status: string): P10DecisionItem {
  return {
    id,
    title: "Tối ưu Áo thun sandbox",
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
        as_of: "2026-10-21",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: { code: "card", label: "Hiển thị → Lượt nhấp" },
        lever: { code: "title", label: "Tiêu đề", action: "Viết lại tiêu đề" },
        main_kpi: { key: "ctr", label: "CTR", value: "1,2 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: 70_000,
        product_title: "Áo thun sandbox",
        tiktok_product_id: "1730000000000000001",
      },
      card: {
        seller_sku: "SBX-01",
        seller_sku_more: 0,
        product_title: "Áo thun sandbox",
        workflow_label: "Tối ưu sản phẩm",
        updated_at: new Date().toISOString(),
        status,
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

function rules(bands = true): ShopRules {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  return {
    stability_band: bands ? { ctr: { value: 3, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T00:00:00Z" } } : {},
    stability_band_defaults: { ctr: 4.5 },
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 },
    auto_levers: { ...unset, value: [] },
    protected_terms: { ...unset, value: [] },
    banned_terms: { ...unset, value: [] },
    content_tone: null,
    band_metrics: ["ctr"],
    listing_levers: ["title", "description"],
  } as unknown as ShopRules;
}

/** A finished run whose write landed on the sandbox merchant (`simulated: true`, P61-B). */
function sandboxRun(): QdRun {
  return {
    id: "run-1",
    status: "completed",
    stop_reason: "final_response",
    product_name: "Áo thun sandbox",
    created_at: "2026-10-22T02:00:00Z",
    completed_at: "2026-10-22T02:03:00Z",
    running_seconds_elapsed: 180,
    latest_narration: "Đã cập nhật tiêu đề trên TikTok Shop.",
    decision_summary: null,
    decision_id: "card-1",
    simulated: true,
  } as QdRun;
}

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: "run-1",
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-22T02:0${seq}:00Z`,
    payload,
    v: 1,
  });
}

const CHANGE = { title: "Áo thun cotton sandbox, form rộng" };
/** The seller's listing run as the worker emits it: confirm, then the TikTok write. */
const DONE_RUN: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "workflow.approval_required", {
    tool_call_id: "w1",
    tool_name: "update_product_listing",
    proposed_change: CHANGE,
    expires_at: "2099-10-09T07:00:00Z",
    options: [{ option_id: "opt-1", proposed_change: CHANGE, rationale: "Đủ ý", params_sha: "x" }],
  }),
  ev(3, "tool.started", { tool_call_id: "w1", tool_name: "update_product_listing" }),
  ev(4, "tool.completed", { tool_call_id: "w1", tool_name: "update_product_listing", ok: true, summary: "Đã cập nhật tiêu đề" }),
  ev(5, "workflow.completed", { stop_reason: "final_response" }),
];

function clients(over: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([decision("card-1", "simulated")] as unknown as DemoDecisionItem[]),
    approve: vi.fn().mockResolvedValue({ runId: "run-2" }),
    reject: vi.fn(),
    fetchRuns: vi.fn().mockResolvedValue([sandboxRun()]),
    fetchRules: vi.fn().mockResolvedValue(rules()),
    putRule: vi.fn().mockResolvedValue(undefined),
    deleteRule: vi.fn().mockResolvedValue(undefined),
    fetchChanges: vi.fn().mockResolvedValue({ run_id: "run-1", changes: [] }),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
    useRunEvents: () => ({ events: DONE_RUN, streamStatus: "closed" }),
    ...over,
  };
}

function renderQd(query: QdQuery, c: QdClients) {
  return render(
    <StaticReviewerProvider reviewer={SANDBOX}>
      <SignedInQuyetDinh clients={c} onNavigate={vi.fn()} query={query} shop={{ id: "shop-1", name: "Juli Sandbox" }} token="tok" />
    </StaticReviewerProvider>,
  );
}

describe("P64 — the sandbox reviewer is never told a run was simulated", () => {
  it("chips: a sandbox write is Đã ghi lên TikTok for the reviewer, Đã chạy thử for a seller", () => {
    const run = sandboxRun();
    expect(runChip(run, "listing", "done", true)).toEqual({ label: SANDBOX_WRITTEN_LABEL, tone: "ok" });
    expect(listChip(run, true).label).toBe(SANDBOX_WRITTEN_LABEL);
    expect(cardStatusLabel("simulated", true)).toBe(SANDBOX_WRITTEN_LABEL);
    // The seller's own shop is unchanged (P61-B).
    expect(runChip(run, "listing", "done").label).toBe(SIMULATED_RUN_LABEL);
    expect(listChip(run).label).toBe(SIMULATED_RUN_LABEL);
    expect(cardStatusLabel("simulated")).toBe(SIMULATED_RUN_LABEL);
    expect(SANDBOX_WRITTEN_LABEL).not.toMatch(SIMULATION_WORDS);
  });

  it("Quyết định: the completed card says Đã ghi lên TikTok, no simulation wording", async () => {
    renderQd({ tab: "de-xuat", run: null, rulesOpen: false }, clients());
    const card = await screen.findByTestId("recommendation-card");
    expect(within(card).getByTestId("card-status")).toHaveTextContent(SANDBOX_WRITTEN_LABEL);
    expect(document.body.textContent).not.toMatch(SIMULATION_WORDS);
  });

  it("Đang thực hiện: queue row, run header and result say the write landed on TikTok", async () => {
    renderQd({ tab: "dang-thuc-hien", run: "run-1", rulesOpen: false }, clients());
    const done = await screen.findByTestId("run-done");
    expect(done).toHaveTextContent("Đã ghi lên shop sandbox TikTok của Juli");
    const queue = screen.getByTestId("run-queue");
    await waitFor(() => expect(queue).toHaveTextContent(SANDBOX_WRITTEN_LABEL));
    expect(document.body.textContent).toContain(SANDBOX_WRITTEN_LABEL);
    expect(document.body.textContent).not.toMatch(SIMULATION_WORDS);
  });

  it("Trang chủ: banner, connection card and overview carry no simulation wording", async () => {
    const shop: SandboxShop = {
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
      synced_at: new Date().toISOString(),
      sync_endpoints: [],
      sync_interval_seconds: 60,
    };
    render(
      <StaticReviewerProvider reviewer={SANDBOX}>
        <ReviewerBanner onReset={vi.fn()} reviewer={SANDBOX} />
        <SandboxConnectionCard fetchShop={vi.fn().mockResolvedValue(shop)} sync={vi.fn()} token="t" />
        <HomeOverview envelope={sampleEnvelope()} />
      </StaticReviewerProvider>,
    );
    await screen.findByText("Juli Sandbox");
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent("thay đổi được ghi thật lên TikTok");
    expect(document.body.textContent).not.toMatch(SIMULATION_WORDS);
  });
});

describe("P64 — the sandbox reviewer sets the stability bands Duyệt waits for", () => {
  it("Đặt ngưỡng and Sửa quy tắc are enabled; Revert-style writes stay read-only", async () => {
    const c = clients({
      fetchDecisions: vi.fn().mockResolvedValue([decision("card-1", "pending")] as unknown as DemoDecisionItem[]),
      fetchRules: vi.fn().mockResolvedValue(rules(false)),
      fetchRuns: vi.fn().mockResolvedValue([]),
    });
    renderQd({ tab: "de-xuat", run: null, rulesOpen: false }, c);
    const card = await screen.findByTestId("recommendation-card");
    await waitFor(() => expect(within(card).getByRole("button", { name: "Duyệt" })).toBeDisabled());
    const stability = screen.getByTestId("stability-card");
    expect(within(stability).getByRole("button", { name: "Đặt ngưỡng" })).toBeEnabled();
    expect(within(screen.getByTestId("rules-chips")).getByRole("button", { name: "Sửa quy tắc" })).toBeEnabled();
    // Từ chối is not a rule: it stays read-only for the partner account.
    expect(within(card).getByRole("button", { name: "Từ chối" })).toHaveAttribute("title", REVIEWER_SANDBOX_READ_ONLY_TITLE);
  });

  it("the rules editor saves a band through the seller's own rule write", async () => {
    const c = clients({
      fetchDecisions: vi.fn().mockResolvedValue([decision("card-1", "pending")] as unknown as DemoDecisionItem[]),
      fetchRules: vi.fn().mockResolvedValue(rules(false)),
      fetchRuns: vi.fn().mockResolvedValue([]),
    });
    renderQd({ tab: "de-xuat", run: null, rulesOpen: true }, c);
    const editor = await screen.findByTestId("rules-editor");
    expect(editor).not.toHaveTextContent(SIMULATION_WORDS);
    const enabledSaves = within(editor)
      .getAllByRole("button")
      .filter((button) => !(button as HTMLButtonElement).disabled);
    expect(enabledSaves.length).toBeGreaterThan(0);
    for (const control of within(editor).queryAllByRole("button")) {
      expect(control).not.toHaveAttribute("data-read-only");
    }
    const user = userEvent.setup();
    const band = within(editor).getByTestId("rule-stability_band-ctr");
    const input = within(band).getByRole("textbox");
    await user.clear(input);
    await user.type(input, "5");
    await user.click(within(band).getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(c.putRule).toHaveBeenCalled());
    const [auth, ruleKey, value, , scopeRef] = vi.mocked(c.putRule).mock.calls[0];
    expect(auth).toEqual({ token: "tok", shopId: "shop-1" });
    expect([ruleKey, value, scopeRef]).toEqual(["stability_band", 5, "ctr"]);
  });
});
