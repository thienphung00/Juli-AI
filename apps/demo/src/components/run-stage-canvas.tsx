"use client";

/**
 * One stage's canvas content (issue #1316, PUI-DESIGN.md §2). Renders
 * exactly the §2 content mapping for the stage it is given -- nothing it
 * computed itself. Every piece of text here traces to either a reducer
 * field (`view.narration`, `view.decisionRequest`, `view.terminal`) or a
 * raw event payload looked up via `stage-events.ts` -- there is no branch
 * in this file that invents seller-facing content from scratch.
 *
 * A tool's raw `tool_name` never reaches this component's output --
 * `describeToolAction` maps it to a seller-facing label first
 * (`SELLER_COPY_BANNED_PATTERNS` forbids the raw identifier). The terminal
 * stage's outcome goes through `resolveRunTerminalState` +
 * `RUN_TERMINAL_STATE_COPY` (already built for the run ledger, #1318) --
 * never the raw `stop_reason` enum value.
 */

import type { AgentEvent } from "@juli/contracts";

import { useState, type RefObject } from "react";

import {
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
} from "../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../lib/run-ledger/terminal-state";
import type { RunStageId, RunViewState } from "../lib/run-surface/reduce-run-view";
import {
  lastApprovalRequiredEvent,
  toolActivityForStage,
  type StageToolActivityItem,
} from "../lib/run-surface/stage-events";
import { describeOptionField } from "../lib/run-surface/option-diff";
import {
  RUN_PRODUCT_BINDING_LABEL,
  RUN_STAGE_EMPTY_COPY,
  describeToolAction,
} from "../lib/run-surface/stage-copy";
import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import { RUN_SURFACE_PANEL_CLASS_NAMES } from "../lib/run-surface/tokens";
import type { ConfirmDecisionFn } from "../lib/run-surface/confirmation-decision";
import { OptionPicker } from "./option-picker";
import { RunNarrationTypewriter } from "./run-narration-typewriter";

export interface RunStageCanvasProps {
  readonly stageId: RunStageId;
  readonly view: RunViewState;
  readonly events: readonly AgentEvent[];
  readonly productName: string;
  /** The wall clock for the Đề xuất expiry countdown -- sourced by the
   *  parent in an effect, never read here via `Date.now()` (purity). */
  readonly nowMs: number | null;
  /** True once the run has reached a terminal state -- every stage renders
   *  frozen (no "thinking" indicator) once this is true, even the one at
   *  the live edge, per the "finished run opens fully frozen" AC. */
  readonly isTerminal: boolean;
  readonly headingRef?: RefObject<HTMLHeadingElement | null>;
  /** The run id the Đề xuất option picker (#1317) needs to address its
   *  confirmation POST -- otherwise unused by every other stage. */
  readonly runId: string;
  readonly confirmationToken?: string;
  readonly confirmationBaseUrl?: string;
  readonly confirmationFetchImpl?: typeof fetch;
  /** Injectable for tests; defaults to the real client. */
  readonly confirm?: ConfirmDecisionFn;
}

function joinClassNames(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(" ");
}

function proposedChangeEntries(change: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(change).map(([key, value]) => [
    key,
    typeof value === "object" && value !== null ? JSON.stringify(value) : String(value),
  ]);
}

function ToolActivityList({
  items,
  isTerminal,
}: {
  items: readonly StageToolActivityItem[];
  isTerminal: boolean;
}) {
  // Completions already present at mount were not delivered by a
  // tool.completed event in THIS session (a finished run opens fully
  // frozen; a frozen-stage snapshot remounts with history) -- they render
  // a static check, never a replayed settle (issue #1915).
  const [initiallySettled] = useState(
    () => new Set(items.filter((item) => item.status !== "running").map((item) => item.toolCallId)),
  );
  const reduced = prefersReducedMotion();

  return (
    <ul className="run-stage__tool-list">
      {items.map((item) => {
        // §5 row 7 (tool-chip-complete): "Check-in with subtle scale
        // settle", triggered by the real tool.completed event that
        // flipped this item's status. Reduced motion renders the stated
        // alternative -- an instant check, no settle animation.
        const completedLive =
          item.status === "completed" && !isTerminal && !initiallySettled.has(item.toolCallId);
        const checkMotion = completedLive
          ? resolveRunSurfaceMotion(
              "tool-chip-complete",
              { kind: "agent-event", eventType: "tool.completed" },
              reduced,
            )
          : null;
        const settles = checkMotion !== null && !checkMotion.reduced;

        return (
          <li className="run-stage__tool-item" data-tool-status={item.status} key={item.toolCallId}>
            <span className="run-stage__tool-label">{describeToolAction(item.toolName)}</span>
            {item.status === "running" ? (
              <span className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>Đang thực hiện…</span>
            ) : (
              <span className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{item.summary}</span>
            )}
            {item.status === "completed" ? (
              <span
                aria-hidden="true"
                className={joinClassNames(
                  "run-stage__tool-check",
                  settles ? "run-stage__tool-check--settle" : undefined,
                )}
                style={
                  settles
                    ? {
                        animationDuration: `${checkMotion.durationMs}ms`,
                        animationTimingFunction: checkMotion.easing,
                      }
                    : undefined
                }
              >
                ✓
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function PhanTichContent({ view }: { view: RunViewState }) {
  // The thinking indicator lives on the active stepper node now
  // (PUI-DESIGN.md §5 "on the active stepper node"; issue #1913 item 4)
  // -- this stage renders its narration through the §5 typewriter
  // (issue #1915), which owns the empty copy too so it stays mounted
  // from the stage's first render (see its module doc).
  return (
    <div>
      <RunNarrationTypewriter lines={view.narration} />
    </div>
  );
}

function ProductSnapshotContent({
  events,
  view,
  productName,
  isTerminal,
}: {
  events: readonly AgentEvent[];
  view: RunViewState;
  productName: string;
  isTerminal: boolean;
}) {
  const stage = view.stages.find((s) => s.id === "thong-tin-san-pham")!;
  const activity = toolActivityForStage(events, stage);

  return (
    <div>
      <p className="run-stage__product-snapshot-label">
        {RUN_PRODUCT_BINDING_LABEL}: <strong>{productName}</strong>
      </p>
      {activity.length === 0 ? (
        <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>
          {RUN_STAGE_EMPTY_COPY["thong-tin-san-pham"]}
        </p>
      ) : (
        <ToolActivityList isTerminal={isTerminal} items={activity} />
      )}
    </div>
  );
}

function SeoContent({
  events,
  view,
  isTerminal,
}: {
  events: readonly AgentEvent[];
  view: RunViewState;
  isTerminal: boolean;
}) {
  const stage = view.stages.find((s) => s.id === "seo")!;
  const activity = toolActivityForStage(events, stage);

  return activity.length === 0 ? (
    <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY.seo}</p>
  ) : (
    <ToolActivityList isTerminal={isTerminal} items={activity} />
  );
}

function DecisionContent({
  view,
  nowMs,
  productName,
  runId,
  confirmationToken,
  confirmationBaseUrl,
  confirmationFetchImpl,
  confirm,
}: {
  view: RunViewState;
  nowMs: number | null;
  productName: string;
  runId: string;
  confirmationToken?: string;
  confirmationBaseUrl?: string;
  confirmationFetchImpl?: typeof fetch;
  confirm?: ConfirmDecisionFn;
}) {
  const decision = view.decisionRequest;
  if (!decision) {
    return (
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY["de-xuat"]}</p>
    );
  }

  const options = decision.options && decision.options.length > 0 ? decision.options : [
    { option_id: "default", proposed_change: decision.proposedChange, rationale: "", params_sha: "" },
  ];

  return (
    <OptionPicker
      baseUrl={confirmationBaseUrl}
      confirm={confirm}
      expiresAt={decision.expiresAt}
      fetchImpl={confirmationFetchImpl}
      nowMs={nowMs}
      options={options}
      productName={productName}
      runId={runId}
      token={confirmationToken}
      toolCallId={decision.toolCallId}
    />
  );
}

function UpdateContent({
  events,
  view,
  isTerminal,
}: {
  events: readonly AgentEvent[];
  view: RunViewState;
  isTerminal: boolean;
}) {
  const approval = lastApprovalRequiredEvent(events);
  const stage = view.stages.find((s) => s.id === "cap-nhat")!;
  const activity = toolActivityForStage(events, stage);

  return (
    <div>
      {approval ? (
        <header className="run-stage__update-header">
          <p>{describeToolAction(approval.payload.tool_name)}</p>
          <dl className="run-stage__proposed-change">
            {proposedChangeEntries(approval.payload.proposed_change).map(([key, value]) => (
              <div className="run-stage__proposed-change-row" key={key}>
                {/* The seller-facing label, NEVER the raw proposed_change
                    JSON key (issue #1908) -- same describeOptionField the
                    Đề xuất option cards already use, so the two consumers
                    of this fact cannot diverge again. `key` (the raw key)
                    stays as the React key only; it is never rendered. */}
                <dt>{describeOptionField(key)}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </header>
      ) : null}
      {activity.length === 0 ? (
        <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>
          {RUN_STAGE_EMPTY_COPY["cap-nhat"]}
        </p>
      ) : (
        <ToolActivityList isTerminal={isTerminal} items={activity} />
      )}
    </div>
  );
}

function TerminalContent({ view }: { view: RunViewState }) {
  // A terminal state already present at mount means the seller opened a
  // finished run -- it renders frozen (issue #1316's "finished run opens
  // fully frozen"), never re-animated. Only a terminal event arriving in
  // this session is a real trigger (issue #1915).
  const [hadTerminalAtMount] = useState(() => view.terminal !== undefined);

  if (!view.terminal) {
    return (
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY["hoan-tat"]}</p>
    );
  }

  const bucket = resolveRunTerminalState(view.terminal.stopReason);
  const copy = bucket ? RUN_TERMINAL_STATE_COPY[bucket] : RUN_TERMINAL_STATE_UNKNOWN_COPY;

  // §5 row 8 (terminal-complete): "Stepper completes in sequence, then
  // summary rises" -- the summary's rise, triggered by the run's own
  // workflow.completed / workflow.failed. Reduced motion renders the
  // stated alternative: a plain fade.
  const terminalMotion = !hadTerminalAtMount
    ? resolveRunSurfaceMotion(
        "terminal-complete",
        {
          kind: "agent-event",
          eventType: view.terminal.kind === "failed" ? "workflow.failed" : "workflow.completed",
        },
        prefersReducedMotion(),
      )
    : null;

  return (
    <div
      className={
        terminalMotion
          ? terminalMotion.reduced
            ? "run-stage__terminal--fade"
            : "run-stage__terminal--rise"
          : undefined
      }
      data-terminal-state={bucket ?? "unknown"}
      style={
        terminalMotion
          ? {
              animationDuration: `${terminalMotion.durationMs}ms`,
              animationTimingFunction: terminalMotion.easing,
            }
          : undefined
      }
    >
      <p className="run-stage__terminal-label">{copy.label}</p>
      <p>{copy.body}</p>
    </div>
  );
}

const RUN_STAGE_HEADING_COPY: Readonly<Record<RunStageId, string>> = {
  "phan-tich": "Phân tích",
  "thong-tin-san-pham": "Thông tin sản phẩm",
  seo: "SEO",
  "de-xuat": "Đề xuất",
  "cap-nhat": "Cập nhật",
  "hoan-tat": "Hoàn tất",
};

export function RunStageCanvas({
  stageId,
  view,
  events,
  productName,
  nowMs,
  isTerminal,
  headingRef,
  runId,
  confirmationToken,
  confirmationBaseUrl,
  confirmationFetchImpl,
  confirm,
}: RunStageCanvasProps) {
  return (
    <section
      aria-labelledby={`run-stage-tab-${stageId}`}
      className={`run-stage-canvas ${RUN_SURFACE_PANEL_CLASS_NAMES.panel} ${RUN_SURFACE_PANEL_CLASS_NAMES.panelRaised}`}
      id={`run-stage-panel-${stageId}`}
      role="tabpanel"
      tabIndex={-1}
    >
      <h2 ref={headingRef} tabIndex={-1}>
        {RUN_STAGE_HEADING_COPY[stageId]}
      </h2>
      {stageId === "phan-tich" ? (
        <PhanTichContent view={view} />
      ) : null}
      {stageId === "thong-tin-san-pham" ? (
        <ProductSnapshotContent
          events={events}
          isTerminal={isTerminal}
          productName={productName}
          view={view}
        />
      ) : null}
      {stageId === "seo" ? <SeoContent events={events} isTerminal={isTerminal} view={view} /> : null}
      {stageId === "de-xuat" ? (
        <DecisionContent
          confirm={confirm}
          confirmationBaseUrl={confirmationBaseUrl}
          confirmationFetchImpl={confirmationFetchImpl}
          confirmationToken={confirmationToken}
          nowMs={nowMs}
          productName={productName}
          runId={runId}
          view={view}
        />
      ) : null}
      {stageId === "cap-nhat" ? (
        <UpdateContent events={events} isTerminal={isTerminal} view={view} />
      ) : null}
      {stageId === "hoan-tat" ? <TerminalContent view={view} /> : null}
    </section>
  );
}
