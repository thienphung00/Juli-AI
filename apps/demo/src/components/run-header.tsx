"use client";

/**
 * The run page's header row (issue #1910, PUI-DESIGN.md §2):
 *
 *   │ ← Hành động        Tối ưu sản phẩm     ● Đang chạy │
 *
 * Rendered by `RunStagedView` above the stepper -- the first tab stop on
 * the run surface, before any stepper tab.
 *
 * The status chip NEVER renders a raw `stop_reason` (#1322: no state
 * dressed as another). A non-terminal run reads the dictionary-governed
 * running label; a terminal run resolves its `stop_reason` through
 * `resolveRunTerminalState` into one of the seven honest buckets and
 * renders that bucket's `RUN_TERMINAL_STATE_COPY` label -- the same shared
 * table the run ledger uses, so the two surfaces cannot disagree about
 * what a finished run is called. An unrecognized `stop_reason` falls back
 * to the honest neutral "Đã kết thúc", never guessed into a named bucket.
 *
 * Chip classes reuse the run ledger's `.run-ledger__chip--*` family --
 * token-layer governed (#1912), no colour declared here.
 */

import Link from "next/link";

import {
  RUN_LEDGER_STATUS_LABELS,
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
} from "../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../lib/run-ledger/terminal-state";
import type { RunTerminalState } from "../lib/run-surface/reduce-run-view";
import {
  RUN_HEADER_BACK_LABEL,
  RUN_WORKFLOW_TITLE,
} from "../lib/run-surface/stage-copy";

interface RunHeaderProps {
  /** The LIVE reducer's terminal state (`reduceRunView(events).terminal`)
   *  -- `undefined` while the run is still going. Always the live view,
   *  never a frozen-stage snapshot: the header reports the run's true,
   *  current status even while the seller browses history. */
  readonly terminal: RunTerminalState | undefined;
}

interface RunStatusChip {
  readonly label: string;
  readonly variant: string;
  /** The honest bucket name for `data-run-status` -- a test/debug handle,
   *  never rendered as text. */
  readonly state: string;
}

function resolveStatusChip(terminal: RunTerminalState | undefined): RunStatusChip {
  if (terminal === undefined) {
    return {
      label: RUN_LEDGER_STATUS_LABELS.running,
      variant: "info",
      state: "running",
    };
  }
  const bucket = resolveRunTerminalState(terminal.stopReason);
  const copy = bucket ? RUN_TERMINAL_STATE_COPY[bucket] : RUN_TERMINAL_STATE_UNKNOWN_COPY;
  return { label: copy.label, variant: copy.chipVariant, state: bucket ?? "unknown" };
}

export function RunHeader({ terminal }: RunHeaderProps) {
  const chip = resolveStatusChip(terminal);

  return (
    <header className="run-header">
      <Link className="run-header__back" href="/decisions">
        <span aria-hidden="true">←</span>
        <span>{RUN_HEADER_BACK_LABEL}</span>
      </Link>
      <h1 className="run-header__title">{RUN_WORKFLOW_TITLE}</h1>
      <span
        className={`run-ledger__chip run-ledger__chip--${chip.variant} run-header__status`}
        data-run-status={chip.state}
      >
        {chip.label}
      </span>
    </header>
  );
}
