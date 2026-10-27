import { validateAgentEvent, type AgentEvent, type WorkflowRunListItem } from "@juli/contracts";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { consentRows } from "../../lib/quyet-dinh/consent-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { listChip, runChip, runPhase } from "../../lib/quyet-dinh/run-model";
import { SANDBOX_WRITTEN_LABEL } from "../../lib/quyet-dinh/simulated-copy";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import { isConfirmedSandboxWrite } from "../quyet-dinh/do-luong-panel";
import { RunPanel, type RunPanelProps } from "../quyet-dinh/run-panel";
import { SellerViewProvider } from "../seller-view-context";

/**
 * P70 (run ceec586e, 2026-10-27, reviewer sandbox): the listing edit was confirmed and
 * written ("Ghi lên TikTok Shop · Xong", Seller Center showed the new title); a SECOND
 * "Xác nhận một lần" then came up with an empty panel, the seller declined it, and the
 * run read "Không thay đổi" / "Không có gì được ghi lên TikTok Shop" and was missing from
 * Đo lường. A run with a confirmed write never says nothing was written.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => cleanup());

const RUN_ID = "ceec586e-8455-4fec-940b-2d0825af1b2f";
const TITLE = "Nồi Lẩu Điện Mini 1.5L Có Nắp Kính Tay Cầm Tiện Dụng Nấu Lẩu Mì Súp";
const LISTING = { title: TITLE, description: "<p>Nồi lẩu điện mini 1.5L.</p>" };
const PRICE = { skus: [{ sku_ref: "sku-1", amount: "199000", currency: "VND" }] };

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-27T09:${String(10 + seq).padStart(2, "0")}:00Z`,
    payload,
    v: 1,
  });
}

function approval(seq: number, callId: string, tool: string, change: Record<string, unknown>): AgentEvent {
  return ev(seq, "workflow.approval_required", {
    tool_call_id: callId,
    tool_name: tool,
    proposed_change: change,
    expires_at: "2026-10-27T13:00:00Z",
    options: [{ option_id: "1", proposed_change: change, rationale: "", params_sha: "x" }],
  });
}

/** The stream as production recorded it, up to the second consent. */
function upToSecondConsent(): AgentEvent[] {
  return [
    ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "optimize_product.v3" }),
    ev(2, "tool.started", { tool_call_id: "c0", tool_name: "get_product_information" }),
    ev(3, "tool.completed", { tool_call_id: "c0", tool_name: "get_product_information", ok: true, summary: "Đã đọc sản phẩm" }),
    approval(4, "c1", "update_product_listing", LISTING),
    ev(5, "tool.started", { tool_call_id: "c1", tool_name: "update_product_listing" }),
    ev(6, "tool.completed", { tool_call_id: "c1", tool_name: "update_product_listing", ok: true, summary: "Đã cập nhật tiêu đề, mô tả" }),
    approval(7, "c2", "update_product_price", PRICE),
  ];
}

/** ...then the decline, as the pre-fix backend ended it (`confirmation_declined`). */
function declinedAfterWrite(stopReason = "confirmation_declined"): AgentEvent[] {
  return [
    ...upToSecondConsent(),
    ev(8, "tool.completed", { tool_call_id: "c2", tool_name: "update_product_price", ok: false, summary: "Bạn đã từ chối" }),
    ev(9, "workflow.completed", { stop_reason: stopReason }),
  ];
}

const RUN = {
  id: RUN_ID,
  status: "completed",
  stop_reason: "confirmation_declined",
  product_name: "Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng",
  created_at: "2026-10-27T09:09:00Z",
  completed_at: "2026-10-27T09:20:00Z",
  running_seconds_elapsed: 60,
  latest_narration: null,
  decision_summary: null,
  awaiting: null,
  simulated: true,
  confirmed_write: { kind: "listing_edit", tiktok_id: "1", confirmed_at: "2026-10-27T09:12:20Z", discount_pct: null, fields: ["title", "description"] },
} as unknown as QdRun;

function props(list: readonly AgentEvent[], run: QdRun = RUN, local: { declined?: boolean } = {}): RunPanelProps {
  const timeline = buildRunTimeline(list, { kind: "listing" });
  const noop = vi.fn().mockResolvedValue(undefined);
  return {
    run,
    kind: "listing",
    phase: runPhase(run, "listing", timeline, local),
    timeline,
    card: null,
    changes: null,
    nowMs: Date.parse("2026-10-27T09:21:00Z"),
    reconnecting: false,
    eventsLoaded: true,
    photoChecks: null,
    photoState: { busy: false, error: null } as unknown as RunPanelProps["photoState"],
    instructions: null,
    appliedState: { busy: false, error: null },
    revertConflict: null,
    revertError: null,
    revertBusy: false,
    measureHref: "/decisions?tab=do-luong",
    onOpenMeasure: vi.fn(),
    onConfirm: noop,
    onDecline: noop,
    onCancelRevert: noop,
    onUpload: noop,
    onApplied: noop,
    onRevert: vi.fn(),
  };
}

function sandbox(node: React.ReactNode) {
  return (
    <SellerViewProvider readOnly readOnlyTitle="chỉ xem" runActions>
      {node}
    </SellerViewProvider>
  );
}

describe("a run that wrote, then declined a later proposal (ceec586e)", () => {
  it.each(["confirmation_declined", "final_response"])("is a written run, never 'Không thay đổi' (%s)", (stop) => {
    const p = props(declinedAfterWrite(stop), { ...RUN, stop_reason: stop } as QdRun);
    expect(p.timeline.wrote).toBe(true);
    expect(p.phase).toBe("done");
    expect(runChip(p.run, "listing", p.phase, true).label).toBe(SANDBOX_WRITTEN_LABEL);
    expect(listChip(p.run, true).label).toBe(SANDBOX_WRITTEN_LABEL);
    const write = p.timeline.steps.find((step) => step.key === "write");
    expect(write?.status).toBe("done");
    expect(write?.detail).toBe("Đã cập nhật tiêu đề, mô tả");
  });

  it("the run panel never says nothing was written", () => {
    render(sandbox(<RunPanel {...props(declinedAfterWrite())} />));
    expect(screen.queryByText(/Không có gì được ghi/)).toBeNull();
    expect(screen.queryByText("Không thay đổi")).toBeNull();
    expect(screen.queryByText(/không thực hiện thay đổi/)).toBeNull();
  });

  it("right after the seller declines (before the resume's events) it is not 'declined' either", () => {
    const p = props(upToSecondConsent(), { ...RUN, status: "waiting_approval", stop_reason: null } as unknown as QdRun, {
      declined: true,
    });
    expect(p.phase).not.toBe("declined");
    render(sandbox(<RunPanel {...p} />));
    expect(screen.queryByText(/Không có gì được ghi/)).toBeNull();
  });

  it("is listed in Đo lường whatever a later step did", () => {
    for (const [status, stop_reason] of [
      ["completed", "confirmation_declined"],
      ["completed", "final_response"],
      ["cancelled", "confirmation_expired"],
    ]) {
      expect(isConfirmedSandboxWrite({ ...RUN, status, stop_reason } as unknown as WorkflowRunListItem)).toBe(true);
    }
    expect(isConfirmedSandboxWrite({ ...RUN, status: "waiting_approval" } as unknown as WorkflowRunListItem)).toBe(false);
    expect(isConfirmedSandboxWrite({ ...RUN, confirmed_write: null } as unknown as WorkflowRunListItem)).toBe(false);
  });

  it("a decline with no write before it is still 'Không thay đổi'", () => {
    const list = [
      ...upToSecondConsent().slice(0, 4),
      ev(5, "tool.completed", { tool_call_id: "c1", tool_name: "update_product_listing", ok: false, summary: "Bạn đã từ chối" }),
      ev(6, "workflow.completed", { stop_reason: "confirmation_declined" }),
    ];
    const run = { ...RUN, confirmed_write: null } as unknown as QdRun;
    const p = props(list, run);
    expect(p.phase).toBe("declined");
    expect(listChip(run, true).label).toBe("Không thay đổi");
  });
});

describe("a price proposal renders its diff", () => {
  it("shows one 'Giá' row per SKU instead of an empty panel", () => {
    const rows = consentRows(PRICE, { revert: false, productName: "Nồi lẩu", card: null });
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("Giá");
    expect(rows[0].after).toBe("199.000 ₫");
  });

  it("labels several SKUs apart", () => {
    const rows = consentRows(
      { skus: [{ sku_ref: "a", amount: "100000" }, { sku_ref: "b", amount: "120000" }] },
      { revert: false, productName: "Nồi lẩu", card: null },
    );
    expect(rows.map((row) => row.label)).toEqual(["Giá · SKU 1", "Giá · SKU 2"]);
  });
});
