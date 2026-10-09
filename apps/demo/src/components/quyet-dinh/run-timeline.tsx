import type { ReactNode } from "react";

import { vnTime, type TimelineStep } from "../../lib/quyet-dinh/timeline";

const STATUS_TEXT: Readonly<Record<TimelineStep["status"], string>> = {
  done: "Xong",
  current: "Đang thực hiện",
  upcoming: "Sắp tới",
  failed: "Dừng",
};

/**
 * The vertical step timeline of the video's execution screen (master cut
 * 1:23): done ✓ / current (pink, spinner) / upcoming greyed, each with its
 * event time and one-line result. Rows come from `buildRunTimeline` — this
 * component formats, it does not derive. `consent` renders inline under the
 * consent step while the run waits on the seller.
 */
export function RunTimeline({
  steps,
  consent,
}: {
  readonly steps: readonly TimelineStep[];
  readonly consent?: ReactNode;
}) {
  return (
    <ol aria-label="Các bước của lượt chạy" className="qd-timeline" data-testid="run-timeline">
      {steps.map((step, index) => {
        const number = index + 1;
        const marker =
          step.status === "done" ? "✓" : step.status === "failed" ? "!" : step.status === "current" ? "" : String(number);
        return (
          <li
            aria-current={step.status === "current" ? "step" : undefined}
            className={`qd-step qd-step--${step.status}`}
            data-kind={step.kind}
            data-status={step.status}
            key={step.key}
          >
            <span aria-hidden="true" className="qd-step__marker">
              {step.status === "current" ? <span className="qd-spinner" /> : marker}
            </span>
            <div className="qd-step__body">
              <div className="qd-step__row">
                <p className="qd-step__label">
                  {step.label}
                  <span className="qd-sr"> — {STATUS_TEXT[step.status]}</span>
                </p>
                {step.at ? (
                  <time className="qd-step__time" dateTime={step.at}>
                    {vnTime(step.at)}
                  </time>
                ) : null}
              </div>
              {step.detail ? <p className="qd-step__detail">{step.detail}</p> : null}
              {step.kind === "consent" && step.status === "current" && consent ? (
                <div className="qd-step__consent">{consent}</div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
