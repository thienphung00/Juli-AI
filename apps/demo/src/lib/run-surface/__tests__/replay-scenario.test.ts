/**
 * Proves the client's copy of the golden scenario is faithful to the tool's
 * output (issue #1752, ADR-084 decision 2) -- byte-identical to the fixture
 * the capture tool produced, every event validating against the shared
 * event union, and rebasing that preserves recorded inter-event deltas
 * rather than arriving all at once.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import { validateAgentEvent } from "@juli/contracts";

import {
  REPLAY_SCENARIO_RUN_ID,
  getReplayInitialEvents,
} from "../replay-scenario";

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

  it("changes nothing but the timestamp field -- same order, ids, payloads", () => {
    const raw = JSON.parse(readFileSync(CLIENT_COPY_PATH, "utf8")) as {
      events: readonly Record<string, unknown>[];
    };

    const rebased = getReplayInitialEvents(Date.now());

    expect(rebased).toHaveLength(raw.events.length);
    rebased.forEach((event, index) => {
      const original = raw.events[index];
      expect(event.workflow_run_id).toBe(original.workflow_run_id);
      expect(event.sequence_number).toBe(original.sequence_number);
      expect(event.event_type).toBe(original.event_type);
      expect(event.payload).toEqual(original.payload);
      expect(event.v).toBe(original.v);
    });
  });

  it("returns events that each validate against the shared event union", () => {
    for (const event of getReplayInitialEvents(Date.now())) {
      expect(() => validateAgentEvent(event)).not.toThrow();
    }
  });

  it("exposes the scenario's own run id as the well-known replay run id", () => {
    // Matches the UUID already pinned in run-detail-route.test.tsx and
    // in-progress-detail-route-dispatch.test.tsx -- this is not a
    // coincidence, it is the same captured run.
    expect(REPLAY_SCENARIO_RUN_ID).toBe("6fed3803-a77e-4d55-9ea3-ac72d25e77e2");
  });
});
