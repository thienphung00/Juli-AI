/**
 * `RunViewState = reduce(events)` — the pure half of #1315 (ADR-076 decision 6).
 *
 * PURE BY CONSTRUCTION. No React, no fetch, no clock. A test asserts that over
 * this module's source, because the property is the point: replay and live are
 * the same code path only if the thing deriving the view cannot tell them
 * apart. Anything that reads the wall clock or the network can.
 *
 * The stage table below is PUI-DESIGN.md §2 transcribed field-for-field. Do not
 * derive it from the tool registry or the playbook — the design doc is the
 * source, and a test diffs this table against its own independently transcribed
 * copy so drift fails rather than silently re-defining the product.
 */

import type {
  AgentEvent,
  WorkflowApprovalRequiredPayload,
} from "@juli/contracts";

export const RUN_STAGE_IDS = [
  "phan-tich",
  "thong-tin-san-pham",
  "seo",
  "de-xuat",
  "cap-nhat",
  "hoan-tat",
] as const;

export type RunStageId = (typeof RUN_STAGE_IDS)[number];

/** PUI-DESIGN.md §2, one row per stage, in order. */
export const RUN_STAGE_LABELS: Readonly<Record<RunStageId, string>> = Object.freeze({
  "phan-tich": "Phân tích",
  "thong-tin-san-pham": "Thông tin sản phẩm",
  seo: "SEO",
  "de-xuat": "Đề xuất",
  "cap-nhat": "Cập nhật",
  "hoan-tat": "Hoàn tất",
});

/** Tool names that drive stages 2, 3 and 5. §2's "Driven by" column. */
const STAGE_TOOL_PREFIXES: readonly (readonly [RunStageId, readonly string[]])[] = [
  ["thong-tin-san-pham", ["get_product_information"]],
  ["seo", ["get_seo_keywords"]],
  ["cap-nhat", ["update_", "upload_"]],
];

export type RunStageStatus = "locked" | "active" | "frozen";

export interface RunStageState {
  readonly id: RunStageId;
  readonly label: string;
  readonly status: RunStageStatus;
  /** Sequence numbers of the events that drove this stage, in arrival order. */
  readonly eventSequences: readonly number[];
}

export interface RunDecisionRequest {
  readonly toolCallId: string;
  readonly toolName: string;
  readonly proposedChange: Record<string, unknown>;
  readonly expiresAt: string;
  readonly options: WorkflowApprovalRequiredPayload["options"];
}

export type RunTerminalKind = "completed" | "failed";

export interface RunTerminalState {
  readonly kind: RunTerminalKind;
  readonly stopReason: string;
}

export interface RunViewState {
  readonly stages: readonly RunStageState[];
  /** The furthest stage reached. Stages after it are locked. */
  readonly liveEdge: RunStageId;
  readonly currentStage: RunStageId;
  readonly decisionRequest?: RunDecisionRequest;
  readonly terminal?: RunTerminalState;
  /** Highest sequence number folded. The reconnect cursor. */
  readonly lastSequence: number;
  /** Assistant narration, in arrival order. Stage 1's content. */
  readonly narration: readonly string[];
}

function stageIndex(id: RunStageId): number {
  return RUN_STAGE_IDS.indexOf(id);
}

function toolStage(toolName: string): RunStageId | null {
  for (const [stage, prefixes] of STAGE_TOOL_PREFIXES) {
    for (const prefix of prefixes) {
      if (toolName === prefix || toolName.startsWith(prefix)) return stage;
    }
  }
  return null;
}

/** Which stage an event belongs to, or null when it drives no stage. */
export function stageForEvent(event: AgentEvent): RunStageId | null {
  switch (event.event_type) {
    case "workflow.started":
    case "assistant.text":
      return "phan-tich";
    case "tool.started":
    case "tool.completed":
      return toolStage(event.payload.tool_name);
    case "workflow.approval_required":
      return "de-xuat";
    case "workflow.completed":
    case "workflow.failed":
      return "hoan-tat";
    case "workflow.status":
      // Status carries no stage of its own -- it annotates whatever stage is
      // already live. Folding it into a stage would advance the live edge on a
      // heartbeat, which is not what §2's table says drives progression.
      return null;
  }
}

/**
 * Fold an event list into the view state.
 *
 * IDEMPOTENT AND ORDER-INSENSITIVE. Events are deduplicated by
 * `sequence_number` and folded in sequence order, so a duplicate frame, an
 * out-of-order arrival, and a replayed prefix after reconnect all produce the
 * same state. That is not defensive coding: `Last-Event-ID` reconnect
 * deliberately re-sends a prefix, so a reducer that is not idempotent corrupts
 * its own view every time the network blips.
 */
export function reduceRunView(events: readonly AgentEvent[]): RunViewState {
  const bySequence = new Map<number, AgentEvent>();
  for (const event of events) {
    if (!bySequence.has(event.sequence_number)) {
      bySequence.set(event.sequence_number, event);
    }
  }
  const ordered = [...bySequence.values()].sort(
    (a, b) => a.sequence_number - b.sequence_number,
  );

  const sequencesByStage = new Map<RunStageId, number[]>();
  const narration: string[] = [];
  let liveEdgeIndex = 0;
  let decisionRequest: RunDecisionRequest | undefined;
  let terminal: RunTerminalState | undefined;
  let lastSequence = 0;

  for (const event of ordered) {
    lastSequence = Math.max(lastSequence, event.sequence_number);

    if (event.event_type === "assistant.text") {
      narration.push(event.payload.text);
    }

    if (event.event_type === "workflow.approval_required") {
      decisionRequest = {
        toolCallId: event.payload.tool_call_id,
        toolName: event.payload.tool_name,
        proposedChange: event.payload.proposed_change,
        expiresAt: event.payload.expires_at,
        options: event.payload.options,
      };
    }

    if (event.event_type === "workflow.completed") {
      terminal = { kind: "completed", stopReason: event.payload.stop_reason };
      // The decision was answered; it is no longer outstanding.
      decisionRequest = undefined;
    }
    if (event.event_type === "workflow.failed") {
      terminal = { kind: "failed", stopReason: event.payload.stop_reason };
      decisionRequest = undefined;
    }

    const stage = stageForEvent(event);
    if (stage === null) continue;

    const existing = sequencesByStage.get(stage);
    if (existing) existing.push(event.sequence_number);
    else sequencesByStage.set(stage, [event.sequence_number]);

    liveEdgeIndex = Math.max(liveEdgeIndex, stageIndex(stage));
  }

  const liveEdge = RUN_STAGE_IDS[liveEdgeIndex];
  const stages: RunStageState[] = RUN_STAGE_IDS.map((id, index) => ({
    id,
    label: RUN_STAGE_LABELS[id],
    // Past stages freeze; the live edge is active; anything beyond is locked
    // and unreachable -- by click, by keyboard, or by URL (#1316 enforces the
    // last of those, but the state it reads is this one).
    status: index < liveEdgeIndex ? "frozen" : index === liveEdgeIndex ? "active" : "locked",
    eventSequences: Object.freeze([...(sequencesByStage.get(id) ?? [])]),
  }));

  return {
    stages: Object.freeze(stages),
    liveEdge,
    currentStage: liveEdge,
    decisionRequest,
    terminal,
    lastSequence,
    narration: Object.freeze([...narration]),
  };
}
