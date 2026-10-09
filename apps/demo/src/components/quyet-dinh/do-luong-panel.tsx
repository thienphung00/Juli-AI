"use client";

import type { WorkflowRunListItem } from "@juli/contracts";

import {
  KEEP_CHANGE_LABEL,
  MEASURE_NO_READING,
  MEASURE_WAITING,
  REVERT_LABEL,
  bandMetricLabel,
} from "../../lib/quyet-dinh/copy";
import { addDays, vnDate } from "../../lib/quyet-dinh/timeline";
import type { RevertQuestion, RunChanges } from "../../lib/quyet-dinh/types";
import { num } from "../../lib/vn-format";

/**
 * Đo lường (ADR-109 d.11/d.13): one row per executed run — the product, the
 * fields Juli changed, and "Đang chờ đủ 7 ngày dữ liệu · đo lúc dd/mm/yyyy"
 * until day 7 (D14). No reading API exists for this screen yet, so no number
 * is shown (DEBT P8-F). Day-7 band breaches arrive as "Hoàn tác?" questions:
 * "Hoàn tác" starts the ordinary revert run, "Giữ thay đổi" dismisses —
 * Juli never undoes on its own. No "giờ nhân sự".
 */

export type ChangesState =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly changes: RunChanges };

export type QuestionActionState = { readonly busy: boolean; readonly message: string | null };

/** A run that finished normally (it may have written); revert runs drop out once their changes load. */
export function isExecutedRun(run: WorkflowRunListItem): boolean {
  return run.status === "completed" && run.stop_reason === "final_response";
}

export function measurementLine(completedAt: string | null, nowMs: number | null): string {
  if (!completedAt) return MEASURE_NO_READING;
  const day7 = addDays(completedAt, 7);
  if (!day7) return MEASURE_NO_READING;
  if (nowMs === null || nowMs < Date.parse(day7)) return MEASURE_WAITING(vnDate(day7));
  return MEASURE_NO_READING;
}

export function breachLine(breach: RevertQuestion["breaches"][number]): string {
  const sign = breach.impact_pct >= 0 ? "+" : "−";
  return `${bandMetricLabel(breach.metric)} lệch ${sign}${num(Math.abs(breach.impact_pct), 1)} % (ngưỡng ±${num(breach.band_pct, breach.band_pct % 1 ? 1 : 0)} %)`;
}

export function DoLuongPanel({
  runs,
  changesByRun,
  questions,
  questionStates,
  nowMs,
  onRevertQuestion,
  onDismissQuestion,
  onOpenRun,
}: {
  readonly runs: readonly WorkflowRunListItem[];
  readonly changesByRun: Readonly<Record<string, ChangesState>>;
  readonly questions: readonly RevertQuestion[];
  readonly questionStates: Readonly<Record<string, QuestionActionState>>;
  readonly nowMs: number | null;
  readonly onRevertQuestion: (question: RevertQuestion) => void;
  readonly onDismissQuestion: (question: RevertQuestion) => void;
  readonly onOpenRun: (runId: string) => void;
}) {
  const executed = runs.filter(isExecutedRun).filter((run) => {
    const state = changesByRun[run.id];
    if (state?.status !== "ready") return true;
    return state.changes.reverts_run_id === null && state.changes.changes.length > 0;
  });
  const productOf = (runId: string) => runs.find((run) => run.id === runId)?.product_name ?? "Sản phẩm";

  return (
    <div className="qd-dl">
      {questions.length > 0 ? (
        <section aria-labelledby="qd-questions" className="card qd-questions" data-testid="revert-questions">
          <h2 className="qd-side-card__title" id="qd-questions">
            Hoàn tác?
          </h2>
          <p className="qd-muted">Ngày thứ 7, các chỉ số dưới đây vượt ngưỡng giữ ổn định bạn đặt. Juli không tự hoàn tác — bạn quyết định.</p>
          <ul className="qd-questions__list">
            {questions.map((question) => {
              const state = questionStates[question.id] ?? { busy: false, message: null };
              return (
                <li className="qd-question" data-question-id={question.id} key={question.id}>
                  <p className="qd-question__product">{productOf(question.run_id)}</p>
                  <ul className="qd-question__breaches">
                    {question.breaches.map((breach) => (
                      <li key={breach.metric}>{breachLine(breach)}</li>
                    ))}
                  </ul>
                  {question.revert_run_id ? (
                    <button className="btn-secondary" onClick={() => onOpenRun(question.revert_run_id!)} type="button">
                      Xem lượt hoàn tác
                    </button>
                  ) : (
                    <div className="qd-question__actions">
                      <button className="btn-primary" disabled={state.busy} onClick={() => onRevertQuestion(question)} type="button">
                        {REVERT_LABEL}
                      </button>
                      <button className="btn-secondary" disabled={state.busy} onClick={() => onDismissQuestion(question)} type="button">
                        {KEEP_CHANGE_LABEL}
                      </button>
                    </div>
                  )}
                  {state.message ? (
                    <p className="qd-error" role="alert">
                      {state.message}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="qd-measure" className="card qd-measure" data-testid="measure-list">
        <h2 className="qd-side-card__title" id="qd-measure">
          Thay đổi đang được đo
        </h2>
        {executed.length === 0 ? (
          <p className="qd-muted">Chưa có lượt chạy nào ghi thay đổi lên TikTok Shop.</p>
        ) : (
          <ul className="qd-measure__list">
            {executed.map((run) => {
              const state = changesByRun[run.id];
              const fields =
                state?.status === "ready"
                  ? state.changes.changes.map((change) => change.label).join(", ")
                  : state?.status === "error"
                    ? "Không tải được các trường đã đổi"
                    : "Đang tải…";
              return (
                <li className="qd-measure__row" data-run-id={run.id} key={run.id}>
                  <button className="qd-measure__product" onClick={() => onOpenRun(run.id)} type="button">
                    {run.product_name}
                  </button>
                  <span className="qd-measure__fields">{fields}</span>
                  <span className="qd-measure__when">
                    Xong {vnDate(run.completed_at)} · {measurementLine(run.completed_at, nowMs)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
