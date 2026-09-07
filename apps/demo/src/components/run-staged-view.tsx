"use client";

/**
 * The staged run view (issue #1316, ADR-076 decision 3, PUI-DESIGN.md §2).
 * One stage owns the canvas at a time; a top stepper carries position; back
 * revisits frozen completed stages; forward returns to the live edge in one
 * action; anything beyond the live edge is locked -- unreachable by click,
 * by keyboard, and by direct URL (`requestedStageId`, clamped once on
 * mount via `resolveRequestedStageIndex`).
 *
 * TWO VIEWS, DELIBERATELY. `liveView = reduceRunView(events)` always
 * reflects the run's true, current progress -- the stepper's frozen/
 * active/locked classification reads this, so the seller can see the run
 * keep advancing even while browsing history. The CANVAS, while browsing a
 * frozen stage, instead reads a SNAPSHOT taken the instant the seller
 * navigated away from the live edge (`frozenEvents`) -- otherwise global,
 * not-stage-scoped reducer fields (`narration`, `decisionRequest`,
 * `terminal`) would keep changing under a stage the seller was told is
 * frozen, which is exactly the "no live updates land in it" acceptance
 * criterion. Returning to the live edge drops the snapshot and resumes
 * reading `events` live.
 *
 * `viewingIndex` IS DERIVED, NOT SYNCED. `manualViewingIndex === null`
 * means "pinned to the live edge"; a non-null value is the frozen stage the
 * seller navigated to. There is no effect keeping a separate "viewingIndex"
 * state in sync with the live edge as it advances -- deriving it during
 * render is both simpler and the React-recommended shape
 * (react-hooks/set-state-in-effect forbids the effect-sync version).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentEvent } from "@juli/contracts";

import { RUN_STAGE_IDS, RUN_STAGE_LABELS, reduceRunView } from "../lib/run-surface/reduce-run-view";
import {
  canNavigateToStageIndex,
  resolveRequestedStageIndex,
  stageIndexOf,
} from "../lib/run-surface/stage-navigation";
import { RUN_STAGE_NAV_COPY, RUN_STREAM_RECONNECTING_COPY } from "../lib/run-surface/stage-copy";
import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import { RUN_SURFACE_DATA_ATTRIBUTE, RUN_SURFACE_DATA_VALUE } from "../lib/run-surface/tokens";
import { RunStageCanvas, type RunStageCanvasProps } from "./run-stage-canvas";
import { RunStepper, type RunStepperNode } from "./run-stepper";

export interface RunStagedViewProps {
  readonly runId: string;
  readonly productName: string;
  readonly events: readonly AgentEvent[];
  /** From the URL (e.g. `?stage=`) -- untrusted, clamped on mount. */
  readonly requestedStageId?: string | null;
  /** True while the transport has dropped and is retrying -- a STREAM
   *  error, never a run error (PUI-DESIGN.md §8). Absent/false renders
   *  nothing extra. */
  readonly isReconnecting?: boolean;
  /** Bearer token for the Đề xuất option picker's confirmation POST
   *  (#1317) -- same "absent means not connected yet" contract as
   *  `useRunStream`'s own `token` (see `RunDetailRoute`'s docstring,
   *  ADR-094). Threaded straight through to `RunStageCanvas`. */
  readonly confirmationToken?: string;
  readonly confirmationBaseUrl?: string;
  readonly confirmationFetchImpl?: typeof fetch;
  /** Injectable for tests; defaults to the real client. */
  readonly confirm?: RunStageCanvasProps["confirm"];
}

function stagePanelId(stageId: string): string {
  return `run-stage-panel-${stageId}`;
}

/** Wall-clock tick for the Đề xuất expiry countdown -- never `Date.now()`
 *  read during render (react-hooks/purity); the read happens inside an
 *  async task the effect kicks off, matching the run ledger's own
 *  `useRunLedger` pattern (`components/in-progress-panel.tsx`). */
function useNowMs(): number | null {
  const [nowMs, setNowMs] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      if (!cancelled) setNowMs(Date.now());
    }

    void tick();
    const intervalId = setInterval(() => void tick(), 30_000);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, []);

  return nowMs;
}

export function RunStagedView({
  runId,
  productName,
  events,
  requestedStageId,
  isReconnecting = false,
  confirmationToken,
  confirmationBaseUrl,
  confirmationFetchImpl,
  confirm,
}: RunStagedViewProps) {
  const liveView = useMemo(() => reduceRunView(events), [events]);
  const liveEdgeIndex = stageIndexOf(liveView.currentStage);
  const isTerminal = liveView.terminal !== undefined;

  const initialRequestedIndex = useMemo(
    () => resolveRequestedStageIndex(requestedStageId, liveView.currentStage),
    // Only ever consulted for the initial state below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // null = pinned to the live edge; a number = the frozen stage index the
  // seller navigated to. Derived `viewingIndex` below, never a second
  // "current index" state that would need an effect to stay in sync.
  const [manualViewingIndex, setManualViewingIndex] = useState<number | null>(() =>
    initialRequestedIndex === liveEdgeIndex ? null : initialRequestedIndex,
  );
  const [frozenEvents, setFrozenEvents] = useState<readonly AgentEvent[] | null>(() =>
    initialRequestedIndex === liveEdgeIndex ? null : events,
  );

  const pinnedToLiveEdge = manualViewingIndex === null;
  const viewingIndex = pinnedToLiveEdge ? liveEdgeIndex : manualViewingIndex;

  const effectiveEvents = pinnedToLiveEdge ? events : (frozenEvents ?? events);
  const displayView = useMemo(() => reduceRunView(effectiveEvents), [effectiveEvents]);

  const nowMs = useNowMs();

  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const hasMountedRef = useRef(false);

  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    // Focus moves to the newly revealed stage on every advance -- never on
    // the very first mount, which would steal focus from wherever the
    // seller (or the browser) already put it on page load.
    headingRef.current?.focus();
  }, [viewingIndex]);

  // "Adjusting state when a prop changes" -- React's own sanctioned
  // pattern (react.dev/learn/you-might-not-need-an-effect) for tracking a
  // previous render's value: a conditional setState call DURING render,
  // never inside an effect (react-hooks/refs forbids mutating a ref during
  // render for this same purpose). React discards and re-renders
  // synchronously before committing, so this never paints an intermediate
  // frame.
  const viewingStageId = RUN_STAGE_IDS[viewingIndex];
  const [motionTrack, setMotionTrack] = useState(() => ({
    stageId: viewingStageId,
    previousStageId: viewingStageId,
  }));
  if (motionTrack.stageId !== viewingStageId) {
    setMotionTrack({ stageId: viewingStageId, previousStageId: motionTrack.stageId });
  }

  const motion = resolveRunSurfaceMotion(
    "stage-advance",
    { kind: "state-transition", from: motionTrack.previousStageId, to: viewingStageId },
    prefersReducedMotion(),
  );

  function navigateToIndex(index: number) {
    if (!canNavigateToStageIndex(index, liveEdgeIndex)) return;
    if (index === liveEdgeIndex) {
      setManualViewingIndex(null);
      setFrozenEvents(null);
    } else {
      setFrozenEvents(events); // snapshot taken the instant we leave the live edge
      setManualViewingIndex(index);
    }
  }

  function handleBack() {
    navigateToIndex(viewingIndex - 1);
  }

  function handleReturnToLiveEdge() {
    // ONE action, regardless of how many stages behind the seller is.
    navigateToIndex(liveEdgeIndex);
  }

  const nodes: RunStepperNode[] = RUN_STAGE_IDS.map((id, index) => ({
    id,
    label: RUN_STAGE_LABELS[id],
    displayStatus: isTerminal
      ? index <= liveEdgeIndex
        ? "frozen"
        : "locked"
      : index < liveEdgeIndex
        ? "frozen"
        : index === liveEdgeIndex
          ? "active"
          : "locked",
  }));

  return (
    <div {...{ [RUN_SURFACE_DATA_ATTRIBUTE]: RUN_SURFACE_DATA_VALUE }} className="run-staged-view">
      {isReconnecting ? (
        <p className="run-staged-view__reconnecting" role="status">
          {RUN_STREAM_RECONNECTING_COPY}…
        </p>
      ) : null}

      <RunStepper
        nodes={nodes}
        onNavigate={navigateToIndex}
        stagePanelId={stagePanelId}
        viewingIndex={viewingIndex}
      />

      <div
        className="run-staged-view__canvas-wrapper"
        data-run-id={runId}
        style={{
          animationDuration: `${motion.durationMs}ms`,
          animationTimingFunction: motion.easing,
        }}
      >
        <RunStageCanvas
          confirm={confirm}
          confirmationBaseUrl={confirmationBaseUrl}
          confirmationFetchImpl={confirmationFetchImpl}
          confirmationToken={confirmationToken}
          events={effectiveEvents}
          headingRef={headingRef}
          isTerminal={isTerminal}
          nowMs={nowMs}
          productName={productName}
          runId={runId}
          stageId={viewingStageId}
          view={displayView}
        />
      </div>

      <div className="run-staged-view__nav">
        <button disabled={viewingIndex === 0} onClick={handleBack} type="button">
          ← {RUN_STAGE_NAV_COPY.back}
        </button>
        <button
          disabled={viewingIndex === liveEdgeIndex}
          onClick={handleReturnToLiveEdge}
          type="button"
        >
          {RUN_STAGE_NAV_COPY.continueToLiveEdge} →
        </button>
      </div>
    </div>
  );
}
