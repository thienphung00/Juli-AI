import { FIVE_STAGES } from "../../lib/quyet-dinh/copy";
import type { StageState } from "../../lib/quyet-dinh/batch";

const STATE_TEXT: Readonly<Record<StageState, string>> = {
  done: "xong",
  current: "đang ở bước này",
  todo: "chưa tới",
  failed: "dừng ở bước này",
};

/**
 * The five-stage stepper (ADR-109 d.8): Phân tích → Đề xuất → Duyệt → Thực
 * thi → Đo lường, on ONE card group or ONE run, showing that group's/run's
 * own state. Never in the global header.
 */
export function FiveStageStepper({ states, label }: { readonly states: readonly StageState[]; readonly label: string }) {
  return (
    <ol aria-label={label} className="qd-stepper">
      {FIVE_STAGES.map((stage, index) => {
        const state = states[index] ?? "todo";
        return (
          <li
            aria-current={state === "current" ? "step" : undefined}
            className={`qd-stepper__item qd-stepper__item--${state}`}
            key={stage}
          >
            <span aria-hidden="true" className="qd-stepper__dot">
              {state === "done" ? "✓" : state === "failed" ? "!" : index + 1}
            </span>
            <span className="qd-stepper__label">{stage}</span>
            <span className="qd-sr"> — {STATE_TEXT[state]}</span>
          </li>
        );
      })}
    </ol>
  );
}
