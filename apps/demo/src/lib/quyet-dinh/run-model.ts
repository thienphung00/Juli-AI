/**
 * A run's phase, kind, status chip and five stage chips as the Đang thực
 * hiện artboards show them (`Run.dc.html`, `RunPhoto.dc.html`,
 * `RunManual.dc.html`, `Revert.dc.html`) — pure. Colours are the artboards'
 * hex values (`--qd-*` tokens in `quyet-dinh.css`), named by tone here.
 */

import type { AgentEvent } from "@juli/contracts";

import type { CardView } from "./card-model";
import type { QdRun } from "./p10-types";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../run-ledger/copy";
import { resolveRunTerminalState } from "../run-ledger/terminal-state";
import { SANDBOX_WRITTEN_LABEL, SIMULATED_RUN_LABEL } from "./simulated-copy";
import type { RunKind, RunTimeline } from "./timeline";

/** P66 (D15): Juli ended the run without proposing (`conclude_without_changes`). */
export const NO_PROPOSAL_STOP_REASON = "concluded_without_changes";
export const NO_PROPOSAL_LABEL = "Không đề xuất";

export type ChipTone = "wait" | "info" | "ok" | "muted" | "warn" | "queue";

export type RunPhase =
  | "queued"
  | "analysing"
  | "photo"
  | "checking"
  | "consent"
  | "guide"
  | "verify"
  | "writing"
  | "review"
  | "running"
  | "done"
  | "declined"
  | "conflict"
  | "ended";

const PHOTO_TOOLS = new Set(["upload_product_image"]);
/** P66 (D20-D22): the tools only a "Tạo sản phẩm" / "Tạo khuyến mãi" run calls. */
const CREATE_TOOLS = new Set(["get_category_candidates", "check_listing_requirements", "create_product"]);
const PROMOTION_TOOLS = new Set(["get_promotion_candidates", "check_promotion_eligibility", "create_product_discount"]);

/** The tool an event names, if any. */
function eventTool(event: AgentEvent): string | null {
  if (event.event_type === "tool.started" || event.event_type === "tool.completed" || event.event_type === "workflow.approval_required") {
    return event.payload.tool_name;
  }
  return null;
}

/** P66 (D20-D22): the workflow the run itself carries, else the tools it called. Never the
 *  card alone -- after a reload the card may no longer be on the desk. */
function workflowKind(run: QdRun, events: readonly AgentEvent[]): RunKind | null {
  if (run.run_flow === "create") return "create";
  if (run.run_flow === "promotion") return "promotion";
  for (const event of events) {
    const tool = eventTool(event);
    if (tool && CREATE_TOOLS.has(tool)) return "create";
    if (tool && PROMOTION_TOOLS.has(tool)) return "promotion";
  }
  return null;
}

/** Which artboard a run follows: from its awaiting state, the card it came from, or its tools. */
export function runKind(run: QdRun, card: CardView | null, events: readonly AgentEvent[], isRevert: boolean): RunKind {
  if (isRevert) return "revert";
  const workflow = workflowKind(run, events);
  if (workflow) return workflow;
  if (card?.leverCode === "create_product") return "create";
  if (card?.leverCode === "create_promotion") return "promotion";
  if (run.awaiting === "content_choice" || run.awaiting === "content_publish") return "content";
  if (card?.executor === "juli_drafts" || card?.content) return "content";
  if (run.awaiting === "photo") return "photo";
  if (run.awaiting === "seller_action") return "manual";
  if (card?.executor === "juli_with_photo") return "photo";
  if (card?.executor === "seller_center") return "manual";
  for (const event of events) {
    if (event.event_type === "tool.started" && PHOTO_TOOLS.has(event.payload.tool_name)) return "photo";
    if (event.event_type === "workflow.status" && /^Đang chờ ảnh/.test(event.payload.phase_narration)) return "photo";
  }
  return "listing";
}

/** The run statuses that are not over yet; every other status is terminal. */
const LIVE_RUN_STATUSES = new Set(["queued", "running", "waiting_approval", "waiting_external"]);

export function isTerminalRun(run: Pick<QdRun, "status">): boolean {
  return !LIVE_RUN_STATUSES.has(run.status);
}

/** A run that ended without success whose event stream shows no terminal event (not
 * loaded yet, or reaped / cancelled before it emitted one): its phase from the polled
 * status. A completed run still waits for its events (the done panel needs its writes). */
function terminalPhaseFromStatus(run: QdRun): RunPhase | null {
  if (run.status === "completed") return null;
  const stop = run.stop_reason;
  if (stop === "confirmation_declined" || stop === "cancelled_by_seller") return "declined";
  if (stop === "concurrency_conflict") return "conflict";
  return "ended";
}

/** The run's events show it was picked up: a tool ran or a consent is waiting. */
function runStarted(timeline: RunTimeline): boolean {
  return (
    timeline.pendingConsent !== null ||
    timeline.runningTool !== null ||
    timeline.steps.some((step) => (step.kind === "tool" || step.kind === "consent") && step.status === "done")
  );
}

export function runPhase(
  run: QdRun,
  kind: RunKind,
  timeline: RunTimeline,
  local: { readonly appliedPosted?: boolean; readonly declined?: boolean } = {},
): RunPhase {
  const terminal = timeline.terminal;
  // P70 (run ceec586e): a write TikTok confirmed stays the run's outcome whatever a later
  // step did -- a run that wrote is never "Không thay đổi" / "Không có gì được ghi".
  const wroteFirst = timeline.wrote && kind !== "manual" && kind !== "revert";
  if (terminal) {
    const stop = terminal.stopReason;
    if (wroteFirst && terminal.kind === "completed") return "done";
    if (stop === "confirmation_declined" || stop === "cancelled_by_seller") return "declined";
    if (stop === "concurrency_conflict") return "conflict";
    if (terminal.kind === "completed" && (timeline.wrote || kind === "manual" || kind === "revert")) return "done";
    return "ended";
  }
  // Never "Đang chạy" for a run the server already ended (e.g. reaped as worker_lost).
  const ended = isTerminalRun(run) ? terminalPhaseFromStatus(run) : null;
  if (ended) return ended;
  // The seller declined a later proposal: the resume is on its way, the write stands.
  if (local.declined) return wroteFirst ? "running" : "declined";
  // P41: a polled list row can still say `queued` after the run's events moved
  // on (a consent is up, a tool ran) — the events win, so the chip never says
  // "Trong hàng đợi" next to "Xác nhận một lần — Đang chờ bạn".
  if (run.status === "queued" && !runStarted(timeline)) return "queued";
  if (run.awaiting === "photo") return "photo";
  if (run.awaiting === "seller_action") return local.appliedPosted ? "verify" : "guide";
  if (timeline.pendingConsent) return "consent";
  if (kind === "manual" && (local.appliedPosted || timeline.toolsAfterPause > 0)) return "verify";
  const tool = timeline.runningTool;
  if (tool === "update_product_listing" || tool === "upload_product_image" || tool === "update_product_price" || tool === "create_product" || tool === "create_product_discount") return "writing";
  if (tool === "check_product_status") return "review";
  const consentDone = timeline.steps.some((step) => step.kind === "consent" && step.status === "done");
  if (consentDone) return "writing";
  if (kind === "photo" && timeline.steps.some((step) => step.key === "photo-check" && step.status === "current")) return "checking";
  if (run.status === "waiting_approval") return "consent";
  return "analysing";
}

export interface Chip {
  readonly label: string;
  readonly tone: ChipTone;
}

/**
 * A finished run's chip. P61-B: a run that wrote to the test shop is "Đã chạy thử" for a
 * seller; P64 (D73.4): on the reviewer's live sandbox shop (`sandboxShop`) that write is
 * the real change, "Đã ghi lên TikTok".
 */
function appliedChip(run: QdRun, sandboxShop: boolean): Chip {
  if (!run.simulated) return { label: "Đã áp dụng", tone: "ok" };
  return sandboxShop ? { label: SANDBOX_WRITTEN_LABEL, tone: "ok" } : { label: SIMULATED_RUN_LABEL, tone: "muted" };
}

/** The run's status chip (header and queue). `sandboxShop`: the reviewer's live sandbox (P64). */
export function runChip(run: QdRun, kind: RunKind, phase: RunPhase, sandboxShop = false): Chip {
  switch (phase) {
    case "queued":
      return { label: "Trong hàng đợi", tone: "queue" };
    case "photo":
    case "consent":
    case "guide":
      return { label: "Đang chờ bạn", tone: "wait" };
    case "verify":
      return { label: "Đang kiểm tra", tone: "info" };
    case "analysing":
    case "checking":
    case "writing":
    case "review":
    case "running":
      return { label: "Đang chạy", tone: "info" };
    case "done":
      if (kind === "revert") return { label: "Đã hoàn tác", tone: "muted" };
      // P64 (D73.3): the new listing exists on TikTok (the sandbox shop is the shop).
      if (kind === "create") return { label: "Đã tạo sản phẩm", tone: "ok" };
      // P65 (D74): the discount exists on TikTok (TikTok read it back).
      if (kind === "promotion") return { label: "Đã tạo khuyến mãi", tone: "ok" };
      // P61-B: the writes went to the test shop, not the seller's shop.
      return appliedChip(run, sandboxShop);
    case "declined":
      // The seller stopped the run ("Không thực hiện" on a wait / cancel): the ledger's "Đã hủy".
      if (run.stop_reason === "cancelled_by_seller") return { label: RUN_TERMINAL_STATE_COPY.cancelled.label, tone: "muted" };
      if (kind === "manual") return { label: "Không áp dụng", tone: "muted" };
      if (kind === "revert") return { label: "Không hoàn tác", tone: "muted" };
      return { label: "Không thay đổi", tone: "muted" };
    case "conflict":
      return { label: "Dừng · có thay đổi ngoài Juli", tone: "warn" };
    case "ended": {
      if (run.stop_reason === NO_PROPOSAL_STOP_REASON) return { label: NO_PROPOSAL_LABEL, tone: "muted" };
      const key = resolveRunTerminalState(run.stop_reason);
      return { label: (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).label, tone: "muted" };
    }
  }
}

/** The run's chip from the list item alone (queue rows of runs not open). */
export function listChip(run: QdRun, sandboxShop = false): Chip {
  if (run.status === "queued") return { label: "Trong hàng đợi", tone: "queue" };
  if (run.status === "waiting_approval" || run.awaiting) return { label: "Đang chờ bạn", tone: "wait" };
  if (run.status === "running" || run.status === "waiting_external") return { label: "Đang chạy", tone: "info" };
  // P70: a run that declined a later proposal after its write still wrote (below).
  const wroteThenDeclined = run.stop_reason === "confirmation_declined" && Boolean(run.confirmed_write);
  if (run.stop_reason === "confirmation_declined" && !wroteThenDeclined) return { label: "Không thay đổi", tone: "muted" };
  if (run.stop_reason === "cancelled_by_seller") return { label: RUN_TERMINAL_STATE_COPY.cancelled.label, tone: "muted" };
  if (run.status === "completed" && (run.stop_reason === "final_response" || wroteThenDeclined)) {
    return appliedChip(run, sandboxShop);
  }
  if (run.stop_reason === NO_PROPOSAL_STOP_REASON) return { label: NO_PROPOSAL_LABEL, tone: "muted" };
  const key = resolveRunTerminalState(run.stop_reason);
  return { label: (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).label, tone: "muted" };
}

export type StageState = "done" | "cur" | "todo";
export const STAGE_NAMES = ["Phân tích", "Đề xuất", "Duyệt", "Thực thi", "Đo lường"] as const;

export function stageStates(phase: RunPhase): readonly StageState[] {
  switch (phase) {
    case "queued":
    case "analysing":
      return ["cur", "todo", "todo", "todo", "todo"];
    case "photo":
    case "checking":
    case "consent":
    case "guide":
      return ["done", "done", "cur", "todo", "todo"];
    case "verify":
    case "writing":
    case "review":
    case "running":
      return ["done", "done", "done", "cur", "todo"];
    case "done":
      return ["done", "done", "done", "done", "cur"];
    case "declined":
    case "conflict":
    case "ended":
      return ["done", "done", "done", "todo", "todo"];
  }
}

/** "✓ Phân tích" / "3 Duyệt". */
export function stageLabel(index: number, state: StageState): string {
  return `${state === "done" ? "✓" : String(index + 1)} ${STAGE_NAMES[index]}`;
}

/** Grey bar under the timeline while Juli works (artboards' "runningNote", without the demo button). */
export function runningNote(kind: RunKind, phase: RunPhase, narration: string | null): string | null {
  if (phase === "writing") {
    if (kind === "photo") return "Juli đang tải ảnh lên TikTok Shop…";
    if (kind === "revert") return "Juli đang ghi lại nội dung cũ…";
    // P66 (D21): each workflow says what it writes.
    if (kind === "create") return "Juli đang tạo sản phẩm trên TikTok…";
    if (kind === "promotion") return "Juli đang tạo khuyến mãi trên TikTok…";
    return "Juli đang ghi lên TikTok Shop…";
  }
  if (phase === "review") return "Đang chờ TikTok duyệt lại trang sản phẩm…";
  if (phase === "verify") return "Juli đang tìm khuyến mãi trên TikTok Shop để xác nhận…";
  if (phase === "analysing" || phase === "checking" || phase === "running") return narration;
  return null;
}
