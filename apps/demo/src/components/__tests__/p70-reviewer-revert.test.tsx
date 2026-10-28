import { validateAgentEvent, type AgentEvent, type WorkflowRunListItem } from "@juli/contracts";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildRunTimeline, DECLINED_BY_SELLER_SUMMARY } from "../../lib/quyet-dinh/timeline";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import { DoLuongPanel, IDLE_REVERT, type MeasureItem } from "../quyet-dinh/do-luong-panel";
import { SellerViewProvider } from "../seller-view-context";

/**
 * P70 (owner, 2026-10-28):
 * 1. On Juli's live TikTok sandbox shop the partner account reverts ("Hoàn tác") a run it
 *    started, like a seller -- the API allows it there only (`SANDBOX_RUN_ENDPOINTS`).
 *    A run it did not start offers no Hoàn tác (P66); a read-only partner account
 *    (any other pin) keeps it disabled.
 * 2. A tool call the model proposed in its wrap-up turn after a decline is the runner talking
 *    to the model: no row, and never "The seller declined this change; …".
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => cleanup());

const SANDBOX = { platform: "shopee", expiresAt: "2099-11-13T00:00:00Z", mode: "sandbox", writesEnabled: true } as const;
const MASKED = { platform: "shopee", expiresAt: "2099-11-13T00:00:00Z", mode: "masked", writesEnabled: false } as const;

function sandboxRun(startedByViewer: boolean): WorkflowRunListItem {
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
    simulated: true,
    started_by_viewer: startedByViewer,
    confirmed_write: {
      kind: "listing_edit",
      tiktok_id: "1736363193934775939",
      confirmed_at: "2026-10-28T02:09:00Z",
      discount_pct: null,
      fields: ["title"],
    },
  } as unknown as WorkflowRunListItem;
}

function measureItem(startedByViewer: boolean): MeasureItem {
  return {
    run: sandboxRun(startedByViewer),
    card: null,
    changes: undefined,
    measurement: undefined,
    question: null,
    action: IDLE_REVERT,
  };
}

function panel(items: MeasureItem[], onRevert = vi.fn()) {
  return (
    <DoLuongPanel
      items={items}
      nowMs={null}
      onKeep={vi.fn()}
      onOpenProposals={vi.fn()}
      onOpenRun={vi.fn()}
      onRevert={onRevert}
      onTab={vi.fn()}
      proposalsHref="/d"
      tab="d0"
    />
  );
}

/** What `SignedInQuyetDinh` mounts for the sandbox reviewer. */
function sandboxReviewer(node: React.ReactNode) {
  return (
    <StaticReviewerProvider reviewer={SANDBOX}>
      <SellerViewProvider readOnly readOnlyTitle="chỉ xem" rulesActions runActions>
        {node}
      </SellerViewProvider>
    </StaticReviewerProvider>
  );
}

describe("P70 — Hoàn tác for the reviewer on the sandbox shop", () => {
  it("is enabled on a run the reviewer started, and opens the reason dialog", async () => {
    const onRevert = vi.fn();
    const item = measureItem(true);
    render(sandboxReviewer(panel([item], onRevert)));
    const button = within(screen.getByTestId("measure-panel")).getByRole("button", { name: "Hoàn tác" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("data-read-only");
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("radio", { name: "Không hợp giọng thương hiệu" }));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu hoàn tác" }));
    expect(onRevert).toHaveBeenCalledWith(item, { reason_code: "off_brand" });
  });

  it("is not offered on a run the reviewer did not start (P66)", () => {
    render(sandboxReviewer(panel([measureItem(false)])));
    expect(within(screen.getByTestId("measure-panel")).queryByRole("button", { name: "Hoàn tác" })).toBeNull();
  });

  it("stays disabled for the read-only partner account (not the sandbox pin)", () => {
    render(
      <StaticReviewerProvider reviewer={MASKED}>
        <SellerViewProvider readOnly readOnlyTitle="chỉ xem" simulateApprove>
          {panel([measureItem(true)])}
        </SellerViewProvider>
      </StaticReviewerProvider>,
    );
    const button = within(screen.getByTestId("measure-panel")).getByRole("button", { name: "Hoàn tác" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-read-only");
  });

  it("stays disabled in Juli Ops' read-only view-as", () => {
    render(<SellerViewProvider readOnly>{panel([measureItem(true)])}</SellerViewProvider>);
    expect(within(screen.getByTestId("measure-panel")).getByRole("button", { name: "Hoàn tác" })).toBeDisabled();
  });
});

// -- the decline wrap-up -------------------------------------------------------------

const RUN_ID = "7d3c3d1e-1d1f-4b0e-9a55-2a0c4f3e8b10";
const ENGLISH = "The seller declined this change; the run is wrapping up without dispatching any further tool calls.";

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-28T03:${String(10 + seq).padStart(2, "0")}:00Z`,
    payload,
    v: 1,
  });
}

const CHANGE = { title: "Áo thun cotton mới" };

function declined(wrapUp: AgentEvent[], declineSummary = DECLINED_BY_SELLER_SUMMARY): AgentEvent[] {
  return [
    ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "optimize_product.v3" }),
    ev(2, "tool.started", { tool_call_id: "c0", tool_name: "get_product_information" }),
    ev(3, "tool.completed", { tool_call_id: "c0", tool_name: "get_product_information", ok: true, summary: "Đã đọc sản phẩm" }),
    ev(4, "workflow.approval_required", {
      tool_call_id: "c1",
      tool_name: "update_product_listing",
      proposed_change: CHANGE,
      expires_at: "2026-10-28T07:00:00Z",
      options: [{ option_id: "1", proposed_change: CHANGE, rationale: "", params_sha: "x" }],
    }),
    ev(5, "tool.completed", { tool_call_id: "c1", tool_name: "update_product_listing", ok: false, summary: declineSummary }),
    ...wrapUp,
    ev(5 + wrapUp.length + 1, "workflow.completed", { stop_reason: "confirmation_declined" }),
  ];
}

function refused(summary: string): AgentEvent[] {
  return [
    ev(6, "tool.started", { tool_call_id: "c2", tool_name: "update_product_listing" }),
    ev(7, "tool.completed", { tool_call_id: "c2", tool_name: "update_product_listing", ok: false, summary }),
  ];
}

describe("P70 — the decline wrap-up shows no refusal row", () => {
  it.each([
    ["the pre-fix English summary", ENGLISH, DECLINED_BY_SELLER_SUMMARY],
    ["the Vietnamese summary", "Juli dừng lại theo lựa chọn của bạn.", DECLINED_BY_SELLER_SUMMARY],
    ["a decline summary in other words", ENGLISH, "Bạn đã từ chối"],
  ])("%s", (_label, summary, declineSummary) => {
    const plain = buildRunTimeline(declined([], declineSummary), { kind: "listing" });
    const withRefusal = buildRunTimeline(declined(refused(summary), declineSummary), { kind: "listing" });
    expect(withRefusal.steps).toEqual(plain.steps);
    const text = JSON.stringify(withRefusal.steps);
    expect(text).not.toContain("The seller declined");
    expect(text).not.toContain("wrapping up");
    expect(text).not.toContain(summary);
    expect(withRefusal.runningTool).toBeNull();
  });

  it("a failed write that is not a decline still shows its row", () => {
    const events = [
      ...declined([], "TikTok từ chối thay đổi").slice(0, 5),
      ev(6, "tool.started", { tool_call_id: "c3", tool_name: "check_product_status" }),
      ev(7, "tool.completed", { tool_call_id: "c3", tool_name: "check_product_status", ok: true, summary: "Đang hoạt động" }),
      ev(8, "workflow.completed", { stop_reason: "final_response" }),
    ];
    const timeline = buildRunTimeline(events, { kind: "listing" });
    expect(JSON.stringify(timeline.steps)).toContain("Đang hoạt động");
  });
});
