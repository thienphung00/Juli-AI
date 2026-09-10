"use client";

/**
 * The top stepper (issue #1316, PUI-DESIGN.md §2/§6). One real tab stop per
 * stage, rendered as native `<button>` elements: a locked stage carries the
 * native `disabled` attribute, which removes it from the tab order and
 * blocks both click and keyboard activation by construction -- "unreachable
 * by click" and "unreachable by keyboard" are the same guarantee here, not
 * two independently-maintained ones.
 *
 * `displayStatus` (frozen/active/locked) is the RUN's state -- the live
 * edge, wherever it is -- and is independent of which node the seller is
 * currently *viewing* (`aria-selected`, the tablist's own "current panel"
 * semantics). Browsing back to a frozen stage does not move the live-edge
 * accent; it stays on the live edge node, exactly as PUI-DESIGN.md §6
 * reserves that accent for "the live edge," never for "whatever the seller
 * is looking at."
 */

import type { RunStageId } from "../lib/run-surface/reduce-run-view";
import { RUN_STAGE_STATUS_COPY } from "../lib/run-surface/stage-copy";
import { RUN_SURFACE_LIVE_EDGE_CLASS_NAMES } from "../lib/run-surface/tokens";

export type RunStepperNodeDisplayStatus = "frozen" | "active" | "locked";

export interface RunStepperNode {
  readonly id: RunStageId;
  readonly label: string;
  readonly displayStatus: RunStepperNodeDisplayStatus;
}

export interface RunStepperProps {
  readonly nodes: readonly RunStepperNode[];
  /** Index of the stage the seller is currently viewing -- may be behind
   *  the live edge; never ahead of it. */
  readonly viewingIndex: number;
  readonly onNavigate: (index: number) => void;
  readonly stagePanelId: (stageId: RunStageId) => string;
}

function joinClassNames(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(" ");
}

export function RunStepper({ nodes, viewingIndex, onNavigate, stagePanelId }: RunStepperProps) {
  return (
    <div aria-label="Các bước xử lý" className="run-stepper" role="tablist">
      {nodes.map((node, index) => {
        const isLocked = node.displayStatus === "locked";
        const isViewing = index === viewingIndex;

        return (
          <button
            key={node.id}
            aria-controls={stagePanelId(node.id)}
            aria-current={node.displayStatus === "active" ? "step" : undefined}
            aria-selected={isViewing}
            className={joinClassNames(
              "run-stepper__node",
              `run-stepper__node--${node.displayStatus}`,
              node.displayStatus === "active"
                ? RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.stepperNodeActive
                : undefined,
              isViewing ? "run-stepper__node--viewing" : undefined,
            )}
            disabled={isLocked}
            id={`run-stage-tab-${node.id}`}
            onClick={() => onNavigate(index)}
            role="tab"
            type="button"
          >
            <span aria-hidden="true" className="run-stepper__node-index">
              {index + 1}
            </span>
            <span className="run-stepper__node-label">{node.label}</span>
            <span className="run-stepper__node-status juli-run-text-muted">
              ({RUN_STAGE_STATUS_COPY[node.displayStatus]})
            </span>
          </button>
        );
      })}
    </div>
  );
}
