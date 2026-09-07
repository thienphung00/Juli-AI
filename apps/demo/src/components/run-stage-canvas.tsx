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

import type { RefObject } from "react";

import { resolveExpiryCountdown } from "../lib/run-ledger/expiry";
import {
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
  formatRunExpiryCopy,
} from "../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../lib/run-ledger/terminal-state";
import type { RunStageId, RunViewState } from "../lib/run-surface/reduce-run-view";
import {
  lastApprovalRequiredEvent,
  toolActivityForStage,
  type StageToolActivityItem,
} from "../lib/run-surface/stage-events";
import {
  RUN_PRODUCT_BINDING_LABEL,
  RUN_STAGE_EMPTY_COPY,
  describeToolAction,
} from "../lib/run-surface/stage-copy";
import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import { RUN_SURFACE_PANEL_CLASS_NAMES } from "../lib/run-surface/tokens";

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
}

function proposedChangeEntries(change: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(change).map(([key, value]) => [
    key,
    typeof value === "object" && value !== null ? JSON.stringify(value) : String(value),
  ]);
}

function ToolActivityList({ items }: { items: readonly StageToolActivityItem[] }) {
  return (
    <ul className="run-stage__tool-list">
      {items.map((item) => (
        <li className="run-stage__tool-item" data-tool-status={item.status} key={item.toolCallId}>
          <span className="run-stage__tool-label">{describeToolAction(item.toolName)}</span>
          {item.status === "running" ? (
            <span className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>Đang thực hiện…</span>
          ) : (
            <span className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{item.summary}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function PhanTichContent({
  view,
  isActive,
  isTerminal,
}: {
  view: RunViewState;
  isActive: boolean;
  isTerminal: boolean;
}) {
  const showThinking = isActive && !isTerminal && view.narration.length === 0;
  const thinkingMotion = showThinking
    ? resolveRunSurfaceMotion(
        "thinking-state",
        { kind: "state-transition", from: "idle", to: "running" },
        prefersReducedMotion(),
      )
    : null;

  return (
    <div>
      {view.narration.length === 0 ? (
        <p className={RUN_SURFACE_PANEL_CLASS_NAMES.narration}>
          {thinkingMotion ? (
            <span
              aria-hidden="true"
              className="run-stage__thinking-dot"
              data-testid="run-stage-thinking-dot"
              style={{
                animationDuration: `${thinkingMotion.durationMs}ms`,
                animationTimingFunction: thinkingMotion.easing,
              }}
            />
          ) : null}
          {RUN_STAGE_EMPTY_COPY["phan-tich"]}
        </p>
      ) : (
        view.narration.map((line, index) => (
          <p className={RUN_SURFACE_PANEL_CLASS_NAMES.narration} key={index}>
            {line}
          </p>
        ))
      )}
    </div>
  );
}

function ProductSnapshotContent({
  events,
  view,
  productName,
}: {
  events: readonly AgentEvent[];
  view: RunViewState;
  productName: string;
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
        <ToolActivityList items={activity} />
      )}
    </div>
  );
}

function SeoContent({ events, view }: { events: readonly AgentEvent[]; view: RunViewState }) {
  const stage = view.stages.find((s) => s.id === "seo")!;
  const activity = toolActivityForStage(events, stage);

  return activity.length === 0 ? (
    <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY.seo}</p>
  ) : (
    <ToolActivityList items={activity} />
  );
}

function DecisionContent({ view, nowMs }: { view: RunViewState; nowMs: number | null }) {
  const decision = view.decisionRequest;
  if (!decision) {
    return (
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY["de-xuat"]}</p>
    );
  }

  const expiry = nowMs !== null ? resolveExpiryCountdown(decision.expiresAt, nowMs) : null;
  const options = decision.options && decision.options.length > 0 ? decision.options : [
    { option_id: "default", proposed_change: decision.proposedChange, rationale: "", params_sha: "" },
  ];

  return (
    <div>
      {options.map((option) => (
        <article className={RUN_SURFACE_PANEL_CLASS_NAMES.panel} key={option.option_id}>
          <dl className="run-stage__proposed-change">
            {proposedChangeEntries(option.proposed_change).map(([key, value]) => (
              <div className="run-stage__proposed-change-row" key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {option.rationale ? <p>{option.rationale}</p> : null}
        </article>
      ))}
      {expiry ? <p className="run-stage__expiry">{formatRunExpiryCopy(expiry.label)}</p> : null}
    </div>
  );
}

function UpdateContent({ events, view }: { events: readonly AgentEvent[]; view: RunViewState }) {
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
                <dt>{key}</dt>
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
        <ToolActivityList items={activity} />
      )}
    </div>
  );
}

function TerminalContent({ view }: { view: RunViewState }) {
  if (!view.terminal) {
    return (
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{RUN_STAGE_EMPTY_COPY["hoan-tat"]}</p>
    );
  }

  const bucket = resolveRunTerminalState(view.terminal.stopReason);
  const copy = bucket ? RUN_TERMINAL_STATE_COPY[bucket] : RUN_TERMINAL_STATE_UNKNOWN_COPY;

  return (
    <div data-terminal-state={bucket ?? "unknown"}>
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
}: RunStageCanvasProps) {
  const isActive = view.currentStage === stageId;

  return (
    <section
      aria-labelledby={`run-stage-tab-${stageId}`}
      className={RUN_SURFACE_PANEL_CLASS_NAMES.panelRaised}
      id={`run-stage-panel-${stageId}`}
      role="tabpanel"
      tabIndex={-1}
    >
      <h2 ref={headingRef} tabIndex={-1}>
        {RUN_STAGE_HEADING_COPY[stageId]}
      </h2>
      {stageId === "phan-tich" ? (
        <PhanTichContent isActive={isActive} isTerminal={isTerminal} view={view} />
      ) : null}
      {stageId === "thong-tin-san-pham" ? (
        <ProductSnapshotContent events={events} productName={productName} view={view} />
      ) : null}
      {stageId === "seo" ? <SeoContent events={events} view={view} /> : null}
      {stageId === "de-xuat" ? <DecisionContent nowMs={nowMs} view={view} /> : null}
      {stageId === "cap-nhat" ? <UpdateContent events={events} view={view} /> : null}
      {stageId === "hoan-tat" ? <TerminalContent view={view} /> : null}
    </section>
  );
}
