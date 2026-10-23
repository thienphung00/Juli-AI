import { validateAgentEvent, type AgentEvent } from "@juli/contracts";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import { TERMINAL_STEP_LABEL } from "../../lib/quyet-dinh/copy";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { listChip, runChip, runPhase } from "../../lib/quyet-dinh/run-model";
import { SANDBOX_WRITTEN_LABEL } from "../../lib/quyet-dinh/simulated-copy";
import { buildRunTimeline, type RunKind } from "../../lib/quyet-dinh/timeline";
import { RunPanel, type RunPanelProps } from "../quyet-dinh/run-panel";
import { SellerViewProvider } from "../seller-view-context";

/**
 * P64 (live run 74aefd1a, 2026-10-23): TikTok refused the sandbox create with 12052217
 * ("all-region shops must use V2 categories"). The run must read as failed everywhere —
 * the step stopped with TikTok's reason, no "Đã ghi lên TikTok" chip (header or queue),
 * no "Đã ghi lên shop sandbox" result, and no "đặt lịch đo" / measurement dates.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => cleanup());

const RUN_ID = "33333333-3333-4333-8333-333333333333";

const REFUSAL =
  "Không thành công · TikTok từ chối tạo sản phẩm (mã lỗi 12052217): Invalid Parameter. Parameter " +
  "`category_version` is invalid because all-region shops must use V2 categories. Use V2 categories and retry.";

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-23T03:30:${String(seq).padStart(2, "0")}Z`,
    payload,
    v: 1,
  });
}

const PROPOSAL = {
  category_id: "605254",
  title: "Combo 2 bình giữ nhiệt inox 750ml",
  description: "Hai bình inox giữ nhiệt 750ml.",
  reason_vi: "Cùng danh mục bình nước với sản phẩm gốc.",
};

function events(tool: string, completed: boolean): AgentEvent[] {
  const list = [
    ev(1, "workflow.started", { workflow_key: "create_product", product_ref: "p", prompt_version: "create_product.v1" }),
    ev(2, "tool.started", { tool_call_id: "c1", tool_name: "get_category_candidates" }),
    ev(3, "tool.completed", { tool_call_id: "c1", tool_name: "get_category_candidates", ok: true, summary: "Đã lấy 4 danh mục" }),
    ev(4, "workflow.approval_required", {
      tool_call_id: "c3",
      tool_name: tool,
      proposed_change: PROPOSAL,
      expires_at: "2026-10-23T07:30:00Z",
      options: [{ option_id: "1", proposed_change: PROPOSAL, rationale: "Tạo sản phẩm mới", params_sha: "x" }],
    }),
    ev(5, "tool.started", { tool_call_id: "c3", tool_name: tool }),
  ];
  if (completed) list.push(ev(6, "tool.completed", { tool_call_id: "c3", tool_name: tool, ok: false, summary: REFUSAL }));
  list.push(ev(7, "workflow.failed", { status: "failed", stop_reason: "tool_error_unrecoverable" }));
  return list;
}

const RUN = {
  id: RUN_ID,
  status: "failed",
  stop_reason: "tool_error_unrecoverable",
  product_name: "Bình giữ nhiệt inox 750ml",
  created_at: "2026-10-23T03:30:00Z",
  completed_at: "2026-10-23T03:31:00Z",
  running_seconds_elapsed: 3,
  latest_narration: null,
  decision_summary: null,
  awaiting: null,
  simulated: true,
} as QdRun;

const CARD = { leverCode: "create_product", executor: "juli", title: "Bình giữ nhiệt inox 750ml", beforeAfter: [] } as unknown as CardView;

function props(list: readonly AgentEvent[], kind: RunKind, run: QdRun = RUN): RunPanelProps {
  const timeline = buildRunTimeline(list, { kind });
  const noop = vi.fn().mockResolvedValue(undefined);
  return {
    run,
    kind,
    phase: runPhase(run, kind, timeline),
    timeline,
    card: kind === "create" ? CARD : null,
    changes: null,
    nowMs: Date.parse("2026-10-23T03:32:00Z"),
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

describe("a write TikTok refused (12052217)", () => {
  it.each<RunKind>(["create", "listing"])("is a stopped step with TikTok's reason and no measurement (%s)", (kind) => {
    const timeline = buildRunTimeline(events("create_product", true), { kind });
    expect(timeline.wrote).toBe(false);
    expect(timeline.terminal?.kind).toBe("failed");
    expect(timeline.terminal?.day7).toBeNull();
    const write = timeline.steps.find((step) => step.label === "Tạo sản phẩm trên TikTok");
    expect(write?.status).toBe("failed");
    expect(write?.detail).toContain("12052217");
    expect(timeline.steps.some((step) => step.label === TERMINAL_STEP_LABEL)).toBe(false);
    expect(timeline.steps.some((step) => /Đo sơ bộ/.test(step.detail ?? ""))).toBe(false);
  });

  it.each<RunKind>(["create", "listing"])("never wears a written / applied chip (%s)", (kind) => {
    const p = props(events("create_product", true), kind);
    expect(p.phase).toBe("ended");
    for (const sandboxShop of [true, false]) {
      const chips = [runChip(p.run, kind, p.phase, sandboxShop), listChip(p.run, sandboxShop)];
      for (const chip of chips) {
        expect(chip.label).toBe("Thất bại");
        expect(chip.label).not.toBe(SANDBOX_WRITTEN_LABEL);
      }
    }
  });

  it.each<RunKind>(["create", "listing"])("shows the failure, not a result header, in the run panel (%s)", (kind) => {
    render(sandbox(<RunPanel {...props(events("create_product", true), kind)} />));
    expect(screen.queryByTestId("run-done")).toBeNull();
    expect(screen.queryByText(/Đã ghi lên/)).toBeNull();
    expect(screen.queryByText(/Đã tạo sản phẩm/)).toBeNull();
    expect(screen.queryByText(/đặt lịch đo/)).toBeNull();
    expect(screen.getByText(/mã lỗi 12052217/)).toBeInTheDocument();
    expect(screen.getAllByText("Thất bại").length).toBeGreaterThan(0);
  });

  it("a seller's listing edit that failed is never 'Đã áp dụng'", () => {
    const run = { ...RUN, simulated: false } as QdRun;
    const p = props(events("update_product_listing", true), "listing", run);
    expect(p.phase).toBe("ended");
    expect(runChip(run, "listing", p.phase).label).toBe("Thất bại");
    expect(listChip(run).label).toBe("Thất bại");
    expect(p.timeline.steps.find((step) => step.key === "write")?.status).toBe("failed");
  });

  it("a write that raised (never completed) is a stopped step, not 'Xong'", () => {
    const timeline = buildRunTimeline(events("create_product", false), { kind: "create" });
    expect(timeline.steps.find((step) => step.label === "Tạo sản phẩm trên TikTok")?.status).toBe("failed");
    expect(timeline.wrote).toBe(false);
  });
});
