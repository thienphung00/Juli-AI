import { validateAgentEvent, type AgentEvent } from "@juli/contracts";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import { consentRows } from "../../lib/quyet-dinh/consent-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { runChip, runKind } from "../../lib/quyet-dinh/run-model";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import { RunPanel, type RunPanelProps } from "../quyet-dinh/run-panel";
import { SellerViewProvider } from "../seller-view-context";

/**
 * P65 (D74): the sandbox reviewer's "Tạo khuyến mãi" run in "Đang thực hiện" — the
 * steps, the proposal (no "Trước"), the reviewer's edit of the discount % / end date,
 * and TikTok's read-back with no ROI claim.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => cleanup());

const RUN_ID = "33333333-3333-4333-8333-333333333333";

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-23T03:00:${String(seq).padStart(2, "0")}Z`,
    payload,
    v: 1,
  });
}

const PROPOSAL = {
  product_ids: ["1736405947247986307"],
  discount_pct: 15,
  end_date: "2026-10-30",
  promotion_title: "Giảm giá bình giữ nhiệt",
  reason_vi: "Sản phẩm bán chạy, còn hàng, chưa có khuyến mãi.",
};

const PAUSED: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "create_promotion", product_ref: "p", prompt_version: "create_promotion.v1" }),
  ev(2, "tool.started", { tool_call_id: "c1", tool_name: "get_promotion_candidates" }),
  ev(3, "tool.completed", {
    tool_call_id: "c1",
    tool_name: "get_promotion_candidates",
    ok: true,
    summary: "Đã đọc 2 sản phẩm (2 còn hàng, đủ điều kiện), 0 khuyến mãi giá đang chạy hoặc sắp chạy",
  }),
  ev(4, "tool.started", { tool_call_id: "c2", tool_name: "check_promotion_eligibility" }),
  ev(5, "tool.completed", {
    tool_call_id: "c2",
    tool_name: "check_promotion_eligibility",
    ok: true,
    summary: "1 sản phẩm đủ điều kiện · giảm 15% đến 30/10/2026",
  }),
  ev(6, "workflow.approval_required", {
    tool_call_id: "c3",
    tool_name: "create_product_discount",
    proposed_change: PROPOSAL,
    expires_at: "2026-10-23T07:00:00Z",
    options: [{ option_id: "1", proposed_change: PROPOSAL, rationale: "Tạo khuyến mãi", params_sha: "x" }],
  }),
];

const READ_BACK =
  "Đã tạo khuyến mãi trên TikTok · mã 7660009586606409490 · Chưa bắt đầu · giảm 15% cho 1/1 sản phẩm đến 30/10/2026 · TikTok xác nhận lúc 10:00 23/10/2026";

const DONE: AgentEvent[] = [
  ...PAUSED,
  ev(7, "tool.started", { tool_call_id: "c3", tool_name: "create_product_discount" }),
  ev(8, "tool.completed", { tool_call_id: "c3", tool_name: "create_product_discount", ok: true, summary: READ_BACK }),
  ev(9, "workflow.completed", { stop_reason: "final_response" }),
];

const CARD = {
  leverCode: "create_promotion",
  executor: "juli",
  title: "Tạo khuyến mãi giảm giá cho «Bình giữ nhiệt inox 750ml»",
  beforeAfter: [],
} as unknown as CardView;

function props(events: readonly AgentEvent[], phase: RunPanelProps["phase"], status: string): RunPanelProps {
  const run = {
    id: RUN_ID,
    status,
    stop_reason: status === "completed" ? "final_response" : null,
    product_name: "Bình giữ nhiệt inox 750ml",
    created_at: "2026-10-23T03:00:00Z",
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
    kind: "promotion",
    phase,
    timeline: buildRunTimeline(events, { kind: "promotion" }),
    card: CARD,
    changes: null,
    nowMs: Date.parse("2026-10-23T03:01:00Z"),
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

describe("the promotion run", () => {
  it("is its own kind for a Tạo khuyến mãi card", () => {
    expect(runKind(props(PAUSED, "consent", "waiting_approval").run, CARD, PAUSED, false)).toBe("promotion");
  });

  it("lists the promotion steps and the proposal with no 'before'", () => {
    const timeline = buildRunTimeline(PAUSED, { kind: "promotion" });
    expect(timeline.steps.map((step) => step.label)).toEqual([
      "Đọc sản phẩm và khuyến mãi hiện có",
      "Kiểm tra điều kiện khuyến mãi",
      "Xác nhận một lần",
      "Tạo khuyến mãi trên TikTok",
      "Kết thúc",
    ]);
    expect(timeline.pendingConsent?.toolName).toBe("create_product_discount");
    const rows = consentRows(PROPOSAL, { revert: false, productName: "x", card: CARD, promotion: true });
    expect(rows.map((row) => [row.label, row.after])).toEqual([
      ["Tên khuyến mãi", "Giảm giá bình giữ nhiệt"],
      ["Mức giảm", "15%"],
      ["Ngày kết thúc", "30/10/2026"],
      ["Lý do", "Sản phẩm bán chạy, còn hàng, chưa có khuyến mãi."],
    ]);
    expect(rows.every((row) => row.before === null)).toBe(true);
  });

  it("shows the run header with the product", () => {
    render(sandbox(<RunPanel {...props(PAUSED, "consent", "waiting_approval")} />));
    expect(screen.getByText("Tạo khuyến mãi · Bình giữ nhiệt inox 750ml")).toBeInTheDocument();
  });

  it("lets the sandbox reviewer edit the discount and end date, then confirm", async () => {
    const p = props(PAUSED, "consent", "waiting_approval");
    render(sandbox(<RunPanel {...p} />));
    await userEvent.click(screen.getByRole("button", { name: "✎ Sửa mức giảm hoặc ngày kết thúc" }));
    const pct = screen.getByLabelText("Mức giảm (%)");
    await userEvent.clear(pct);
    await userEvent.type(pct, "20");
    fireEvent.change(screen.getByLabelText("Ngày kết thúc"), { target: { value: "2026-11-05" } });
    await userEvent.click(screen.getByRole("button", { name: "Lưu bản sửa" }));
    const option = screen.getByRole("button", { pressed: true });
    expect(option).toHaveTextContent("20%");
    expect(option).toHaveTextContent("05/11/2026");
    await userEvent.click(screen.getByRole("button", { name: "Xác nhận tạo khuyến mãi" }));
    expect(p.onConfirm).toHaveBeenCalledWith("c3", "1", { discount_pct: 20, end_date: "2026-11-05" });
  });

  it("refuses a non-number discount locally", async () => {
    const p = props(PAUSED, "consent", "waiting_approval");
    render(sandbox(<RunPanel {...p} />));
    await userEvent.click(screen.getByRole("button", { name: "✎ Sửa mức giảm hoặc ngày kết thúc" }));
    const pct = screen.getByLabelText("Mức giảm (%)");
    await userEvent.clear(pct);
    await userEvent.type(pct, "abc");
    await userEvent.click(screen.getByRole("button", { name: "Lưu bản sửa" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Mức giảm cần là số nguyên phần trăm.");
  });

  it("keeps the confirm read-only outside the sandbox account", () => {
    render(
      <SellerViewProvider readOnly readOnlyTitle="chỉ xem">
        <RunPanel {...props(PAUSED, "consent", "waiting_approval")} />
      </SellerViewProvider>,
    );
    expect(screen.getByRole("button", { name: "Xác nhận tạo khuyến mãi" })).toBeDisabled();
  });

  it("shows TikTok's read-back and says the sandbox measures no ROI", () => {
    const p = props(DONE, "done", "completed");
    render(sandbox(<RunPanel {...p} />));
    expect(screen.getByTestId("run-done")).toHaveTextContent("Đã tạo khuyến mãi trên TikTok");
    const readBack = screen.getByTestId("promotion-read-back");
    expect(readBack).toHaveTextContent("mã 7660009586606409490");
    expect(readBack).toHaveTextContent("TikTok xác nhận lúc 10:00 23/10/2026");
    expect(screen.getByTestId("promotion-no-roi")).toHaveTextContent(
      "Shop sandbox không có người mua thật nên Juli không đo doanh số hay hiệu quả (ROI) của khuyến mãi này.",
    );
    const done = screen.getByTestId("run-done").textContent ?? "";
    expect(done).not.toMatch(/tăng|dự báo|₫\/tháng|đặt lịch đo/);
    expect(screen.queryByText(/chạy thử/)).toBeNull();
    expect(runChip(p.run, "promotion", "done", true)).toEqual({ label: "Đã tạo khuyến mãi", tone: "ok" });
  });

  it("never reads as done when TikTok refused the create", () => {
    const refused: AgentEvent[] = [
      ...PAUSED,
      ev(7, "tool.started", { tool_call_id: "c3", tool_name: "create_product_discount" }),
      ev(8, "tool.completed", {
        tool_call_id: "c3",
        tool_name: "create_product_discount",
        ok: false,
        summary: "TikTok từ chối tạo khuyến mãi (mã lỗi 17019004): activity title duplicated",
      }),
      ev(9, "workflow.completed", { stop_reason: "final_response" }),
    ];
    expect(buildRunTimeline(refused, { kind: "promotion" }).wrote).toBe(false);
  });
});
