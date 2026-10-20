/**
 * Streamed model text in the run surface (ADR-071 amendment, D71.3 / P61-C).
 *
 * Driven by `optimize_product_streamed.json`, a scenario CAPTURED by the tool
 * from the real runner (`tests/unit/test_golden_scenario_streamed_capture.py`),
 * never hand-built events: prefixes and replays of the captured list are what
 * the client actually sees mid-stream and after a reconnect.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import { RunPanel, type RunPanelProps } from "../../../components/quyet-dinh/run-panel";
import type { QdRun } from "../../quyet-dinh/p10-types";
import { buildRunTimeline } from "../../quyet-dinh/timeline";
import { reduceRunView } from "../reduce-run-view";

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../../tests/fixtures/golden_scenarios/optimize_product_streamed.json",
);
const events = (JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as { events: AgentEvent[] }).events;

const finals = events.flatMap((e) => (e.event_type === "assistant.text" ? [e.payload.text] : []));
const firstCommit = events.findIndex((e) => e.event_type === "assistant.text");
/** Mid-stream: the first block's deltas have arrived, its assistant.text has not. */
const midFirstBlock = events.slice(0, firstCommit);
const firstBlockText = midFirstBlock
  .flatMap((e) => (e.event_type === "assistant.text.delta" ? [e.payload.text] : []))
  .join("");

describe("the captured streamed scenario", () => {
  it("contains two streamed blocks, each committed by an assistant.text", () => {
    expect(finals).toHaveLength(2);
    const blockIds = new Set(
      events.flatMap((e) => (e.event_type === "assistant.text.delta" ? [e.payload.block_id] : [])),
    );
    expect(blockIds.size).toBe(2);
    expect(firstBlockText.length).toBeGreaterThan(0);
    expect(finals[0].startsWith(firstBlockText)).toBe(true);
  });
});

describe("reduceRunView -- streamed text", () => {
  it("shows the streamed preview while the block is open", () => {
    const view = reduceRunView(midFirstBlock);
    expect(view.liveNarration).toBe(firstBlockText);
    expect(view.narration).toEqual([]);
  });

  it("replaces the preview with the committed text, once", () => {
    const view = reduceRunView(events);
    expect(view.liveNarration).toBeNull();
    expect(view.narration).toEqual(finals);
  });

  it("does not duplicate text after a Last-Event-ID replay or out-of-order arrival", () => {
    const resumeAt = Math.floor(firstCommit / 2);
    const replayed = [...events.slice(0, resumeAt + 2), ...events.slice(resumeAt)];
    expect(reduceRunView(replayed)).toEqual(reduceRunView(events));
    expect(reduceRunView([...midFirstBlock, ...midFirstBlock]).liveNarration).toBe(firstBlockText);
    expect(reduceRunView([...events].reverse())).toEqual(reduceRunView(events));
  });

  it("drops a block that was never committed once the run ends", () => {
    const lastCommit = events.map((e) => e.event_type).lastIndexOf("assistant.text");
    const withoutLastCommit = [...events.slice(0, lastCommit), ...events.slice(lastCommit + 1)];
    const view = reduceRunView(withoutLastCommit);
    expect(view.terminal?.kind).toBe("completed");
    expect(view.liveNarration).toBeNull();
    expect(view.narration).toEqual([finals[0]]);
  });
});

describe("buildRunTimeline -- streamed narration", () => {
  it("narrates the preview with the streaming flag, then the committed text", () => {
    const live = buildRunTimeline(midFirstBlock);
    expect(live.narration).toBe(firstBlockText);
    expect(live.narrationStreaming).toBe(true);

    const committed = buildRunTimeline(events.slice(0, firstCommit + 1));
    expect(committed.narration).toBe(finals[0]);
    expect(committed.narrationStreaming).toBe(false);
  });

  it("is not streaming once the run is terminal", () => {
    expect(buildRunTimeline(events).narrationStreaming).toBe(false);
  });
});

function panelProps(eventList: readonly AgentEvent[]): RunPanelProps {
  const run = {
    id: "run-s",
    status: "running",
    stop_reason: null,
    product_name: "Mặt nạ đất sét 100g",
    created_at: "2026-10-10T02:00:00Z",
    completed_at: null,
    running_seconds_elapsed: 3,
    latest_narration: null,
    decision_summary: null,
    awaiting: null,
  } as QdRun;
  const noop = vi.fn().mockResolvedValue(undefined);
  return {
    run,
    kind: "listing",
    phase: "analysing",
    timeline: buildRunTimeline(eventList),
    card: null,
    changes: null,
    nowMs: null,
    reconnecting: false,
    eventsLoaded: true,
    photoChecks: null,
    photoState: { busy: false, error: null } as unknown as RunPanelProps["photoState"],
    instructions: null,
    appliedState: { busy: false, error: null },
    revertConflict: null,
    revertError: null,
    revertBusy: false,
    measureHref: "/decisions?tab=do-luong",
    onOpenMeasure: vi.fn(),
    onConfirm: noop,
    onDecline: noop,
    onCancelRevert: noop,
    onUpload: noop,
    onApplied: noop,
    onRevert: vi.fn(),
  };
}

describe("RunPanel -- typing caret", () => {
  it("shows the streamed text with a caret while the block is open", () => {
    render(<RunPanel {...panelProps(midFirstBlock)} />);
    const status = screen.getByTestId("typing-caret").closest("[role=status]");
    expect(status).toHaveTextContent(firstBlockText.trim());
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("shows the committed text without a caret once assistant.text lands", () => {
    render(<RunPanel {...panelProps(events.slice(0, firstCommit + 1))} />);
    expect(screen.queryByTestId("typing-caret")).toBeNull();
    expect(screen.getByText(finals[0])).toBeInTheDocument();
  });
});
