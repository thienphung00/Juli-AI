import { describe, expect, it } from "vitest";

import {
  AGENT_EVENT_TYPES,
  ENVELOPE_FIELDS,
  GOLDEN_AGENT_EVENTS,
  PAYLOAD_FIELDS,
  STOP_REASONS,
  validateAgentEvent,
  type AgentEvent,
} from "../agent-events";
// Also exercise the package-root re-export (ADR-074 d.2 acceptance criterion:
// index.ts must export every new type/value without reaching into
// agent-events.ts directly).
import {
  validateAgentEvent as validateAgentEventFromIndex,
  type AgentEvent as AgentEventFromIndex,
} from "../index";

import workflowStartedFixture from "../../fixtures/agent-events/workflow-started.json";
import workflowStatusFixture from "../../fixtures/agent-events/workflow-status.json";
import assistantTextFixture from "../../fixtures/agent-events/assistant-text.json";
import toolStartedFixture from "../../fixtures/agent-events/tool-started.json";
import toolCompletedFixture from "../../fixtures/agent-events/tool-completed.json";
import workflowApprovalRequiredFixture from "../../fixtures/agent-events/workflow-approval-required.json";
import workflowCompletedFixture from "../../fixtures/agent-events/workflow-completed.json";
import workflowFailedFixture from "../../fixtures/agent-events/workflow-failed.json";
import envelopeV1SnapshotFixture from "../../fixtures/agent-events/envelope-v1-snapshot.json";
import wrongEnvelopeVersionFixture from "../../fixtures/agent-events/invalid/wrong-envelope-version.json";
import assistantTextDeltaReservedFixture from "../../fixtures/agent-events/invalid/assistant-text-delta-reserved.json";
import pythonOnlyValidFixture from "../../fixtures/agent-events/invalid/python-only-valid-workflow-started.json";
import tsOnlyValidFixture from "../../fixtures/agent-events/invalid/ts-only-valid-tool-started.json";

const GOLDEN_FIXTURES: Array<[eventType: string, fixture: unknown]> = [
  ["workflow.started", workflowStartedFixture],
  ["workflow.status", workflowStatusFixture],
  ["assistant.text", assistantTextFixture],
  ["tool.started", toolStartedFixture],
  ["tool.completed", toolCompletedFixture],
  ["workflow.approval_required", workflowApprovalRequiredFixture],
  ["workflow.completed", workflowCompletedFixture],
  ["workflow.failed", workflowFailedFixture],
];

describe("AGENT_EVENT_TYPES", () => {
  it("names exactly the eight event types", () => {
    expect(AGENT_EVENT_TYPES).toHaveLength(8);
    expect(new Set(AGENT_EVENT_TYPES).size).toBe(8);
  });

  it("does not include the reserved assistant.text.delta", () => {
    expect(AGENT_EVENT_TYPES as readonly string[]).not.toContain("assistant.text.delta");
  });
});

describe("validateAgentEvent -- golden fixtures", () => {
  it.each(GOLDEN_FIXTURES)("accepts the %s golden fixture as-is", (eventType, fixture) => {
    const event = validateAgentEvent(fixture);
    expect(event.event_type).toBe(eventType);
    // Byte-equal-in-shape: the validator does not transform the input.
    expect(event).toEqual(fixture);
  });

  it("accepts the envelope-v1-snapshot fixture and pins v: 1", () => {
    const event = validateAgentEvent(envelopeV1SnapshotFixture);
    expect(event.v).toBe(1);
  });
});

describe("validateAgentEvent -- negative fixtures", () => {
  it("rejects a fixture with v !== 1", () => {
    expect(() => validateAgentEvent(wrongEnvelopeVersionFixture)).toThrow(/v must be the literal 1/);
  });

  it("rejects assistant.text.delta by name -- it is not a union member", () => {
    expect(() => validateAgentEvent(assistantTextDeltaReservedFixture)).toThrow(
      /assistant\.text\.delta/,
    );
  });

  it("rejects the Python-only-valid divergence fixture, naming workflow.started", () => {
    // sequence_number is a numeric *string* here -- Pydantic's lax int
    // coercion accepts it, but this hand-rolled TS validator requires a
    // real `number` (mirroring the AgentEvent field type), so it must fail
    // loudly and name the offending event type.
    expect(() => validateAgentEvent(pythonOnlyValidFixture)).toThrow(/^workflow\.started:/);
  });

  it("accepts the TS-only-valid divergence fixture (proves the asymmetry is real)", () => {
    // timestamp is a non-ISO string here -- Pydantic's `datetime` field
    // rejects it (proven on the Python side of the contract test), but this
    // validator only checks `typeof timestamp === "string"`, so it passes
    // here. The contract test proves the Python side rejects the exact same
    // fixture, naming tool.started.
    const event = validateAgentEvent(tsOnlyValidFixture);
    expect(event.event_type).toBe("tool.started");
  });
});

describe("GOLDEN_AGENT_EVENTS -- interface-drift guard (#1126 review follow-up)", () => {
  // Each GOLDEN_*_EVENT constant in agent-events.ts is a *fresh object
  // literal* assigned directly to its specific interface (e.g.
  // `WorkflowStartedEvent`), which makes `tsc` enforce, at compile time,
  // that the literal has exactly the interface's fields -- no more, no
  // less -- and that `v` is exactly `1`. `PAYLOAD_FIELDS`/`ENVELOPE_FIELDS`
  // are *derived* from these instances (see agent-events.ts), so this test
  // only needs to prove the two remaining things `tsc` alone can't: the
  // instances' *values* agree with the golden JSON fixtures both languages
  // parse, and the derived tables genuinely reflect the instances (not a
  // stale snapshot).
  it.each(GOLDEN_FIXTURES)("GOLDEN_AGENT_EVENTS[%s] equals the JSON fixture exactly", (eventType) => {
    const jsonFixture = GOLDEN_FIXTURES.find(([type]) => type === eventType)?.[1];
    expect(GOLDEN_AGENT_EVENTS[eventType as keyof typeof GOLDEN_AGENT_EVENTS]).toEqual(jsonFixture);
  });

  it("PAYLOAD_FIELDS[type] is exactly Object.keys(GOLDEN_AGENT_EVENTS[type].payload)", () => {
    for (const type of AGENT_EVENT_TYPES) {
      expect(PAYLOAD_FIELDS[type]).toEqual(Object.keys(GOLDEN_AGENT_EVENTS[type].payload));
    }
  });

  it("ENVELOPE_FIELDS is exactly Object.keys of a golden instance", () => {
    expect([...ENVELOPE_FIELDS].sort()).toEqual(
      Object.keys(GOLDEN_AGENT_EVENTS["workflow.started"]).sort(),
    );
  });
});

describe("PAYLOAD_FIELDS / ENVELOPE_FIELDS", () => {
  it("declares the exact envelope field set", () => {
    expect([...ENVELOPE_FIELDS].sort()).toEqual(
      ["event_type", "payload", "sequence_number", "timestamp", "v", "workflow_run_id"].sort(),
    );
  });

  it("declares the exact payload field set for every event type", () => {
    expect(Object.keys(PAYLOAD_FIELDS).sort()).toEqual([...AGENT_EVENT_TYPES].sort());
    expect(PAYLOAD_FIELDS["tool.completed"]).toEqual([
      "tool_call_id",
      "tool_name",
      "ok",
      "summary",
    ]);
  });

  it("STOP_REASONS names every stop_reason workflow.completed/workflow.failed may carry", () => {
    expect(STOP_REASONS).toContain("final_response");
    expect(STOP_REASONS).toContain("worker_lost");
    expect(STOP_REASONS).toHaveLength(12);
  });
});

describe("package-root export (index.ts)", () => {
  it("re-exports validateAgentEvent and it behaves identically", () => {
    expect(validateAgentEventFromIndex).toBe(validateAgentEvent);
    const event: AgentEventFromIndex = validateAgentEventFromIndex(workflowStartedFixture);
    expect(event.event_type).toBe("workflow.started");
  });

  it("type-checks AgentEvent from the package root", () => {
    // Compile-time only: if index.ts stopped re-exporting `AgentEvent`, this
    // assignment would fail `tsc`, not just this test file at runtime.
    const sample: AgentEventFromIndex = validateAgentEvent(workflowCompletedFixture);
    const sameType: AgentEvent = sample;
    expect(sameType.event_type).toBe("workflow.completed");
  });
});
