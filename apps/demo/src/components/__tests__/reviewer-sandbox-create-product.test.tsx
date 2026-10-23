import { validateAgentEvent, type AgentEvent } from "@juli/contracts";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { consentRows } from "../../lib/quyet-dinh/consent-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { runKind } from "../../lib/quyet-dinh/run-model";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import type { CardView } from "../../lib/quyet-dinh/card-model";
import { RunPanel, type RunPanelProps } from "../quyet-dinh/run-panel";
import { SellerViewProvider } from "../seller-view-context";

/**
 * P64 (D73.3 / D73.4): the sandbox reviewer's "Tạo sản phẩm" run in "Đang thực
 * hiện" — the seller's own run panel: the steps, the proposal ("Trước" is "—"),
 * the reviewer's confirm (enabled on the sandbox), and TikTok's read-back.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => cleanup());

const RUN_ID = "22222222-2222-4222-8222-222222222222";

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-22T03:30:${String(seq).padStart(2, "0")}Z`,
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

const PAUSED: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "create_product", product_ref: "p", prompt_version: "create_product.v1" }),
  ev(2, "tool.started", { tool_call_id: "c1", tool_name: "get_category_candidates" }),
  ev(3, "tool.completed", { tool_call_id: "c1", tool_name: "get_category_candidates", ok: true, summary: "Đã lấy 4 danh mục phù hợp từ TikTok" }),
  ev(4, "tool.started", { tool_call_id: "c2", tool_name: "check_listing_requirements" }),
  ev(5, "tool.completed", {
    tool_call_id: "c2",
    tool_name: "check_listing_requirements",
    ok: true,
    summary: "Danh mục Bình nước: đủ điều kiện đăng bán, 1 thuộc tính lấy từ sản phẩm gốc",
  }),
  ev(6, "workflow.approval_required", {
    tool_call_id: "c3",
    tool_name: "create_product",
    proposed_change: PROPOSAL,
    expires_at: "2026-10-22T07:30:00Z",
    options: [{ option_id: "1", proposed_change: PROPOSAL, rationale: "Tạo sản phẩm mới", params_sha: "x" }],
  }),
];

const READ_BACK = "Đã tạo sản phẩm trên TikTok · mã 1737000000000000001 · Đang chờ TikTok duyệt · TikTok xác nhận lúc 10:30 22/10/2026";

const DONE: AgentEvent[] = [
  ...PAUSED,
  ev(7, "tool.started", { tool_call_id: "c3", tool_name: "create_product" }),
  ev(8, "tool.completed", { tool_call_id: "c3", tool_name: "create_product", ok: true, summary: READ_BACK }),
  ev(9, "workflow.completed", { stop_reason: "final_response" }),
];

const CARD = { leverCode: "create_product", executor: "juli", title: "Bình giữ nhiệt inox 750ml", beforeAfter: [] } as unknown as CardView;

function props(events: readonly AgentEvent[], phase: RunPanelProps["phase"], status: string): RunPanelProps {
  const run = {
    id: RUN_ID,
    status,
    stop_reason: status === "completed" ? "final_response" : null,
    product_name: "Bình giữ nhiệt inox 750ml",
    created_at: "2026-10-22T03:30:00Z",
    completed_at: null,
    running_seconds_elapsed: 3,
    latest_narration: null,
    decision_summary: null,
    awaiting: null,
    simulated: true,
  } as QdRun;
  const noop = vi.fn().mockResolvedValue(undefined);
  return {
    run,
    kind: "create",
    phase,
    timeline: buildRunTimeline(events, { kind: "create" }),
    card: CARD,
    changes: null,
    nowMs: Date.parse("2026-10-22T03:31:00Z"),
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

describe("the create run", () => {
  it("is its own kind for a Tạo sản phẩm card", () => {
    expect(runKind(props(PAUSED, "consent", "waiting_approval").run, CARD, PAUSED, false)).toBe("create");
  });

  it("lists the create steps and the proposal with no 'before'", () => {
    const timeline = buildRunTimeline(PAUSED, { kind: "create" });
    expect(timeline.steps.map((step) => step.label)).toEqual([
      "Đọc sản phẩm gốc và danh mục TikTok",
      "Kiểm tra điều kiện đăng bán",
      "Xác nhận một lần",
      "Tạo sản phẩm trên TikTok",
      "Kết thúc",
    ]);
    expect(timeline.pendingConsent?.toolName).toBe("create_product");
    const rows = consentRows(PROPOSAL, { revert: false, productName: "Bình giữ nhiệt inox 750ml", card: CARD, create: true });
    expect(rows.map((row) => row.label)).toEqual(["Mã danh mục TikTok", "Tiêu đề", "Mô tả", "Lý do chọn danh mục"]);
    expect(rows.every((row) => row.before === null)).toBe(true);
  });

  it("lets the sandbox reviewer pick and confirm the proposal", async () => {
    const p = props(PAUSED, "consent", "waiting_approval");
    render(sandbox(<RunPanel {...p} />));
    // P66 (D19): the single proposal is selected by default.
    const option = screen.getByRole("button", { pressed: true, name: /Combo 2 bình giữ nhiệt/ });
    expect(option).toHaveTextContent("Lý do chọn danh mục");
    expect(option).toBeEnabled();
    const confirm = screen.getByRole("button", { name: "Xác nhận tạo sản phẩm" });
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(p.onConfirm).toHaveBeenCalled();
  });

  it("C6: the header is verb + the subject product, never the pre-labelled card title", () => {
    const p = props(PAUSED, "consent", "waiting_approval");
    const card = { ...CARD, title: "Tạo sản phẩm mới từ «Bình giữ nhiệt inox 750ml»" } as CardView;
    render(sandbox(<RunPanel {...p} card={card} />));
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Tạo sản phẩm · Bình giữ nhiệt inox 750ml$/);
    expect(screen.getByRole("heading", { level: 2 })).not.toHaveTextContent("từ");
  });

  it("keeps the confirm read-only outside the sandbox account", () => {
    render(
      <SellerViewProvider readOnly readOnlyTitle="chỉ xem">
        <RunPanel {...props(PAUSED, "consent", "waiting_approval")} />
      </SellerViewProvider>,
    );
    expect(screen.getByRole("button", { name: "Xác nhận tạo sản phẩm" })).toBeDisabled();
  });

  it("shows TikTok's read-back of the new product when done", () => {
    render(sandbox(<RunPanel {...props(DONE, "done", "completed")} />));
    expect(screen.getByTestId("run-done")).toHaveTextContent("Đã tạo sản phẩm trên TikTok");
    const readBack = screen.getByTestId("create-read-back");
    expect(readBack).toHaveTextContent("mã 1737000000000000001");
    expect(readBack).toHaveTextContent("Đang chờ TikTok duyệt");
    expect(readBack).toHaveTextContent("TikTok xác nhận lúc 10:30 22/10/2026");
    expect(screen.queryByText(/chạy thử/)).toBeNull();
  });
});
