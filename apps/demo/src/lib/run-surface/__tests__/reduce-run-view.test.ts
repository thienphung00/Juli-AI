/**
 * The reducer, proven on a CAPTURED SCENARIO rather than hand-built events.
 *
 * This is #1315's stated point, not a stylistic preference. The reducer is a
 * consumer of a protocol produced by a server it never imports — which is the
 * exact shape of the dominant defect in the last three waves. A hand-built
 * event object encodes what the author *believed* the server emits, so a test
 * built from one passes precisely when the belief is wrong. The scenario file
 * was captured from a real persisted run, so it disagrees with a wrong belief.
 *
 * Review should reject any hand-built fixture added to this file.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { AGENT_EVENT_TYPES, type AgentEvent } from "@juli/contracts";

import {
  RUN_STAGE_IDS,
  reduceRunView,
  stageForEvent,
  type RunStageId,
} from "../reduce-run-view";

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

interface Scenario {
  readonly scenario_id: string;
  readonly events: AgentEvent[];
  readonly continuations: Record<string, AgentEvent[]>;
}

function loadScenario(): Scenario {
  return JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as Scenario;
}

const scenario = loadScenario();
const approved: AgentEvent[] = [...scenario.events, ...scenario.continuations.approve];

describe("the captured scenario drives the reducer", () => {
  it("loads a scenario whose events carry the shared envelope", () => {
    // Canary. If the capture format drifts from the shared union, every other
    // assertion below is measuring the wrong thing.
    expect(scenario.events.length).toBeGreaterThan(0);
    for (const event of scenario.events) {
      expect(AGENT_EVENT_TYPES).toContain(event.event_type);
      expect(typeof event.sequence_number).toBe("number");
      expect(event.v).toBe(1);
    }
  });

  it("folds every event type in the shared union into a defined decision", () => {
    // Iterates the UNION'S OWN member list, so a ninth event type added to
    // packages/contracts fails here rather than being silently ignored by a
    // switch that quietly falls through.
    for (const type of AGENT_EVENT_TYPES) {
      const probe = { event_type: type, payload: { tool_name: "get_product_information" } };
      const stage = stageForEvent(probe as unknown as AgentEvent);
      // `null` is a defined answer ("drives no stage"); `undefined` is not.
      expect(stage === null || RUN_STAGE_IDS.includes(stage as RunStageId)).toBe(true);
    }
  });

  it("reproduces the stage progression the scenario actually contains", () => {
    const view = reduceRunView(approved);

    // The scenario is a confirm-pause capture: it calls get_product_information,
    // requests approval, then updates. It contains NO get_seo_keywords call, so
    // the SEO stage is never entered. Asserting six-of-six here would mean
    // asserting against a scenario we do not have.
    const entered = view.stages.filter((s) => s.eventSequences.length > 0).map((s) => s.id);
    expect(entered).toEqual([
      "phan-tich",
      "thong-tin-san-pham",
      "de-xuat",
      "cap-nhat",
      "hoan-tat",
    ]);
    expect(view.stages.find((s) => s.id === "seo")?.eventSequences).toEqual([]);

    expect(view.liveEdge).toBe("hoan-tat");
    expect(view.terminal?.kind).toBe("completed");
  });

  it("freezes every past stage and locks nothing once the run is terminal", () => {
    const view = reduceRunView(approved);
    const statuses = view.stages.map((s) => s.status);
    expect(statuses).toEqual(["frozen", "frozen", "frozen", "frozen", "frozen", "active"]);
  });

  it("surfaces the decision request while it is outstanding, and drops it once answered", () => {
    const paused = reduceRunView(scenario.events);
    expect(paused.decisionRequest?.toolName).toBe("update_product_listing");
    expect(paused.liveEdge).toBe("de-xuat");
    expect(paused.terminal).toBeUndefined();

    const answered = reduceRunView(approved);
    expect(answered.decisionRequest).toBeUndefined();
  });
});

describe("idempotence and ordering", () => {
  it("is unchanged by duplicate sequence numbers", () => {
    expect(reduceRunView([...approved, ...approved])).toEqual(reduceRunView(approved));
  });

  it("is unchanged by out-of-order arrival", () => {
    expect(reduceRunView([...approved].reverse())).toEqual(reduceRunView(approved));
  });

  it("is unchanged by a replayed prefix after reconnect", () => {
    // Exactly what Last-Event-ID reconnect does: re-send from a cursor.
    const replayed = [...approved, ...approved.slice(0, 3)];
    expect(reduceRunView(replayed)).toEqual(reduceRunView(approved));
  });

  it("returns equal state when called twice with the same events", () => {
    expect(reduceRunView(approved)).toEqual(reduceRunView(approved));
  });
});

describe("a failed run and a dropped stream are different things", () => {
  it("gives workflow.failed a terminal failed state", () => {
    const failed = scenario.events.map((e, i) =>
      i === scenario.events.length - 1
        ? ({
            ...e,
            event_type: "workflow.failed",
            payload: { status: "failed", stop_reason: "tool_error_unrecoverable" },
          } as unknown as AgentEvent)
        : e,
    );
    const view = reduceRunView(failed);
    expect(view.terminal).toEqual({ kind: "failed", stopReason: "tool_error_unrecoverable" });
  });

  it("leaves terminal undefined when the event list merely stops", () => {
    // A stream that drops mid-run produces a SHORTER event list, never a
    // failure. If this ever returns a terminal state, the UI would tell a
    // seller their run died because the connection blinked.
    const view = reduceRunView(scenario.events.slice(0, 2));
    expect(view.terminal).toBeUndefined();
  });
});

describe("purity", () => {
  it("imports no React, no fetch and no clock", () => {
    const source = readFileSync(
      path.resolve(__dirname, "../reduce-run-view.ts"),
      "utf8",
    );
    // Strip comments first: the module's own docstring names these on purpose.
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(code).not.toMatch(/from "react"/);
    expect(code).not.toMatch(/\bfetch\s*\(/);
    expect(code).not.toMatch(/Date\.now\s*\(/);
    expect(code).not.toMatch(/new Date\s*\(/);
  });
});
