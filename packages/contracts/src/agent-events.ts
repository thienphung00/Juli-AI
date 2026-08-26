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
 * Two independent guards against drift, at two layers:
 *  - Interfaces (this module, e.g. `WorkflowStartedEvent`, `ToolCompletedPayload`)
 *    -- what a consumer actually imports and types against (#1132's client
 *    helper, future UI slices). TypeScript types are erased at runtime, so
 *    the guard here is `tsc` itself: `PAYLOAD_FIELDS`/`ENVELOPE_FIELDS` are
 *    *derived* from `GOLDEN_*_EVENT` constants -- fresh object literals
 *    assigned directly to their interface types -- so an interface field
 *    added, removed, or the envelope `v` literal changed, with nothing else
 *    touched, fails compilation (excess/missing-property checking) rather
 *    than silently landing. See the comment above `GOLDEN_AGENT_EVENTS`.
 *  - `validateAgentEvent`'s runtime checks -- what actually parses a wire
 *    payload. `tests/unit/test_agent_events_contract.py` proves this layer
 *    with fixtures (including two that exploit a real per-language runtime
 *    leniency difference, since interfaces vanish before this layer runs).
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
  // ADR-073 amendment (ADR-075 decision 2, #1224 review round 3): consent
  // binding refused a write because it no longer matched what the seller
  // consented to -- distinct in kind from `concurrency_conflict` (a stale
  // product snapshot), even though both are compare-before-write guards.
  "confirmation_diverged",
  "iteration_cap_exceeded",
  "wall_clock_timeout",
  "tool_error_unrecoverable",
  "llm_error",
  "concurrency_conflict",
  "output_validation_failed",
  "worker_lost",
  // Issue #1359 amendment: fail-closed resume when stored prompt version
  // is missing or unparseable (ADR-072 decision 4, ADR-075 decision 2).
  "prompt_version_unrecoverable",
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
      | "confirmation_diverged"
      | "iteration_cap_exceeded"
      | "wall_clock_timeout"
      | "tool_error_unrecoverable"
      | "llm_error"
      | "concurrency_conflict"
      | "output_validation_failed"
      | "worker_lost"
      | "prompt_version_unrecoverable"
    >,
    WorkflowRunStatus
  >
> = {
  cancelled_by_seller: "cancelled",
  confirmation_expired: "cancelled",
  confirmation_diverged: "failed",
  iteration_cap_exceeded: "timed_out",
  wall_clock_timeout: "timed_out",
  tool_error_unrecoverable: "failed",
  llm_error: "failed",
  concurrency_conflict: "failed",
  output_validation_failed: "failed",
  worker_lost: "failed",
  prompt_version_unrecoverable: "failed",
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

/**
 * One decision-request option (ADR-075 decision 2, issue #1221 / AGT-W5A)
 * -- mirrors `ConfirmationOptionPayload` in `payloads.py` field-for-field.
 * `proposed_change` is verbatim (the audit is what was shown); `params_sha`
 * is the SHA-256 canonical-JSON fingerprint `runner/confirmation.py`
 * defines (see that module's docstring for the exact canonicalization).
 */
export interface ConfirmationOptionPayload {
  option_id: string;
  proposed_change: Record<string, unknown>;
  rationale: string;
  params_sha: string;
}

export interface WorkflowApprovalRequiredPayload {
  tool_call_id: string;
  tool_name: string;
  proposed_change: Record<string, unknown>;
  expires_at: string;
  /**
   * Additive AND OPTIONAL (ADR-075 decision 2, issue #1221 / AGT-W5A) --
   * mirrors `payloads.py`'s `WorkflowApprovalRequiredPayload.options`
   * defaulting to `[]`. A `workflow_run_events` row written before this
   * issue shipped has no `options` key at all; `validateAgentEvent` below
   * (`OPTIONAL_PAYLOAD_FIELDS`) does not require it either, so replaying
   * that historical row still validates on this side too. Binary confirm
   * is the N=1 case for every *new* write: exactly one option, not a
   * structurally different shape from an eventual N>1 decision request.
   */
  options?: ConfirmationOptionPayload[];
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
// Canonical golden instances -- one per event type, each a *fresh object
// literal* assigned directly to its specific interface type.
//
// This is the interface-drift guard (Review's Option 1, #1126 follow-up):
// TypeScript performs excess-property and missing-property checking on a
// fresh object literal assigned to a named type, recursively into nested
// literals (`payload` included). That means:
//   - a field added to an interface only, with no matching literal update,
//     fails `tsc` with "Property '<x>' is missing" (the literal is now
//     short a required field);
//   - a field removed from an interface only, with the literal still
//     carrying it, fails `tsc` with "Object literal may only specify known
//     properties" (the literal now has an excess field);
//   - `v: 1` narrowed/widened to any other literal in the envelope base
//     fails `tsc` with "Type '1' is not assignable to type '<x>'" on every
//     one of these eight literals at once.
// `PAYLOAD_FIELDS`/`ENVELOPE_FIELDS` below are *derived* from these
// instances via `Object.keys` rather than hand-authored in parallel, so
// there is no second table for a field edit to forget -- the field lists
// literally cannot diverge from what these compiler-checked instances
// contain. Values are the same as the corresponding golden fixture JSON
// under `packages/contracts/fixtures/agent-events/` (asserted equal by
// `packages/contracts/src/__tests__/agent-events.test.ts`), so this is not
// a second, independently-drifting source of *values* -- only of *shape*,
// where `tsc` is the enforcement.
// ---------------------------------------------------------------------------

const GOLDEN_RUN_ID = "17c048f5-53e3-4ec7-9c3f-7a39a272d07a";

export const GOLDEN_WORKFLOW_STARTED_EVENT: WorkflowStartedEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 0,
  event_type: "workflow.started",
  timestamp: "2026-08-14T12:00:00Z",
  payload: {
    workflow_key: "optimize_product",
    product_ref: "prod-123",
    prompt_version: "optimize_product.v1",
  },
  v: 1,
};

export const GOLDEN_WORKFLOW_STATUS_EVENT: WorkflowStatusEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 1,
  event_type: "workflow.status",
  timestamp: "2026-08-14T12:00:01Z",
  payload: {
    phase_narration: "Đang xem lại nội dung sản phẩm...",
  },
  v: 1,
};

export const GOLDEN_ASSISTANT_TEXT_EVENT: AssistantTextEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 2,
  event_type: "assistant.text",
  timestamp: "2026-08-14T12:00:02Z",
  payload: {
    text: "Tôi đã lên kế hoạch tối ưu sản phẩm của bạn.",
  },
  v: 1,
};

export const GOLDEN_TOOL_STARTED_EVENT: ToolStartedEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 3,
  event_type: "tool.started",
  timestamp: "2026-08-14T12:00:03Z",
  payload: {
    tool_call_id: "call_1",
    tool_name: "update_price",
  },
  v: 1,
};

export const GOLDEN_TOOL_COMPLETED_EVENT: ToolCompletedEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 4,
  event_type: "tool.completed",
  timestamp: "2026-08-14T12:00:04Z",
  payload: {
    tool_call_id: "call_1",
    tool_name: "update_price",
    ok: true,
    summary: "Đã cập nhật giá thành công.",
  },
  v: 1,
};

export const GOLDEN_WORKFLOW_APPROVAL_REQUIRED_EVENT: WorkflowApprovalRequiredEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 5,
  event_type: "workflow.approval_required",
  timestamp: "2026-08-14T12:00:05Z",
  payload: {
    tool_call_id: "call_2",
    tool_name: "update_price",
    proposed_change: {
      price: { from: "199000", to: "179000" },
    },
    expires_at: "2026-08-14T16:00:05Z",
    options: [
      {
        option_id: "1",
        proposed_change: {
          price: { from: "199000", to: "179000" },
        },
        rationale: "Apply the new price to the bound product.",
        params_sha: "21e39b8b688d33711086e974731e227a9818c5da5abe137b16d35157777d5fb1",
      },
    ],
  },
  v: 1,
};

export const GOLDEN_WORKFLOW_COMPLETED_EVENT: WorkflowCompletedEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 6,
  event_type: "workflow.completed",
  timestamp: "2026-08-14T12:00:06Z",
  payload: {
    stop_reason: "final_response",
  },
  v: 1,
};

export const GOLDEN_WORKFLOW_FAILED_EVENT: WorkflowFailedEvent = {
  workflow_run_id: GOLDEN_RUN_ID,
  sequence_number: 7,
  event_type: "workflow.failed",
  timestamp: "2026-08-14T12:00:07Z",
  payload: {
    status: "failed",
    stop_reason: "llm_error",
  },
  v: 1,
};

/**
 * All eight canonical instances, keyed by discriminant. Built from the
 * already-typed constants above (not fresh literals), so this assignment
 * itself carries no additional excess/missing-property checking -- the
 * checking already happened where each constant was declared.
 */
export const GOLDEN_AGENT_EVENTS: Readonly<Record<AgentEventType, AgentEvent>> = {
  "workflow.started": GOLDEN_WORKFLOW_STARTED_EVENT,
  "workflow.status": GOLDEN_WORKFLOW_STATUS_EVENT,
  "assistant.text": GOLDEN_ASSISTANT_TEXT_EVENT,
  "tool.started": GOLDEN_TOOL_STARTED_EVENT,
  "tool.completed": GOLDEN_TOOL_COMPLETED_EVENT,
  "workflow.approval_required": GOLDEN_WORKFLOW_APPROVAL_REQUIRED_EVENT,
  "workflow.completed": GOLDEN_WORKFLOW_COMPLETED_EVENT,
  "workflow.failed": GOLDEN_WORKFLOW_FAILED_EVENT,
};

// ---------------------------------------------------------------------------
// Exact payload/envelope field sets -- *derived* from `GOLDEN_AGENT_EVENTS`
// via `Object.keys`, mirroring each Pydantic payload model's `model_fields`.
// Used by `validateAgentEvent` below and read directly by the Python-side
// dual-language contract test (via `node`) to diff both languages' field
// sets per type. See the comment above `GOLDEN_AGENT_EVENTS` for why these
// are computed rather than hand-authored in parallel.
// ---------------------------------------------------------------------------

export const PAYLOAD_FIELDS: Readonly<Record<AgentEventType, readonly string[]>> = Object.freeze(
  Object.fromEntries(
    (Object.keys(GOLDEN_AGENT_EVENTS) as AgentEventType[]).map((type) => [
      type,
      Object.freeze(Object.keys(GOLDEN_AGENT_EVENTS[type].payload)),
    ]),
  ),
) as Readonly<Record<AgentEventType, readonly string[]>>;

/** Mirrors `_EventEnvelope`'s fields plus each subclass's `event_type`/`payload`. */
export const ENVELOPE_FIELDS: readonly string[] = Object.freeze(
  Object.keys(GOLDEN_WORKFLOW_STARTED_EVENT),
);

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
  assertExactKeys(payload, PAYLOAD_FIELDS[type], type, "payload", OPTIONAL_PAYLOAD_FIELDS[type]);
  validatePayloadFields(type, payload);

  return obj as unknown as AgentEvent;
}

/**
 * Payload fields that may be *absent* entirely, keyed by event type --
 * still members of `PAYLOAD_FIELDS[type]` (so a present-and-valid value is
 * still checked by `validatePayloadFields`, and an excess/unknown field is
 * still rejected by `assertExactKeys`'s first loop), just not required to
 * be present. Currently exactly one entry: `workflow.approval_required
 * .options` (ADR-075 decision 2, issue #1221 / AGT-W5A) -- see that
 * payload's own interface doc comment for why. Every other event type's
 * field set stays fully required, matching `payloads.py`'s "every field
 * required" default.
 */
const OPTIONAL_PAYLOAD_FIELDS: Readonly<Partial<Record<AgentEventType, readonly string[]>>> = {
  "workflow.approval_required": ["options"],
};

function assertExactKeys(
  obj: Record<string, unknown>,
  allowed: readonly string[],
  eventType: string,
  label: string,
  optional: readonly string[] = [],
): void {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(obj)) {
    if (!allowedSet.has(key)) {
      throw new Error(
        `${eventType}: unexpected field "${key}" in ${label} (extra fields are forbidden)`,
      );
    }
  }
  const optionalSet = new Set(optional);
  for (const key of allowed) {
    if (optionalSet.has(key)) {
      continue;
    }
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

/** `options[]` validator for `workflow.approval_required` (ADR-075
 * decision 2, issue #1221 / AGT-W5A) -- each element required, extra keys
 * forbidden, mirroring `ConfirmationOptionPayload` field-for-field. */
function validateConfirmationOptions(eventType: AgentEventType, value: unknown): void {
  if (!Array.isArray(value)) {
    throw new Error(`${eventType}: payload.options must be an array`);
  }
  const allowed = ["option_id", "proposed_change", "rationale", "params_sha"] as const;
  value.forEach((option, index) => {
    if (!isPlainObject(option)) {
      throw new Error(`${eventType}: payload.options[${index}] must be an object`);
    }
    for (const key of Object.keys(option)) {
      if (!(allowed as readonly string[]).includes(key)) {
        throw new Error(
          `${eventType}: unexpected field "${key}" in payload.options[${index}] ` +
            "(extra fields are forbidden)",
        );
      }
    }
    for (const key of allowed) {
      if (!(key in option)) {
        throw new Error(`${eventType}: missing required field "${key}" in payload.options[${index}]`);
      }
    }
    if (typeof option["option_id"] !== "string") {
      throw new Error(`${eventType}: payload.options[${index}].option_id must be a string`);
    }
    if (!isPlainObject(option["proposed_change"])) {
      throw new Error(`${eventType}: payload.options[${index}].proposed_change must be an object`);
    }
    if (typeof option["rationale"] !== "string") {
      throw new Error(`${eventType}: payload.options[${index}].rationale must be a string`);
    }
    if (typeof option["params_sha"] !== "string") {
      throw new Error(`${eventType}: payload.options[${index}].params_sha must be a string`);
    }
  });
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
      // Optional (OPTIONAL_PAYLOAD_FIELDS): a pre-#1221 historical row has
      // no "options" key at all, and that must still validate -- only
      // check shape when the key is actually present.
      if (payload["options"] !== undefined) {
        validateConfirmationOptions(type, payload["options"]);
      }
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
