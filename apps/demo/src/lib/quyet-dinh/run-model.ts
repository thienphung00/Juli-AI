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
import type { RunKind, RunTimeline } from "./timeline";

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

/** Which artboard a run follows: from its awaiting state, the card it came from, or its tools. */
export function runKind(run: QdRun, card: CardView | null, events: readonly AgentEvent[], isRevert: boolean): RunKind {
  if (isRevert) return "revert";
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

export function runPhase(
  run: QdRun,
  kind: RunKind,
  timeline: RunTimeline,
  local: { readonly appliedPosted?: boolean; readonly declined?: boolean } = {},
): RunPhase {
  const terminal = timeline.terminal;
  if (terminal) {
    const stop = terminal.stopReason;
    if (stop === "confirmation_declined" || stop === "cancelled_by_seller") return "declined";
    if (stop === "concurrency_conflict") return "conflict";
    if (terminal.kind === "completed" && (timeline.wrote || kind === "manual" || kind === "revert")) return "done";
    return "ended";
  }
  if (local.declined) return "declined";
  if (run.status === "queued") return "queued";
  if (run.awaiting === "photo") return "photo";
  if (run.awaiting === "seller_action") return local.appliedPosted ? "verify" : "guide";
  if (timeline.pendingConsent) return "consent";
  if (kind === "manual" && (local.appliedPosted || timeline.toolsAfterPause > 0)) return "verify";
  const tool = timeline.runningTool;
  if (tool === "update_product_listing" || tool === "upload_product_image" || tool === "update_product_price") return "writing";
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

/** The run's status chip (header and queue). */
export function runChip(run: QdRun, kind: RunKind, phase: RunPhase): Chip {
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
      return kind === "revert" ? { label: "Đã hoàn tác", tone: "muted" } : { label: "Đã áp dụng", tone: "ok" };
    case "declined":
      if (kind === "manual") return { label: "Không áp dụng", tone: "muted" };
      if (kind === "revert") return { label: "Không hoàn tác", tone: "muted" };
      return { label: "Không thay đổi", tone: "muted" };
    case "conflict":
      return { label: "Dừng · có thay đổi ngoài Juli", tone: "warn" };
    case "ended": {
      const key = resolveRunTerminalState(run.stop_reason);
      return { label: (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).label, tone: "muted" };
    }
  }
}

/** The run's chip from the list item alone (queue rows of runs not open). */
export function listChip(run: QdRun): Chip {
  if (run.status === "queued") return { label: "Trong hàng đợi", tone: "queue" };
  if (run.status === "waiting_approval" || run.awaiting) return { label: "Đang chờ bạn", tone: "wait" };
  if (run.status === "running" || run.status === "waiting_external") return { label: "Đang chạy", tone: "info" };
  if (run.stop_reason === "confirmation_declined" || run.stop_reason === "cancelled_by_seller") {
    return { label: "Không thay đổi", tone: "muted" };
  }
  if (run.status === "completed" && run.stop_reason === "final_response") return { label: "Đã áp dụng", tone: "ok" };
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
    return "Juli đang ghi lên TikTok Shop…";
  }
  if (phase === "review") return "Đang chờ TikTok duyệt lại trang sản phẩm…";
  if (phase === "verify") return "Juli đang tìm khuyến mãi trên TikTok Shop để xác nhận…";
  if (phase === "analysing" || phase === "checking" || phase === "running") return narration;
  return null;
}
