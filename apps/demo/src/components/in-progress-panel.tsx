"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import type {
  ExecutionLifecycleStatus,
  ExecutionRecord,
  ExecutionTimelineStep,
  ExecutionTimelineStepKind,
  ExecutionTimelineStepStatus,
  WorkflowRunListItem,
} from "@juli/contracts";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle } from "@juli/ui";

import { sanitizeSellerReviewText } from "../lib/review-seller-copy";
import { recommendationFixtures } from "../lib/recommendations";
import {
  type RepeatConsentSurface,
  selectRepeatConsentSurfaces,
} from "../lib/repeat-consent";
import { fetchDemoRuns } from "../lib/run-ledger/api-client";
import {
  RUN_LEDGER_BACK_TO_DECISIONS,
  RUN_LEDGER_BODY_COPY,
  RUN_LEDGER_EMPTY_STATE,
  RUN_LEDGER_LOADING,
  RUN_LEDGER_LOAD_ERROR,
  RUN_LEDGER_NO_RETRY_NOTE,
  RUN_LEDGER_SECTION_TITLES,
  RUN_LEDGER_STATUS_LABELS,
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
  formatRunExpiryCopy,
} from "../lib/run-ledger/copy";
import { resolveExpiryCountdown } from "../lib/run-ledger/expiry";
import { RUN_LEDGER_POLL_INTERVAL_MS } from "../lib/run-ledger/panel-config";
import { groupRunsIntoLedgerSections } from "../lib/run-ledger/sections";
import { resolveRunTerminalState } from "../lib/run-ledger/terminal-state";
import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import {
  RUN_SURFACE_DATA_ATTRIBUTE,
  RUN_SURFACE_DATA_VALUE,
  RUN_SURFACE_PANEL_CLASS_NAMES,
} from "../lib/run-surface/tokens";
import { useDemoState } from "./demo-state";
import { RepeatConsentBlock } from "./repeat-consent-block";

/**
 * In-Progress becomes the run ledger (issue #1318 / W6-A/P-UI-5,
 * PUI-DESIGN.md §4, ADR-076 decision 5).
 *
 * This panel now composes TWO sources, deliberately kept apart:
 *
 * 1. **The run ledger** (this issue's scope) — a POLLED consumer of
 *    `GET /v1/demo/runs` (#1310). Every card here is a real
 *    `workflow_run` row for the Optimize Product workflow, sorted into
 *    three priority sections. A queued run (zero events) is visible
 *    because this reads the persisted list, never the per-run SSE event
 *    stream. No terminal state is computed here: `resolveRunTerminalState`
 *    is a pure lookup keyed on the server's own `stop_reason` value. No
 *    retry-in-place control exists on this surface.
 *
 * 2. **The legacy mock execution list** — the OTHER 10 workflows' existing
 *    In-Progress flow (needs_input / executing / completed
 *    `ExecutionRecord`s from `useDemoState()`), which PUI-DESIGN.md's own
 *    mandate keeps binding ("the other 10 workflows' existing flows") and
 *    issue #1318's own notes leave untouched ("the mock state it reads is
 *    deleted in the mock-layer slice [#1320], so leave the mock's other
 *    consumers alone here"). This half of the component is functionally
 *    UNCHANGED from before this issue.
 *
 * Clicking a run-ledger card navigates to `/decisions/in-progress/{run.id}`
 * -- the per-run route ADR-076 decision 3 specifies reopens a finished run
 * frozen via replay. That staged/frozen renderer is issue #1316's
 * deliverable (not yet merged on this branch, and not a blocker of this
 * issue) -- this slice owns the correct navigation contract into it, not a
 * duplicate renderer.
 */

interface InProgressPanelProps {
  panelId: string;
  /**
   * Whether this panel is the seller's currently-visible sub-tab.
   * `RecommendationsView` mounts BOTH sub-tab panels at all times (hidden
   * via CSS, not unmounted, so tab state survives switching) -- without
   * this gate the ledger would poll `GET /v1/demo/runs` in the background
   * even while the seller is looking at Recommendations, which is exactly
   * the "makes no backend request anywhere in the recommendations flow"
   * invariant `decisions-recommendations.test.tsx` protects. Defaults to
   * `true` for standalone usage (tests, or any future host that always
   * shows this panel).
   */
  active?: boolean;
}

// ---------------------------------------------------------------------------
// Run ledger (issue #1318) — real workflow_run rows from GET /v1/demo/runs
// ---------------------------------------------------------------------------

type LedgerLoadStatus = "loading" | "ready" | "error";

function runDetailHref(runId: string): string {
  return `/decisions/in-progress/${runId}`;
}

function joinClassNames(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(" ");
}

interface RunCardProps {
  run: WorkflowRunListItem;
}

function WaitingOnYouCard({ run }: RunCardProps) {
  const expiry = run.decision_summary
    ? resolveExpiryCountdown(run.decision_summary.expires_at, Date.now())
    : null;

  return (
    <article
      className={joinClassNames(
        RUN_SURFACE_PANEL_CLASS_NAMES.panel,
        RUN_SURFACE_PANEL_CLASS_NAMES.panelRaised,
        "run-ledger__card",
        "run-ledger__card--waiting",
      )}
      data-run-card-id={run.id}
      data-run-section="waiting_on_you"
    >
      <h3 className="run-ledger__card-title">
        <Link href={runDetailHref(run.id)}>{run.product_name}</Link>
      </h3>
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>
        {RUN_LEDGER_BODY_COPY.waitingOnYou}
      </p>
      {expiry ? (
        <p className="run-ledger__expiry">{formatRunExpiryCopy(expiry.label)}</p>
      ) : null}
    </article>
  );
}

function RunningCard({ run }: RunCardProps) {
  const isActivelyRunning = run.status === "running";
  const statusLabel =
    run.status === "queued"
      ? RUN_LEDGER_STATUS_LABELS.queued
      : RUN_LEDGER_STATUS_LABELS.running;
  const narration =
    run.latest_narration ??
    (run.status === "queued"
      ? RUN_LEDGER_BODY_COPY.queued
      : RUN_LEDGER_BODY_COPY.runningFallback);

  const breathingMotion = isActivelyRunning
    ? resolveRunSurfaceMotion(
        "thinking-state",
        { kind: "state-transition", from: "idle", to: "running" },
        prefersReducedMotion(),
      )
    : null;

  return (
    <article
      className={joinClassNames(RUN_SURFACE_PANEL_CLASS_NAMES.panel, "run-ledger__card")}
      data-run-card-id={run.id}
      data-run-section="running"
    >
      <h3 className="run-ledger__card-title">
        <Link href={runDetailHref(run.id)}>{run.product_name}</Link>
      </h3>
      <span className="run-ledger__chip run-ledger__chip--info">
        {breathingMotion ? (
          <span
            aria-hidden="true"
            className="run-ledger__breathing-dot"
            data-testid="run-ledger-breathing-dot"
            style={{
              animationDuration: `${breathingMotion.durationMs}ms`,
              animationTimingFunction: breathingMotion.easing,
            }}
          />
        ) : null}
        {statusLabel}
      </span>
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.narration}>{narration}</p>
    </article>
  );
}

function FinishedRunCard({ run }: RunCardProps) {
  const bucket = resolveRunTerminalState(run.stop_reason);
  const copy = bucket ? RUN_TERMINAL_STATE_COPY[bucket] : RUN_TERMINAL_STATE_UNKNOWN_COPY;
  const isFailureLike = bucket === "failed" || bucket === "worker_lost";

  const riseMotion = resolveRunSurfaceMotion(
    "terminal-complete",
    { kind: "state-transition", from: "running", to: "finished" },
    prefersReducedMotion(),
  );

  return (
    <article
      className={joinClassNames(
        RUN_SURFACE_PANEL_CLASS_NAMES.panel,
        "run-ledger__card",
        "run-ledger__finished-card",
      )}
      data-run-card-id={run.id}
      data-run-section="finished"
      data-terminal-state={bucket ?? "unknown"}
      style={{
        animationDuration: `${riseMotion.durationMs}ms`,
        animationTimingFunction: riseMotion.easing,
      }}
    >
      <h3 className="run-ledger__card-title">
        <Link href={runDetailHref(run.id)}>{run.product_name}</Link>
      </h3>
      <span className={`run-ledger__chip run-ledger__chip--${copy.chipVariant}`}>
        {copy.label}
      </span>
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted}>{copy.body}</p>
      {isFailureLike ? (
        <p className="run-ledger__no-retry">
          {RUN_LEDGER_NO_RETRY_NOTE}{" "}
          <Link href="/decisions">{RUN_LEDGER_BACK_TO_DECISIONS}</Link>
        </p>
      ) : null}
    </article>
  );
}

function useRunLedger(active: boolean): {
  sections: ReturnType<typeof groupRunsIntoLedgerSections>;
  status: LedgerLoadStatus;
  hasAnyRuns: boolean;
} {
  const [runs, setRuns] = useState<WorkflowRunListItem[]>([]);
  const [status, setStatus] = useState<LedgerLoadStatus>("loading");
  const inFlightRef = useRef(false);

  useEffect(() => {
    // Only the visible sub-tab polls — see `InProgressPanelProps.active`.
    if (!active) {
      return;
    }

    let cancelled = false;

    async function load() {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const nextRuns = await fetchDemoRuns();
        if (!cancelled) {
          setRuns(nextRuns);
          setStatus("ready");
        }
      } catch {
        if (!cancelled) {
          setStatus("error");
        }
      } finally {
        inFlightRef.current = false;
      }
    }

    void load();
    // Poll cadence (PUI-DESIGN.md §4/§8): this is the list-level refetch —
    // NOT a per-run SSE stream. The ledger opens zero event streams; a
    // single active run's own live stream is #1315/#1316's per-run detail
    // view concern, not this list surface's.
    const intervalId = setInterval(() => {
      void load();
    }, RUN_LEDGER_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [active]);

  return {
    sections: groupRunsIntoLedgerSections(runs),
    status,
    hasAnyRuns: runs.length > 0,
  };
}

// ---------------------------------------------------------------------------
// Legacy mock execution list (the other 10 workflows) — UNCHANGED behavior.
// ---------------------------------------------------------------------------

export const LIFECYCLE_STATUS_LABELS: Record<ExecutionLifecycleStatus, string> =
  {
    needs_input: "Cần thêm thông tin",
    executing: "Đang thực hiện",
    completed: "Hoàn tất",
  };

export const STEP_KIND_LABELS: Record<ExecutionTimelineStepKind, string> = {
  action: "Hành động",
  wait: "Chờ",
  outcome: "Kết quả",
};

export const STEP_STATUS_LABELS: Record<ExecutionTimelineStepStatus, string> = {
  pending: "Chờ xử lý",
  running: "Đang chạy",
  succeeded: "Thành công",
  failed: "Thất bại",
};

/**
 * Authored fallback when a workflow stops on a step without recoveryText.
 * Plain seller Vietnamese; must stay clean of SELLER_COPY_BANNED_PATTERNS.
 */
export const NEEDS_INPUT_FALLBACK_RECOVERY_TEXT =
  "Juli đang chờ bạn bổ sung thông tin cho bước này trước khi tiếp tục.";

export function getWorkflowTitle(workflowKey: string): string {
  return (
    recommendationFixtures.find((fixture) => fixture.workflowKey === workflowKey)
      ?.title ?? workflowKey
  );
}

export function getWorkflowCapability(workflowKey: string): string {
  return (
    recommendationFixtures.find((fixture) => fixture.workflowKey === workflowKey)
      ?.capabilityLabel ?? "—"
  );
}

export function getActiveStep(
  timeline: ExecutionTimelineStep[],
): ExecutionTimelineStep | undefined {
  const runningStep = timeline.find((step) => step.status === "running");
  if (runningStep) {
    return runningStep;
  }

  const failedStep = timeline.find((step) => step.status === "failed");
  if (failedStep) {
    return failedStep;
  }

  const lastSucceededIndex = timeline.reduce(
    (lastIndex, step, index) =>
      step.status === "succeeded" ? index : lastIndex,
    -1,
  );

  return timeline
    .slice(lastSucceededIndex + 1)
    .find((step) => step.status === "pending");
}

export function getCurrentStepLabel(record: ExecutionRecord): string {
  const activeStep = getActiveStep(record.timeline);

  if (!activeStep) {
    const lastStep = record.timeline.at(-1);
    return lastStep ? `Bước ${lastStep.stepNumber}: ${lastStep.title}` : "—";
  }

  return `Bước ${activeStep.stepNumber}: ${activeStep.title}`;
}

export function getNextActionText(record: ExecutionRecord): string | undefined {
  const activeStep = getActiveStep(record.timeline);
  if (!activeStep) {
    return undefined;
  }

  return activeStep.recoveryText ?? activeStep.title;
}

/**
 * Lifecycle status of an execution record, exposed as a single accessor so
 * downstream consumers (e.g. repeat-consent gating) gate on one source of
 * truth instead of re-deriving it. The model has no failure state: the only
 * values are "needs_input", "executing", and "completed".
 */
export function getLifecycleStatus(
  record: ExecutionRecord,
): ExecutionLifecycleStatus {
  return record.lifecycleStatus;
}

/**
 * Seller-facing recovery text for a stopped workflow. Defined only when the
 * record is in needs_input: the active (stopped) step's authored recoveryText,
 * routed through the seller-copy sanitizer, with an authored generic fallback
 * when the step carries none.
 */
export function getRecoveryText(record: ExecutionRecord): string | undefined {
  if (getLifecycleStatus(record) !== "needs_input") {
    return undefined;
  }

  const activeStep = getActiveStep(record.timeline);
  return sanitizeSellerReviewText(
    activeStep?.recoveryText ?? NEEDS_INPUT_FALLBACK_RECOVERY_TEXT,
  );
}

export function getCurrentStepNumber(record: ExecutionRecord): number {
  const activeStep = getActiveStep(record.timeline);
  if (!activeStep) {
    const lastStep = record.timeline.at(-1);
    return lastStep?.stepNumber ?? record.timeline.length;
  }
  return activeStep.stepNumber;
}

export function getStepFraction(record: ExecutionRecord): string {
  const currentStepNumber = getCurrentStepNumber(record);
  const totalSteps = record.timeline.length;
  return `${currentStepNumber} / ${totalSteps}`;
}

export function getLifecycleChipVariant(
  status: ExecutionLifecycleStatus,
): "info" | "success" | "warning" {
  if (status === "needs_input") {
    return "warning";
  }

  if (status === "completed") {
    return "success";
  }

  return "info";
}

interface ExecutionProgressCardProps {
  record: ExecutionRecord;
  onCancel: (executionId: string) => void;
  repeatConsentSurface: RepeatConsentSurface | undefined;
}

function ExecutionProgressCard({
  record,
  onCancel,
  repeatConsentSurface,
}: ExecutionProgressCardProps) {
  const [expanded, setExpanded] = useState(false);
  const reactId = useId();
  const panelId = `${reactId}-steps-panel`;

  const workflowTitle = getWorkflowTitle(record.workflowKey);
  const lifecycleStatus = getLifecycleStatus(record);
  const recoveryText = getRecoveryText(record);
  const nextAction = getNextActionText(record);
  const stepFraction = getStepFraction(record);

  // Determine mode strip text
  const modeLabel = lifecycleStatus === "needs_input" ? "Xác nhận" : "Đang chạy";

  // Get badge variant for lifecycle status
  const badgeVariant: "success" | "destructive" | "warning" | "live" =
    lifecycleStatus === "completed"
      ? "success"
      : lifecycleStatus === "needs_input"
        ? "warning"
        : "live";

  return (
    <Card
      className={
        lifecycleStatus === "needs_input"
          ? "execution-card--needs-input"
          : undefined
      }
      data-lifecycle-status={lifecycleStatus}
    >
      {/* Mode strip */}
      <div className="execution-card__mode-strip">
        <span className="execution-card__mode-label">{modeLabel}</span>
      </div>

      {/* Card Header */}
      <CardHeader>
        <div className="execution-card__header-row">
          <CardTitle>
            <Link href={`/decisions/in-progress/${record.executionId}`}>
              {workflowTitle}
            </Link>
          </CardTitle>
          <Badge variant={badgeVariant}>
            {LIFECYCLE_STATUS_LABELS[record.lifecycleStatus]}
          </Badge>
        </div>
      </CardHeader>

      {/* Card Body */}
      <CardBody>
        {/* Step fraction line */}
        <div className="execution-card__step-line">
          <p>Bước {stepFraction}</p>
        </div>

        {/* Recovery text — the workflow stopped and needs the seller */}
        {recoveryText ? (
          <div className="execution-card__recovery" role="status">
            <p>{recoveryText}</p>
          </div>
        ) : (
          nextAction && (
            <div className="execution-card__next-action">
              <p>{sanitizeSellerReviewText(nextAction)}</p>
            </div>
          )
        )}

        {/* Policy line */}
        <div className="execution-card__policy-line">
          <p>Đã kiểm tra chính sách TikTok Shop</p>
        </div>

        {/* Expansion control for steps list */}
        <div className="execution-card__expansion-control">
          <Button
            variant="ghost"
            size="small"
            aria-controls={panelId}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Thu gọn" : "Xem tất cả các bước"}
          </Button>
        </div>

        {/* Expanded steps list */}
        {expanded && (
          <div className="execution-card__steps-panel" id={panelId}>
            <ol aria-label="Tiến trình thực hiện" className="execution-card__steps-list">
              {record.timeline.map((step) => (
                <li key={step.id} data-step-kind={step.kind} data-step-status={step.status}>
                  <article>
                    <p className="demo-kicker">
                      Bước {step.stepNumber} · {STEP_KIND_LABELS[step.kind]}
                    </p>
                    <h4>{sanitizeSellerReviewText(step.title)}</h4>
                    <p className="demo-intro">
                      {sanitizeSellerReviewText(step.description)}
                    </p>
                    {step.recoveryText ? (
                      <p className="demo-notice">
                        {sanitizeSellerReviewText(step.recoveryText)}
                      </p>
                    ) : null}
                    {step.errorText ? (
                      <p className="demo-notice" role="alert">
                        {sanitizeSellerReviewText(step.errorText)}
                      </p>
                    ) : null}
                  </article>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Cancel/Rollback button */}
        <div className="execution-card__actions">
          <Button
            variant="secondary"
            size="small"
            onClick={() => onCancel(record.executionId)}
            aria-label={`Hủy ${workflowTitle}`}
          >
            Hủy
          </Button>
        </div>

        {/* Repeat consent — after the work is finished, never before */}
        <RepeatConsentBlock
          surface={repeatConsentSurface}
          workflowKey={record.workflowKey}
        />
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Composed panel
// ---------------------------------------------------------------------------

export function InProgressPanel({ panelId, active = true }: InProgressPanelProps) {
  const ledger = useRunLedger(active);
  // While this sub-tab is not the visible one, treat the ledger as
  // trivially "ready with nothing yet fetched" rather than perpetually
  // "loading" — `useRunLedger` deliberately never issues a request while
  // inactive, so "loading" would otherwise never resolve.
  const ledgerStatus: LedgerLoadStatus = active ? ledger.status : "ready";

  const { mutableState, updateMutableState } = useDemoState();

  // Sort records: executing first, then needs_input, then completed
  const executionRecords = Object.values(mutableState.executionRecords)
    .filter((record): record is ExecutionRecord => record !== undefined)
    .sort((left, right) => {
      const statusOrder: Record<ExecutionLifecycleStatus, number> = {
        executing: 0,
        needs_input: 1,
        completed: 2,
      };

      const leftOrder = statusOrder[left.lifecycleStatus];
      const rightOrder = statusOrder[right.lifecycleStatus];

      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }

      // Within same status, sort by updatedAt descending
      return (
        new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
      );
    });

  // One consent surface per workflow kind across the whole list, decided in
  // display order — the frequency gate, applied once rather than per card.
  const repeatConsentSurfaces = selectRepeatConsentSurfaces({
    records: executionRecords,
    promptedWorkflowKeys: mutableState.repeatConsentPromptedWorkflowKeys,
    grants: mutableState.repeatConsentGrants,
  });

  const handleCancelExecution = (executionId: string) => {
    // Dry-run only: mutate local execution records
    updateMutableState((prev) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [executionId]: _, ...restRecords } = prev.executionRecords;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [executionId]: __, ...restProgress } = prev.executionProgress;
      return {
        ...prev,
        executionRecords: restRecords,
        executionProgress: restProgress,
      };
    });
  };

  const hasAnyMockRecords = executionRecords.length > 0;
  const hasAnything = ledger.hasAnyRuns || hasAnyMockRecords;

  if (!hasAnything && ledgerStatus !== "loading") {
    return (
      <div aria-label="Đang thực hiện" id={panelId}>
        <section
          aria-label="Đang thực hiện"
          className="demo-placeholder"
          role="status"
        >
          <h2>Đang thực hiện</h2>
          <p>{RUN_LEDGER_EMPTY_STATE}</p>
        </section>
      </div>
    );
  }

  return (
    <div
      aria-label="Đang thực hiện"
      id={panelId}
      className="run-ledger"
      {...{ [RUN_SURFACE_DATA_ATTRIBUTE]: RUN_SURFACE_DATA_VALUE }}
    >
      {ledgerStatus === "loading" && !hasAnything ? (
        <p className={RUN_SURFACE_PANEL_CLASS_NAMES.textMuted} role="status">
          {RUN_LEDGER_LOADING}
        </p>
      ) : null}

      {ledgerStatus === "error" ? (
        <p className="run-ledger__error" role="status">
          {RUN_LEDGER_LOAD_ERROR}
        </p>
      ) : null}

      {ledger.sections.waitingOnYou.length > 0 ? (
        <section aria-labelledby={`${panelId}-waiting-heading`}>
          <h2 className="run-ledger__section-heading" id={`${panelId}-waiting-heading`}>
            {RUN_LEDGER_SECTION_TITLES.waitingOnYou}
          </h2>
          <div className="run-ledger__cards">
            {ledger.sections.waitingOnYou.map((run) => (
              <WaitingOnYouCard key={run.id} run={run} />
            ))}
          </div>
        </section>
      ) : null}

      {ledger.sections.running.length > 0 ? (
        <section aria-labelledby={`${panelId}-running-heading`}>
          <h2 className="run-ledger__section-heading" id={`${panelId}-running-heading`}>
            {RUN_LEDGER_SECTION_TITLES.running}
          </h2>
          <div className="run-ledger__cards">
            {ledger.sections.running.map((run) => (
              <RunningCard key={run.id} run={run} />
            ))}
          </div>
        </section>
      ) : null}

      {ledger.sections.finished.length > 0 ? (
        <section aria-labelledby={`${panelId}-finished-heading`}>
          <h2 className="run-ledger__section-heading" id={`${panelId}-finished-heading`}>
            {RUN_LEDGER_SECTION_TITLES.finished}
          </h2>
          <div className="run-ledger__cards">
            {ledger.sections.finished.map((run) => (
              <FinishedRunCard key={run.id} run={run} />
            ))}
          </div>
        </section>
      ) : null}

      {/* Legacy mock execution list — the other 10 workflows, unchanged. */}
      {hasAnyMockRecords ? (
        <div className="execution-cards-container">
          {executionRecords.map((record) => (
            <ExecutionProgressCard
              key={record.executionId}
              record={record}
              onCancel={handleCancelExecution}
              repeatConsentSurface={repeatConsentSurfaces[record.executionId]}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
