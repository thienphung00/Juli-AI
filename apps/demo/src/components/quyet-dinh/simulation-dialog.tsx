"use client";

import { useEffect, useId, useState } from "react";

import { REVIEWER_CONTINUE_LABEL, REVIEWER_EXECUTE_LABEL, REVIEWER_SIMULATED_LABEL } from "../../lib/reviewer/copy";
import type { SimulationResult, SimulationStep } from "../../lib/reviewer/simulation-types";

/**
 * The partner trial account's simulated Duyệt → Thực thi dialog (fast track
 * P32-A, contract p32-reviewer-access.md §4, AC-32.5 / AC-32.7). "Duyệt" on a
 * card opens it: the approve step is simulated at once, then "Thực thi (mô
 * phỏng)" shows the change Juli would make — operation, product, each field
 * before → after, one short line — and sends nothing. P41 (D47.7): no endpoint,
 * method or operation name on screen (the response still carries `request`);
 * the label "Mô phỏng · không gửi tới TikTok" is the single disclaimer.
 *
 * No call site of its own: `simulate` is the API simulation for a pinned shop
 * (`reviewer-simulation.tsx`) or the in-memory sample one (P32-D,
 * `lib/reviewer/sample-simulation.ts`), so the sample door's module graph
 * stays free of any request (`replay-module-graph.test.ts`).
 */

export type Simulate = (cardId: string, step: SimulationStep) => Promise<SimulationResult>;

type State =
  | { status: "loading"; step: SimulationStep; previous: SimulationResult | null }
  | { status: "ready"; result: SimulationResult }
  | { status: "error"; message: string; previous: SimulationResult | null };

const ERROR_COPY = "Chưa mô phỏng được thẻ này. Vui lòng thử lại.";
const GONE_COPY = "Thẻ này không còn trong danh sách đề xuất.";

export function SimulationDialog({
  cardId,
  onClose,
  onContinue,
  simulate,
}: {
  readonly cardId: string;
  readonly onClose: () => void;
  /**
   * P32-E (sample shop only): after the simulated Thực thi, follow the card
   * through the in-memory sample run ("Theo dõi lượt chạy (mô phỏng) ›").
   */
  readonly onContinue?: () => void;
  readonly simulate: Simulate;
}) {
  const titleId = useId();
  const [state, setState] = useState<State>({ status: "loading", step: "approve", previous: null });

  const run = (step: SimulationStep, previous: SimulationResult | null) => {
    setState({ status: "loading", step, previous });
    simulate(cardId, step)
      .then((result) => setState({ status: "ready", result }))
      .catch((error: unknown) => {
        const status = (error as { status?: number } | null)?.status;
        setState({ status: "error", message: status === 404 ? GONE_COPY : ERROR_COPY, previous });
      });
  };

  useEffect(() => {
    const timer = window.setTimeout(() => run("approve", null), 0);
    return () => window.clearTimeout(timer);
    // One simulation per opened card.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId]);

  const result = state.status === "ready" ? state.result : state.previous;
  const executed = state.status === "ready" && state.result.step === "execute";
  const change = result?.change ?? null;

  return (
    <div className="qv-overlay" data-testid="reviewer-simulation">
      <div aria-labelledby={titleId} aria-modal="true" className="qv-dialog reviewer-sim" role="dialog">
        <p className="reviewer-sim__label" data-testid="reviewer-simulation-label">
          {REVIEWER_SIMULATED_LABEL}
        </p>
        <h3 className="qv-dialog__title" id={titleId}>
          {executed ? "Thay đổi Juli sẽ gửi" : "Đã duyệt (mô phỏng)"}
        </h3>

        <ol className="reviewer-sim__steps">
          <li data-done={result ? "true" : "false"}>{result ? "✓ " : ""}Duyệt</li>
          <li data-done={executed ? "true" : "false"}>{executed ? "✓ " : ""}Thực thi</li>
        </ol>

        {change ? (
          <dl className="reviewer-sim__facts">
            <dt>Thao tác</dt>
            <dd>{change.lever.label}</dd>
            {change.product.title ? (
              <>
                <dt>Sản phẩm</dt>
                <dd>{change.product.title}</dd>
              </>
            ) : null}
          </dl>
        ) : null}

        {executed && change ? (
          <div className="reviewer-sim__change" data-testid="reviewer-simulation-change">
            {change.fields.length > 0 ? (
              <table className="reviewer-sim__fields">
                <thead>
                  <tr>
                    <th scope="col">Mục</th>
                    <th scope="col">Trước</th>
                    <th scope="col">Sau</th>
                  </tr>
                </thead>
                <tbody>
                  {change.fields.map((field) => (
                    <tr key={field.field}>
                      <th scope="row">{field.label}</th>
                      <td>{field.before ?? "—"}</td>
                      <td>{field.after ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {change.note ? <p className="qv-dialog__body reviewer-sim__note">{change.note}</p> : null}
          </div>
        ) : null}

        {state.status === "loading" ? (
          <p className="qv-status-line" role="status">
            {state.step === "approve" ? "Đang mô phỏng Duyệt…" : "Đang mô phỏng Thực thi…"}
          </p>
        ) : null}
        {state.status === "error" ? (
          <p className="qv-inline-error" role="alert">
            {state.message}
          </p>
        ) : null}

        <div className="qv-dialog__actions">
          {!executed ? (
            <button
              className="qv-btn qv-btn--primary"
              disabled={state.status !== "ready" || state.result.step !== "approve"}
              onClick={() => state.status === "ready" && run("execute", state.result)}
              type="button"
            >
              {REVIEWER_EXECUTE_LABEL}
            </button>
          ) : null}
          {executed && onContinue ? (
            <button className="qv-btn qv-btn--primary" onClick={onContinue} type="button">
              {REVIEWER_CONTINUE_LABEL}
            </button>
          ) : null}
          <button className="qv-btn qv-btn--secondary" onClick={onClose} type="button">
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}
