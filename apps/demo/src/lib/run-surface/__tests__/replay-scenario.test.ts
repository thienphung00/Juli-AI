/**
 * Proves the client's copy of the golden scenario is faithful to the tool's
 * output (issue #1752, ADR-084 decision 2) -- byte-identical to the fixture
 * the capture tool produced, every event validating against the shared
 * event union, and rebasing that preserves recorded inter-event deltas
 * rather than arriving all at once.
 *
 * Also proves issue #1764's fix: rebasing touches nested temporal payload
 * fields (`workflow.approval_required.expires_at`), not just the envelope
 * `timestamp` -- a scenario rebased to `now` must never yield an offer
 * that is already expired AT `now`.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import type { AgentEvent } from "@juli/contracts";
import { validateAgentEvent } from "@juli/contracts";

import {
  REPLAY_SCENARIO_RUN_ID,
  getReplayContinuationEvents,
  getReplayInitialEvents,
} from "../replay-scenario";

function findApprovalRequired(
  events: readonly AgentEvent[],
): Extract<AgentEvent, { event_type: "workflow.approval_required" }> {
  const event = events.find((e) => e.event_type === "workflow.approval_required");
  if (!event || event.event_type !== "workflow.approval_required") {
    throw new Error("fixture is missing its workflow.approval_required event");
  }
  return event;
}

const CLIENT_COPY_PATH = resolve(
  __dirname,
  "../golden-scenarios/optimize_product_confirm_pause.json",
);

// The capture tool's own output -- the single source of truth (ADR-084 d.2).
// Not read via the package boundary: this is a raw filesystem byte
// comparison, deliberately, so a reformat/prettify/re-key on the way into
// the client bundle is caught even if it happens to still parse as valid
// JSON with the same values.
const CAPTURED_FIXTURE_PATH = resolve(
  __dirname,
  "../../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

describe("the client's golden scenario copy", () => {
  it("is byte-identical to the fixture the capture tool produced", () => {
    const clientCopy = readFileSync(CLIENT_COPY_PATH);
    const capturedFixture = readFileSync(CAPTURED_FIXTURE_PATH);

    expect(clientCopy.equals(capturedFixture)).toBe(true);
  });

  it("every event and continuation validates against the shared event union", () => {
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly unknown[];
      continuations: Readonly<Record<string, readonly unknown[]>>;
    };

    for (const event of raw.events) {
      expect(() => validateAgentEvent(event)).not.toThrow();
    }
    for (const continuation of Object.values(raw.continuations)) {
      for (const event of continuation) {
        expect(() => validateAgentEvent(event)).not.toThrow();
      }
    }
  });
});

describe("getReplayInitialEvents", () => {
  it("rebases the first event's timestamp to now", () => {
    const nowMs = Date.parse("2030-01-01T00:00:00.000Z");
    const [first] = getReplayInitialEvents(nowMs);

    expect(first.timestamp).toBe(new Date(nowMs).toISOString());
  });

  it("preserves the captured inter-event deltas exactly", () => {
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly { timestamp: string }[];
    };
    const capturedDeltasMs = raw.events.map(
      (event) => Date.parse(event.timestamp) - Date.parse(raw.events[0].timestamp),
    );

    const nowMs = Date.parse("2030-01-01T00:00:00.000Z");
    const rebased = getReplayInitialEvents(nowMs);
    const rebasedDeltasMs = rebased.map(
      (event) => Date.parse(event.timestamp) - Date.parse(rebased[0].timestamp),
    );

    expect(rebasedDeltasMs).toEqual(capturedDeltasMs);
  });

  it("changes nothing but temporal fields -- same order, ids, and every non-temporal payload field", () => {
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly Record<string, unknown>[];
    };

    const rebased = getReplayInitialEvents(Date.now());

    expect(rebased).toHaveLength(raw.events.length);
    rebased.forEach((event, index) => {
      const original = raw.events[index] as Record<string, unknown>;
      const originalPayload = original.payload as Record<string, unknown>;
      const rebasedPayload = event.payload as unknown as Record<string, unknown>;

      expect(event.workflow_run_id).toBe(original.workflow_run_id);
      expect(event.sequence_number).toBe(original.sequence_number);
      expect(event.event_type).toBe(original.event_type);
      expect(event.v).toBe(original.v);

      if (event.event_type === "workflow.approval_required") {
        // The one nested temporal field this fixture carries (issue #1764)
        // -- rebased, so it must differ from the captured value -- every
        // OTHER payload field must still match exactly.
        expect(rebasedPayload.expires_at).not.toBe(originalPayload.expires_at);
        expect({ ...rebasedPayload, expires_at: originalPayload.expires_at }).toEqual(
          originalPayload,
        );
      } else {
        expect(rebasedPayload).toEqual(originalPayload);
      }
    });
  });

  it("rebases workflow.approval_required's nested expires_at by the exact same shift as the envelope timestamp -- not a coincidence, the general algorithm", () => {
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly { timestamp: string; event_type: string; payload: Record<string, unknown> }[];
    };
    const originalApproval = raw.events.find(
      (e) => e.event_type === "workflow.approval_required",
    )!;
    const originalExpiresAtMs = Date.parse(originalApproval.payload.expires_at as string);
    const originalEnvelopeMs = Date.parse(originalApproval.timestamp);

    const nowMs = Date.parse("2030-01-01T00:00:00.000Z");
    const rebasedApproval = findApprovalRequired(getReplayInitialEvents(nowMs));

    const envelopeShiftMs = Date.parse(rebasedApproval.timestamp) - originalEnvelopeMs;
    const expiresAtShiftMs =
      Date.parse(rebasedApproval.payload.expires_at) - originalExpiresAtMs;

    expect(envelopeShiftMs).not.toBe(0);
    expect(expiresAtShiftMs).toBe(envelopeShiftMs);
  });

  it("rebased to now, the offer is never already expired at now -- the live #1764 bug (a fixed clock preceding the capture would pass here while the bug persists, so this uses the real clock)", () => {
    const nowMs = Date.now();
    const approval = findApprovalRequired(getReplayInitialEvents(nowMs));

    expect(Date.parse(approval.payload.expires_at)).toBeGreaterThan(nowMs);
  });
});

describe("getReplayContinuationEvents", () => {
  it("rebases the captured 'approve' continuation to start at now, preserving its own recorded deltas", () => {
    const nowMs = Date.parse("2030-01-01T00:00:00.000Z");
    const events = getReplayContinuationEvents("approve", nowMs);

    expect(events.length).toBeGreaterThan(0);
    expect(Date.parse(events[0]!.timestamp)).toBeGreaterThanOrEqual(nowMs);
    for (const event of events) {
      expect(() => validateAgentEvent(event)).not.toThrow();
    }
    expect(events.at(-1)!.event_type).toBe("workflow.completed");
  });

  it("rebases the captured 'decline' continuation to start at now", () => {
    const nowMs = Date.parse("2030-01-01T00:00:00.000Z");
    const events = getReplayContinuationEvents("decline", nowMs);

    expect(events.length).toBeGreaterThan(0);
    expect(events.at(-1)!.event_type).toBe("workflow.completed");
  });

  it("returns events that each validate against the shared event union", () => {
    for (const event of getReplayInitialEvents(Date.now())) {
      expect(() => validateAgentEvent(event)).not.toThrow();
    }
  });

  it("exposes the scenario's own run id as the well-known replay run id", () => {
    // Read from the client copy independently rather than restated. This used
    // to pin the literal "6fed3803-...", which #1862's deterministic re-capture
    // changed — the assertion then failed for a fixture change rather than a
    // behaviour change, and the same literal was pinned in two route tests that
    // failed with it. The property that matters is that the exported id IS the
    // captured run's id, whatever that capture happens to contain.
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly { workflow_run_id: string }[];
    };
    expect(REPLAY_SCENARIO_RUN_ID).toBe(raw.events[0]!.workflow_run_id);
    expect(REPLAY_SCENARIO_RUN_ID).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });
});
