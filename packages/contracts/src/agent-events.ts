/**
 * TypeScript mirror of the eight-event Pydantic union that is the emitting
 * source of truth for `workflow_run_events` (ADR-074 decision 2, #1125 /
 * AGT-W3B). Mirrors
 * `backend/src/juli_backend/services/agent/events/payloads.py` and
 * `envelope.py` field-for-field -- do not add, remove, or rename a field
 * here without a corresponding Pydantic change. `tests/unit/
 * test_agent_events_contract.py` proves both sides agree via shared golden
 * fixtures in `packages/contracts/fixtures/agent-events/`.
 *
 * `assistant.text.delta` (ADR-071) stays reserved: there is no payload
 * type, no envelope member, and no discriminant literal for it anywhere in
 * this module, on purpose -- `validateAgentEvent` rejects it by name.
 */

// ---------------------------------------------------------------------------
// Discriminant literals -- mirrors `envelope.py`'s `EVENT_TYPES` tuple.
// ---------------------------------------------------------------------------

export const AGENT_EVENT_TYPES = [
  "workflow.started",
  "workflow.status",
  "assistant.text",
  "tool.started",
  "tool.completed",
  "workflow.approval_required",
  "workflow.completed",
  "workflow.failed",
] as const;

export type AgentEventType = (typeof AGENT_EVENT_TYPES)[number];

// ---------------------------------------------------------------------------
// Shared enums -- mirrors `juli_backend.services.agent.runner.status`.
// ---------------------------------------------------------------------------

export const STOP_REASONS = [
  "final_response",
  "confirmation_declined",
  "paused_for_confirmation",
  "cancelled_by_seller",
  "confirmation_expired",
  "iteration_cap_exceeded",
  "wall_clock_timeout",
  "tool_error_unrecoverable",
  "llm_error",
  "concurrency_conflict",
  "output_validation_failed",
  "worker_lost",
] as const;

export type StopReason = (typeof STOP_REASONS)[number];

export const WORKFLOW_RUN_STATUSES = [
  "queued",
  "running",
  "waiting_approval",
  "completed",
  "cancelled",
  "timed_out",
  "failed",
] as const;

export type WorkflowRunStatus = (typeof WORKFLOW_RUN_STATUSES)[number];

/**
 * The failure-class `stop_reason -> status` mapping `workflow.failed` may
 * carry (ADR-073's total mapping). This is a *mirror* of the relevant
 * subset of `STOP_REASON_TO_STATUS` in
 * `backend/src/juli_backend/services/agent/runner/status.py` -- that module
 * stays the single authority for the precision (ADR-074 d.2); this table
 * must never drift from it.
 */
export const WORKFLOW_FAILED_STOP_REASON_TO_STATUS: Readonly<
  Record<
    Extract<
      StopReason,
      | "cancelled_by_seller"
      | "confirmation_expired"
      | "iteration_cap_exceeded"
      | "wall_clock_timeout"
      | "tool_error_unrecoverable"
      | "llm_error"
      | "concurrency_conflict"
      | "output_validation_failed"
      | "worker_lost"
    >,
    WorkflowRunStatus
  >
> = {
  cancelled_by_seller: "cancelled",
  confirmation_expired: "cancelled",
  iteration_cap_exceeded: "timed_out",
  wall_clock_timeout: "timed_out",
  tool_error_unrecoverable: "failed",
  llm_error: "failed",
  concurrency_conflict: "failed",
  output_validation_failed: "failed",
  worker_lost: "failed",
};

// ---------------------------------------------------------------------------
// Payload types -- one per event type, exact field parity with payloads.py.
// ---------------------------------------------------------------------------

export interface WorkflowStartedPayload {
  workflow_key: string;
  product_ref: string;
  prompt_version: string;
}

export interface WorkflowStatusPayload {
  phase_narration: string;
}

export interface AssistantTextPayload {
  text: string;
}

export interface ToolStartedPayload {
  tool_call_id: string;
  tool_name: string;
}

export interface ToolCompletedPayload {
  tool_call_id: string;
  tool_name: string;
  ok: boolean;
  summary: string;
}

export interface WorkflowApprovalRequiredPayload {
  tool_call_id: string;
  tool_name: string;
  proposed_change: Record<string, unknown>;
  expires_at: string;
}

export interface WorkflowCompletedPayload {
  stop_reason: StopReason;
}

export interface WorkflowFailedPayload {
  status: WorkflowRunStatus;
  stop_reason: StopReason;
}

// ---------------------------------------------------------------------------
// Envelope + discriminated union -- mirrors `envelope.py`'s
// `_EventEnvelope` + per-type subclasses + `WorkflowRunEvent`.
// ---------------------------------------------------------------------------

interface AgentEventEnvelopeBase {
  workflow_run_id: string;
  sequence_number: number;
  timestamp: string;
  /** Pinned to the literal `1` -- a missing or mismatched `v` is a build error. */
  v: 1;
}

export interface WorkflowStartedEvent extends AgentEventEnvelopeBase {
  event_type: "workflow.started";
  payload: WorkflowStartedPayload;
}

export interface WorkflowStatusEvent extends AgentEventEnvelopeBase {
  event_type: "workflow.status";
  payload: WorkflowStatusPayload;
}

export interface AssistantTextEvent extends AgentEventEnvelopeBase {
  event_type: "assistant.text";
  payload: AssistantTextPayload;
}

export interface ToolStartedEvent extends AgentEventEnvelopeBase {
  event_type: "tool.started";
  payload: ToolStartedPayload;
}

export interface ToolCompletedEvent extends AgentEventEnvelopeBase {
  event_type: "tool.completed";
  payload: ToolCompletedPayload;
}

export interface WorkflowApprovalRequiredEvent extends AgentEventEnvelopeBase {
  event_type: "workflow.approval_required";
  payload: WorkflowApprovalRequiredPayload;
}

export interface WorkflowCompletedEvent extends AgentEventEnvelopeBase {
  event_type: "workflow.completed";
  payload: WorkflowCompletedPayload;
}

export interface WorkflowFailedEvent extends AgentEventEnvelopeBase {
  event_type: "workflow.failed";
  payload: WorkflowFailedPayload;
}

/**
 * The discriminated union -- the complete, closed set of eight event types,
 * discriminated on `event_type`. `assistant.text.delta` has no member here
 * and never will in this slice (ADR-071 / ADR-074 d.2).
 */
export type AgentEvent =
  | WorkflowStartedEvent
  | WorkflowStatusEvent
  | AssistantTextEvent
  | ToolStartedEvent
  | ToolCompletedEvent
  | WorkflowApprovalRequiredEvent
  | WorkflowCompletedEvent
  | WorkflowFailedEvent;

// ---------------------------------------------------------------------------
// Exact payload field sets -- mirrors each Pydantic payload model's
// `model_fields`. Used by `validateAgentEvent` below and read directly by
// the Python-side dual-language contract test (via `node`) to diff both
// languages' field sets per type.
// ---------------------------------------------------------------------------

export const PAYLOAD_FIELDS: Readonly<Record<AgentEventType, readonly string[]>> = {
  "workflow.started": ["workflow_key", "product_ref", "prompt_version"],
  "workflow.status": ["phase_narration"],
  "assistant.text": ["text"],
  "tool.started": ["tool_call_id", "tool_name"],
  "tool.completed": ["tool_call_id", "tool_name", "ok", "summary"],
  "workflow.approval_required": [
    "tool_call_id",
    "tool_name",
    "proposed_change",
    "expires_at",
  ],
  "workflow.completed": ["stop_reason"],
  "workflow.failed": ["status", "stop_reason"],
};

/** Mirrors `_EventEnvelope`'s fields plus each subclass's `event_type`/`payload`. */
export const ENVELOPE_FIELDS = [
  "workflow_run_id",
  "sequence_number",
  "event_type",
  "timestamp",
  "payload",
  "v",
] as const;

// ---------------------------------------------------------------------------
// Runtime structural validator.
//
// `packages/contracts` has no schema-validation library -- ADR-074 d.2
// explicitly rejects adding one for this slice -- and TypeScript's own
// types vanish at runtime, so this hand-rolled check is the "runtime-
// validating helper" the dual-language contract test drives, from both
// languages, against the same golden fixtures.
//
// Mirrors the Pydantic side field-for-field: every envelope/payload field
// is required (no optionals), extra fields are rejected (`extra="forbid"`
// equivalent), and `workflow.failed`'s stop_reason/status cross-field rule
// mirrors payloads.py's `model_validator`. Throws `Error` naming the
// offending `event_type` on any violation -- callers (and the dual-
// language test) depend on that name to say which type drifted.
// ---------------------------------------------------------------------------

export function validateAgentEvent(value: unknown): AgentEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("agent event envelope must be a plain object");
  }
  const obj = value as Record<string, unknown>;

  const eventType = obj["event_type"];
  if (
    typeof eventType !== "string" ||
    !(AGENT_EVENT_TYPES as readonly string[]).includes(eventType)
  ) {
    throw new Error(
      `unknown event_type ${JSON.stringify(eventType)}: not one of the 8 members of ` +
        "AgentEvent (assistant.text.delta stays reserved/unimplemented -- ADR-071 / ADR-074 d.2)",
    );
  }
  const type = eventType as AgentEventType;

  assertExactKeys(obj, ENVELOPE_FIELDS, type, "envelope");

  if (typeof obj["workflow_run_id"] !== "string") {
    throw new Error(`${type}: workflow_run_id must be a string`);
  }
  if (typeof obj["sequence_number"] !== "number" || !Number.isInteger(obj["sequence_number"])) {
    throw new Error(`${type}: sequence_number must be an integer`);
  }
  if (typeof obj["timestamp"] !== "string") {
    throw new Error(`${type}: timestamp must be a string`);
  }
  if (obj["v"] !== 1) {
    throw new Error(`${type}: v must be the literal 1, got ${JSON.stringify(obj["v"])}`);
  }
  if (
    typeof obj["payload"] !== "object" ||
    obj["payload"] === null ||
    Array.isArray(obj["payload"])
  ) {
    throw new Error(`${type}: payload must be a plain object`);
  }
  const payload = obj["payload"] as Record<string, unknown>;
  assertExactKeys(payload, PAYLOAD_FIELDS[type], type, "payload");
  validatePayloadFields(type, payload);

  return obj as unknown as AgentEvent;
}

function assertExactKeys(
  obj: Record<string, unknown>,
  allowed: readonly string[],
  eventType: string,
  label: string,
): void {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(obj)) {
    if (!allowedSet.has(key)) {
      throw new Error(
        `${eventType}: unexpected field "${key}" in ${label} (extra fields are forbidden)`,
      );
    }
  }
  for (const key of allowed) {
    if (!(key in obj)) {
      throw new Error(`${eventType}: missing required field "${key}" in ${label}`);
    }
  }
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(
  payload: Record<string, unknown>,
  field: string,
  eventType: string,
): void {
  if (typeof payload[field] !== "string") {
    throw new Error(`${eventType}: payload.${field} must be a string`);
  }
}

function validatePayloadFields(type: AgentEventType, payload: Record<string, unknown>): void {
  switch (type) {
    case "workflow.started":
      requireString(payload, "workflow_key", type);
      requireString(payload, "product_ref", type);
      requireString(payload, "prompt_version", type);
      return;
    case "workflow.status":
      requireString(payload, "phase_narration", type);
      return;
    case "assistant.text":
      requireString(payload, "text", type);
      return;
    case "tool.started":
      requireString(payload, "tool_call_id", type);
      requireString(payload, "tool_name", type);
      return;
    case "tool.completed":
      requireString(payload, "tool_call_id", type);
      requireString(payload, "tool_name", type);
      if (!isBoolean(payload["ok"])) {
        throw new Error(`${type}: payload.ok must be a boolean`);
      }
      requireString(payload, "summary", type);
      return;
    case "workflow.approval_required":
      requireString(payload, "tool_call_id", type);
      requireString(payload, "tool_name", type);
      if (!isPlainObject(payload["proposed_change"])) {
        throw new Error(`${type}: payload.proposed_change must be an object`);
      }
      requireString(payload, "expires_at", type);
      return;
    case "workflow.completed": {
      const stopReason = payload["stop_reason"];
      if (
        typeof stopReason !== "string" ||
        !(STOP_REASONS as readonly string[]).includes(stopReason)
      ) {
        throw new Error(
          `${type}: payload.stop_reason ${JSON.stringify(stopReason)} is not a known StopReason`,
        );
      }
      return;
    }
    case "workflow.failed": {
      const stopReason = payload["stop_reason"];
      const status = payload["status"];
      if (
        typeof stopReason !== "string" ||
        !(stopReason in WORKFLOW_FAILED_STOP_REASON_TO_STATUS)
      ) {
        throw new Error(
          `${type}: payload.stop_reason ${JSON.stringify(stopReason)} is not a failure-class StopReason`,
        );
      }
      const expected =
        WORKFLOW_FAILED_STOP_REASON_TO_STATUS[
          stopReason as keyof typeof WORKFLOW_FAILED_STOP_REASON_TO_STATUS
        ];
      if (status !== expected) {
        throw new Error(
          `${type}: payload.status ${JSON.stringify(status)} does not match ADR-073's mapped ` +
            `status ${JSON.stringify(expected)} for stop_reason ${JSON.stringify(stopReason)}`,
        );
      }
      return;
    }
  }
}
