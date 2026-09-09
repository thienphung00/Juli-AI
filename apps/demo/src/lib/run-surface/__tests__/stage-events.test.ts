/**
 * Proven against the CAPTURED SCENARIO (#1311's output), never a hand-built
 * event -- same discipline as `reduce-run-view.test.ts`, and for the same
 * reason: a hand-built event encodes what the author believes the server
 * emits.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import { reduceRunView } from "../reduce-run-view";
import {
  lastApprovalRequiredEvent,
  toolActivityForStage,
  workflowStartedPayload,
} from "../stage-events";

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

interface Scenario {
  readonly events: AgentEvent[];
  readonly continuations: Record<string, AgentEvent[]>;
}

function loadScenario(): Scenario {
  return JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as Scenario;
}

const scenario = loadScenario();
const approved: AgentEvent[] = [...scenario.events, ...scenario.continuations.approve];

/**
 * The summary a tool.completed frame actually carries, read from the scenario
 * rather than restated here.
 *
 * These assertions used to hardcode `summary: "completed"`. The golden scenario
 * was re-captured with the seller-facing Vietnamese copy the product ships
 * ("Hoàn tất"), and every test that restated the old English string broke —
 * for a copy change, not a behaviour change. What these tests are about is that
 * the summary is CARRIED THROUGH to the stage activity, so they now read the
 * expected value from the fixture and assert the plumbing.
 */
const summaryFor = (events: readonly AgentEvent[], toolCallId: string): string => {
  const frame = events.find(
    (e) =>
      e.event_type === "tool.completed" &&
      (e.payload as { tool_call_id?: string } | undefined)?.tool_call_id === toolCallId,
  );
  const summary = (frame?.payload as { summary?: string } | undefined)?.summary;
  // A fixture with no summary would make every assertion below vacuously true.
  if (!summary) {
    throw new Error(`fixture has no tool.completed summary for ${toolCallId}`);
  }
  return summary;
};

describe("toolActivityForStage", () => {
  it("returns the completed get_product_information call's verbatim summary for the product-snapshot stage", () => {
    const view = reduceRunView(scenario.events);
    const stage = view.stages.find((s) => s.id === "thong-tin-san-pham")!;

    const activity = toolActivityForStage(scenario.events, stage);

    expect(activity).toEqual([
      {
        toolCallId: "c1",
        toolName: "get_product_information",
        status: "completed",
        summary: summaryFor(scenario.events, "c1"),
      },
    ]);
  });

  it("returns an empty list for a stage the scenario never entered (SEO)", () => {
    const view = reduceRunView(scenario.events);
    const stage = view.stages.find((s) => s.id === "seo")!;

    expect(toolActivityForStage(scenario.events, stage)).toEqual([]);
  });

  it("returns the update_product_listing writes for the Cập nhật stage once approved", () => {
    const view = reduceRunView(approved);
    const stage = view.stages.find((s) => s.id === "cap-nhat")!;

    const activity = toolActivityForStage(approved, stage);

    expect(activity).toEqual([
      {
        toolCallId: "c2",
        toolName: "update_product_listing",
        status: "completed",
        summary: summaryFor(approved, "c2"),
      },
    ]);
  });

  it("surfaces a still-running tool call with no summary, never invented text", () => {
    // Truncate the approved continuation right after the write starts, before
    // its tool.completed frame arrives -- the honest "still running" shape.
    const runningOnly = [...scenario.events, approved[approved.length - 3]];
    const view = reduceRunView(runningOnly);
    const stage = view.stages.find((s) => s.id === "cap-nhat")!;

    const activity = toolActivityForStage(runningOnly, stage);

    expect(activity).toEqual([
      { toolCallId: "c2", toolName: "update_product_listing", status: "running" },
    ]);
  });
});

describe("lastApprovalRequiredEvent", () => {
  it("finds the approval_required event even after the run has completed and view.decisionRequest is cleared", () => {
    const view = reduceRunView(approved);
    expect(view.decisionRequest).toBeUndefined(); // the reducer's own clearing behavior

    const event = lastApprovalRequiredEvent(approved);
    expect(event?.payload.tool_name).toBe("update_product_listing");
    expect(event?.payload.proposed_change).toEqual({ title: "Tiêu đề đã tối ưu" });
  });

  it("returns null when no approval_required event exists yet", () => {
    expect(lastApprovalRequiredEvent(scenario.events.slice(0, 1))).toBeNull();
  });
});

describe("workflowStartedPayload", () => {
  it("reads the workflow_key/product_ref/prompt_version verbatim from workflow.started", () => {
    const payload = workflowStartedPayload(scenario.events);
    expect(payload).toEqual({
      workflow_key: "optimize_product_2",
      product_ref: "product-ref-ba227180",
      prompt_version: "optimize_product.v3",
    });
  });

  it("returns null when the run has not started yet", () => {
    expect(workflowStartedPayload([])).toBeNull();
  });
});
