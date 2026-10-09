import { vnTime, type StepStatus, type TimelineStep } from "../../lib/quyet-dinh/timeline";
import { stageLabel, stageStates, type RunPhase } from "../../lib/quyet-dinh/run-model";

/**
 * The step list every Quyết định artboard shares (Run, RunPhoto, RunManual,
 * Revert, Day7, Day14): a 24 px dot (✓ done · number current/upcoming ·
 * "!" stopped), label 15/600, result 13, time right-aligned.
 */

const STATUS_TEXT: Readonly<Record<StepStatus | "warn", string>> = {
  done: "Xong",
  current: "Đang thực hiện",
  upcoming: "Sắp tới",
  failed: "Dừng",
  skipped: "Bỏ qua",
  warn: "Cần chú ý",
};

export interface StepRow {
  readonly key: string;
  readonly label: string;
  readonly status: StepStatus | "warn";
  readonly result: string | null;
  readonly time: string;
  readonly who?: "juli" | "you";
}

export function timelineRows(steps: readonly TimelineStep[]): StepRow[] {
  return steps.map((step) => ({
    key: step.key,
    label: step.label,
    status: step.status,
    result: step.detail,
    time: step.status === "upcoming" || step.status === "skipped" ? "" : vnTime(step.at),
    who: step.who,
  }));
}

export function StepList({
  rows,
  wide = false,
  label = "Các bước của lượt chạy",
  testId = "run-timeline",
}: {
  readonly rows: readonly StepRow[];
  readonly wide?: boolean;
  readonly label?: string;
  readonly testId?: string;
}) {
  return (
    <ol aria-label={label} className={`qv-steps${wide ? " qv-steps--wide" : ""}`} data-testid={testId}>
      {rows.map((row, index) => {
        const mark = row.status === "done" ? "✓" : row.status === "failed" || row.status === "warn" ? "!" : String(index + 1);
        return (
          <li
            aria-current={row.status === "current" ? "step" : undefined}
            className={`qv-step qv-step--${row.status}`}
            data-status={row.status}
            key={row.key}
          >
            <span aria-hidden="true" className="qv-step__dot">
              {mark}
            </span>
            <div className="qv-step__body">
              <span className="qv-step__label">
                {row.label}
                {row.who ? (
                  <>
                    {" "}
                    <span className={`qv-who-tag qv-who-tag--${row.who}`}>{row.who === "you" ? "Bạn" : "Juli"}</span>
                  </>
                ) : null}
                <span className="qv-sr"> — {STATUS_TEXT[row.status]}</span>
              </span>
              <span className="qv-step__result">{row.result ?? ""}</span>
            </div>
            <span className="qv-step__time">{row.time}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function StageChips({ phase, label }: { readonly phase: RunPhase; readonly label: string }) {
  const states = stageStates(phase);
  return (
    <ol aria-label={label} className="qv-stages" data-testid="stage-chips">
      {states.map((state, index) => (
        <li aria-current={state === "cur" ? "step" : undefined} className={`qv-stage qv-stage--${state}`} key={index}>
          {stageLabel(index, state)}
        </li>
      ))}
    </ol>
  );
}

/** The chevron of Run.dc.html's Thu gọn / Mở rộng. */
export function Chevron({ up }: { readonly up: boolean }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="14"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="14"
    >
      <path d={up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
    </svg>
  );
}
