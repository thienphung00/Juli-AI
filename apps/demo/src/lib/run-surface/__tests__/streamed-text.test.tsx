/**
 * Streamed model text in the run surface (ADR-071 amendment, D71.3 / P61-C).
 *
 * Driven by `optimize_product_streamed.json`, a scenario CAPTURED by the tool
 * from the real runner (`tests/unit/test_golden_scenario_streamed_capture.py`),
 * never hand-built events: prefixes and replays of the captured list are what
 * the client actually sees mid-stream and after a reconnect.
 *
 * P85 (D78.2): this scenario is an Optimize Product run, i.e. the model's own
 * prose. A listing / create / promotion run never shows it any more (new runs no
 * longer emit it; a stored run of before renders nothing). The caret plumbing is
 * still exercised through a scripted kind ("manual"), whose `assistant.text`
 * lines are Juli's own copy.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import {
  RunPanel,
  type RunPanelProps,
} from "../../../components/quyet-dinh/run-panel";
import type { QdRun } from "../../quyet-dinh/p10-types";
import { buildRunTimeline, type RunKind } from "../../quyet-dinh/timeline";
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
const events = (
  JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as { events: AgentEvent[] }
).events;

const finals = events.flatMap((e) =>
  e.event_type === "assistant.text" ? [e.payload.text] : [],
);
const firstCommit = events.findIndex((e) => e.event_type === "assistant.text");
/** Mid-stream: the first block's deltas have arrived, its assistant.text has not. */
const midFirstBlock = events.slice(0, firstCommit);
const firstBlockText = midFirstBlock
  .flatMap((e) =>
    e.event_type === "assistant.text.delta" ? [e.payload.text] : [],
  )
  .join("");

describe("the captured streamed scenario", () => {
  it("contains two streamed blocks, each committed by an assistant.text", () => {
    expect(finals).toHaveLength(2);
    const blockIds = new Set(
      events.flatMap((e) =>
        e.event_type === "assistant.text.delta" ? [e.payload.block_id] : [],
      ),
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
    const replayed = [
      ...events.slice(0, resumeAt + 2),
      ...events.slice(resumeAt),
    ];
    expect(reduceRunView(replayed)).toEqual(reduceRunView(events));
    expect(
      reduceRunView([...midFirstBlock, ...midFirstBlock]).liveNarration,
    ).toBe(firstBlockText);
    expect(reduceRunView([...events].reverse())).toEqual(reduceRunView(events));
  });

  it("drops a block that was never committed once the run ends", () => {
    const lastCommit = events
      .map((e) => e.event_type)
      .lastIndexOf("assistant.text");
    const withoutLastCommit = [
      ...events.slice(0, lastCommit),
      ...events.slice(lastCommit + 1),
    ];
    const view = reduceRunView(withoutLastCommit);
    expect(view.terminal?.kind).toBe("completed");
    expect(view.liveNarration).toBeNull();
    expect(view.narration).toEqual([finals[0]]);
  });
});

const SCRIPTED = { kind: "manual" } as const;

describe("buildRunTimeline -- streamed narration (scripted kind)", () => {
  it("narrates the preview with the streaming flag, then the committed text", () => {
    const live = buildRunTimeline(midFirstBlock, SCRIPTED);
    expect(live.narration).toBe(firstBlockText);
    expect(live.narrationStreaming).toBe(true);

    const committed = buildRunTimeline(
      events.slice(0, firstCommit + 1),
      SCRIPTED,
    );
    expect(committed.narration).toBe(finals[0]);
    expect(committed.narrationStreaming).toBe(false);
  });

  it("is not streaming once the run is terminal", () => {
    expect(buildRunTimeline(events, SCRIPTED).narrationStreaming).toBe(false);
  });
});

describe("buildRunTimeline -- P85: a model-driven run shows none of the model's text", () => {
  it.each(["listing", "create", "promotion"] as const)(
    "%s: no preview, no committed text",
    (kind) => {
      for (const prefix of [
        midFirstBlock,
        events.slice(0, firstCommit + 1),
        events,
      ]) {
        const timeline = buildRunTimeline(prefix, { kind });
        expect(timeline.narration).toBeNull();
        expect(timeline.narrationStreaming).toBe(false);
      }
    },
  );
});

function panelProps(
  eventList: readonly AgentEvent[],
  kind: RunKind = "manual",
): RunPanelProps {
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
    kind,
    phase: "analysing",
    timeline: buildRunTimeline(eventList, { kind }),
    card: null,
    changes: null,
    nowMs: null,
    reconnecting: false,
    eventsLoaded: true,
    photoChecks: null,
    photoState: {
      busy: false,
      error: null,
    } as unknown as RunPanelProps["photoState"],
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

  it("P85: a listing run renders neither the preview nor the committed model text", () => {
    render(
      <RunPanel {...panelProps(events.slice(0, firstCommit + 1), "listing")} />,
    );
    expect(screen.queryByTestId("typing-caret")).toBeNull();
    expect(screen.queryByText(finals[0])).toBeNull();
  });
});

describe("RunPanel -- P85 coded status line", () => {
  const at = (n: number) => `2026-11-02T02:00:0${n}Z`;
  const base = { workflow_run_id: "run-s", v: 1 as const };
  const LINE =
    "Juli đề xuất sửa mô tả. Lý do đề xuất: Mô tả quá ngắn, Mô tả chưa xuống dòng. Tác động dự kiến: trang sản phẩm dễ đọc hơn.";
  const coded: AgentEvent[] = [
    {
      ...base,
      sequence_number: 1,
      timestamp: at(1),
      event_type: "workflow.started",
      payload: {
        workflow_key: "optimize_product_2",
        product_ref: "p",
        prompt_version: "optimize_product.v5",
      },
    },
    {
      ...base,
      sequence_number: 2,
      timestamp: at(2),
      event_type: "assistant.text",
      payload: { text: "## Next-steps **CONFIRM** playbook" },
    },
    {
      ...base,
      sequence_number: 3,
      timestamp: at(3),
      event_type: "workflow.status",
      payload: {
        phase_narration: LINE,
        status_code: {
          reason_codes: [
            "DESC_LESS_THAN_FIVE_HUNDRED_CHARS",
            "DESC_NO_NEW_LINE",
          ],
          plan_code: "description",
          impact_code: "easier_to_read",
        },
      },
    },
    {
      ...base,
      sequence_number: 4,
      timestamp: at(4),
      event_type: "workflow.approval_required",
      payload: {
        tool_call_id: "c2",
        tool_name: "update_product_listing",
        proposed_change: { description: "<p>Mô tả</p>" },
        expires_at: "2026-11-02T06:00:00Z",
        options: [],
      },
    },
  ];

  it("exposes the coded line and never the model's text", () => {
    const timeline = buildRunTimeline(coded, { kind: "listing" });
    expect(timeline.codedStatus).toBe(LINE);
    expect(timeline.narration).toBe(LINE);
  });

  it("shows the coded line beside the decision", () => {
    const props = panelProps(coded, "listing");
    render(<RunPanel {...props} phase="consent" />);
    expect(screen.getByTestId("coded-status")).toHaveTextContent(LINE);
    expect(screen.queryByText(/Next-steps|playbook/)).toBeNull();
  });
});
