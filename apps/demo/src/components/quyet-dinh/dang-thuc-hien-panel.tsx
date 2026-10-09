"use client";

import type { AgentEvent, WorkflowRunListItem } from "@juli/contracts";
import { StatusChip, type StatusChipVariant } from "@juli/ui";
import { useMemo } from "react";

import { runStages } from "../../lib/quyet-dinh/batch";
import { REVERT_LABEL } from "../../lib/quyet-dinh/copy";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import type { FieldChange, RunChanges } from "../../lib/quyet-dinh/types";
import {
  RUN_LEDGER_EMPTY_STATE,
  RUN_LEDGER_SECTION_TITLES,
  RUN_LEDGER_STATUS_LABELS,
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
} from "../../lib/run-ledger/copy";
import { groupRunsIntoLedgerSections } from "../../lib/run-ledger/sections";
import { resolveRunTerminalState } from "../../lib/run-ledger/terminal-state";
import type { ConfirmDecisionFn } from "../../lib/run-surface/confirmation-decision";
import { OptionPicker } from "../option-picker";
import { FiveStageStepper } from "./five-stage-stepper";
import { RunTimeline } from "./run-timeline";

/**
 * Đang thực hiện (ADR-109 d.9/d.13; the video's master cut 1:23). Left: the
 * selected run as a step timeline from its SSE events; the consent step
 * inline (the existing two-step `OptionPicker`); a finished run that wrote
 * something shows before → after and "Hoàn tác". Right: "Hàng chờ thẻ tối
 * ưu" — `GET /v1/demo/runs` in the ledger's three sections (Đang chờ bạn /
 * Đang chạy / Hoàn tất) with honest terminal states.
 */

export function runChip(run: Pick<WorkflowRunListItem, "status" | "stop_reason">): {
  label: string;
  variant: StatusChipVariant;
} {
  if (run.status === "waiting_approval") return { label: RUN_LEDGER_SECTION_TITLES.waitingOnYou, variant: "warning" };
  if (run.status === "queued") return { label: RUN_LEDGER_STATUS_LABELS.queued, variant: "neutral" };
  if (run.status === "running") return { label: RUN_LEDGER_STATUS_LABELS.running, variant: "info" };
  const key = resolveRunTerminalState(run.stop_reason);
  const copy = key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY;
  return { label: copy.label, variant: copy.chipVariant };
}

export function RunQueue({
  runs,
  selectedId,
  onSelect,
}: {
  readonly runs: readonly WorkflowRunListItem[];
  readonly selectedId: string | null;
  readonly onSelect: (runId: string) => void;
}) {
  const sections = groupRunsIntoLedgerSections(runs);
  const list: [keyof typeof RUN_LEDGER_SECTION_TITLES, WorkflowRunListItem[]][] = [
    ["waitingOnYou", sections.waitingOnYou],
    ["running", sections.running],
    ["finished", sections.finished],
  ];
  return (
    <aside aria-labelledby="qd-queue" className="card qd-queue" data-testid="run-queue">
      <h2 className="qd-side-card__title" id="qd-queue">
        Hàng chờ thẻ tối ưu
      </h2>
      <p className="qd-muted">Juli chạy lần lượt, không bao giờ hai thay đổi cùng lúc trên một sản phẩm.</p>
      {runs.length === 0 ? <p className="qd-muted">{RUN_LEDGER_EMPTY_STATE}</p> : null}
      {list.map(([key, items]) =>
        items.length === 0 ? null : (
          <section aria-label={RUN_LEDGER_SECTION_TITLES[key]} className="qd-queue__section" key={key}>
            <h3 className="qd-queue__title">
              {RUN_LEDGER_SECTION_TITLES[key]} <span className="qd-muted">({items.length})</span>
            </h3>
            <ul className="qd-queue__list">
              {items.map((run) => {
                const chip = runChip(run);
                return (
                  <li key={run.id}>
                    <button
                      aria-pressed={run.id === selectedId}
                      className="qd-queue__item"
                      data-run-id={run.id}
                      onClick={() => onSelect(run.id)}
                      type="button"
                    >
                      <span className="qd-queue__name">{run.product_name}</span>
                      <StatusChip variant={chip.variant}>{chip.label}</StatusChip>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ),
      )}
    </aside>
  );
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(trống)";
  if (typeof value === "string") return value.length > 160 ? `${value.slice(0, 157)}…` : value;
  if (typeof value === "number") return String(value);
  if (typeof value === "object" && value !== null && "count" in value) {
    return `${String((value as { count: unknown }).count)} ảnh`;
  }
  if (Array.isArray(value)) return `${value.length} mục`;
  return "—";
}

export type RevertState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly message: string };

export function RunChangesBlock({
  changes,
  revertState,
  onRevert,
}: {
  readonly changes: RunChanges;
  readonly revertState: RevertState;
  readonly onRevert: () => void;
}) {
  if (changes.changes.length === 0) return null;
  const reasonId = `revert-reason-${changes.run_id}`;
  return (
    <section aria-labelledby={`changes-${changes.run_id}`} className="qd-changes" data-testid="run-changes">
      <h3 className="qd-changes__title" id={`changes-${changes.run_id}`}>
        {changes.reverts_run_id ? "Juli đã khôi phục" : "Juli đã thay đổi"}
      </h3>
      <ul className="qd-changes__list">
        {changes.changes.map((change: FieldChange) => (
          <li className="qd-change" key={change.field}>
            <span className="qd-change__label">{change.label}</span>
            <span className="qd-change__before">
              <span className="qd-sr">Trước: </span>
              {displayValue(change.before)}
            </span>
            <span aria-hidden="true" className="qd-change__arrow">
              →
            </span>
            <span className="qd-change__after">
              <span className="qd-sr">Sau: </span>
              {displayValue(change.after)}
            </span>
          </li>
        ))}
      </ul>
      {changes.reverts_run_id ? null : (
        <div className="qd-changes__actions">
          <button
            aria-describedby={!changes.revert.available && changes.revert.message ? reasonId : undefined}
            className="btn-secondary"
            disabled={!changes.revert.available || revertState.status === "submitting"}
            onClick={onRevert}
            type="button"
          >
            {revertState.status === "submitting" ? "Đang tạo lượt hoàn tác…" : REVERT_LABEL}
          </button>
          {!changes.revert.available && changes.revert.message ? (
            <p className="qd-muted" id={reasonId}>
              {changes.revert.message}
            </p>
          ) : null}
          {revertState.status === "error" ? (
            <p className="qd-error" role="alert">
              {revertState.message}
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

export interface RunDetailPaneProps {
  readonly run: WorkflowRunListItem;
  readonly events: readonly AgentEvent[];
  readonly isRevert: boolean;
  readonly reconnecting: boolean;
  readonly nowMs: number | null;
  readonly confirm: ConfirmDecisionFn;
  readonly token?: string;
  readonly changes: RunChanges | null;
  readonly revertState: RevertState;
  readonly onRevert: () => void;
}

export function RunDetailPane({
  run,
  events,
  isRevert,
  reconnecting,
  nowMs,
  confirm,
  token,
  changes,
  revertState,
  onRevert,
}: RunDetailPaneProps) {
  const timeline = useMemo(() => buildRunTimeline(events, { isRevert }), [events, isRevert]);
  const chip = runChip(run);
  const consent = timeline.pendingConsent;
  return (
    <section aria-labelledby={`run-${run.id}`} className="card qd-run" data-testid="run-detail">
      <div className="qd-run__head">
        <StatusChip variant={chip.variant}>{chip.label}</StatusChip>
        <h2 className="qd-run__title" id={`run-${run.id}`}>
          {isRevert ? "Hoàn tác" : "Lượt chạy"} · {run.product_name}
        </h2>
      </div>
      <FiveStageStepper label={`Tiến trình · ${run.product_name}`} states={runStages(run)} />
      {reconnecting ? (
        <p className="qd-muted" role="status">
          Đang kết nối lại…
        </p>
      ) : null}
      {events.length === 0 ? (
        <p className="qd-muted" role="status">
          Đang tải các bước của lượt chạy…
        </p>
      ) : (
        <RunTimeline
          consent={
            consent ? (
              <OptionPicker
                confirm={confirm}
                expiresAt={consent.expiresAt}
                nowMs={nowMs}
                options={
                  consent.options.length > 0
                    ? consent.options
                    : [{ option_id: "default", proposed_change: consent.proposedChange, rationale: "", params_sha: "" }]
                }
                productName={run.product_name}
                runId={run.id}
                token={token}
                toolCallId={consent.toolCallId}
              />
            ) : null
          }
          steps={timeline.steps}
        />
      )}
      {timeline.terminal && changes ? (
        <RunChangesBlock changes={changes} onRevert={onRevert} revertState={revertState} />
      ) : null}
    </section>
  );
}
