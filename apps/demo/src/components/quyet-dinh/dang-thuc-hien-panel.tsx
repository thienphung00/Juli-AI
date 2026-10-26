"use client";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { shortProductName } from "../../lib/quyet-dinh/product-name";
import { isTerminalRun, listChip, type Chip } from "../../lib/quyet-dinh/run-model";
import { useSandboxReviewer } from "../../lib/reviewer/mode";
import { RUN_LEDGER_EMPTY_STATE } from "../../lib/run-ledger/copy";
import { groupRunsIntoLedgerSections } from "../../lib/run-ledger/sections";

/**
 * "Hàng chờ" — Run.dc.html's right column: one row per run
 * (SKU, product, status chip), the run waiting on the seller first, then
 * running, queued and finished ones. A row opens that run.
 */

/** Finished runs older than this leave the queue (their history stays in Đo lường / the run page). */
export const QUEUE_FINISHED_DAYS = 14;
const DAY_MS = 24 * 60 * 60 * 1000;

function timeMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/**
 * The runs the queue shows: every live run, plus finished runs from the last
 * {@link QUEUE_FINISHED_DAYS} days -- and of a card's runs only its latest
 * (a card retried after a failure shows once, not once per attempt). The run
 * the seller has open always stays. `nowMs` null (first render) skips the age rule.
 */
export function queueRuns(runs: readonly QdRun[], nowMs: number | null, keepId: string | null = null): QdRun[] {
  const latestByCard = new Map<string, QdRun>();
  for (const run of runs) {
    if (!run.decision_id) continue;
    const seen = latestByCard.get(run.decision_id);
    if (!seen || (timeMs(run.created_at) ?? 0) > (timeMs(seen.created_at) ?? 0)) latestByCard.set(run.decision_id, run);
  }
  return runs.filter((run) => {
    if (run.id === keepId || !isTerminalRun(run)) return true;
    if (run.decision_id && latestByCard.get(run.decision_id)?.id !== run.id) return false;
    if (nowMs === null) return true;
    const ended = timeMs(run.completed_at) ?? timeMs(run.created_at);
    return ended !== null && nowMs - ended <= QUEUE_FINISHED_DAYS * DAY_MS;
  });
}

export function orderRuns(runs: readonly QdRun[]): QdRun[] {
  const sections = groupRunsIntoLedgerSections(runs);
  const queued = sections.running.filter((run) => run.status === "queued");
  const running = sections.running.filter((run) => run.status !== "queued");
  return [...sections.waitingOnYou, ...running, ...queued, ...sections.finished] as QdRun[];
}

export function RunQueue({
  runs,
  selectedId,
  selectedChip,
  cardFor,
  onSelect,
  nowMs = null,
}: {
  readonly runs: readonly QdRun[];
  /** Wall clock for the 14-day rule; null shows every finished run. */
  readonly nowMs?: number | null;
  readonly selectedId: string | null;
  /** The open run's live chip (its SSE phase), when known. */
  readonly selectedChip: Chip | null;
  readonly cardFor: (run: QdRun) => CardView | null;
  readonly onSelect: (runId: string) => void;
}) {
  const ordered = orderRuns(queueRuns(runs, nowMs, selectedId));
  const sandboxShop = useSandboxReviewer();
  return (
    <aside aria-labelledby="qd-queue" className="qv-queue" data-testid="run-queue">
      <h2 className="qv-queue__title" id="qd-queue">
        Hàng chờ
      </h2>
      {ordered.length === 0 ? <p className="qv-queue__text">{RUN_LEDGER_EMPTY_STATE}</p> : null}
      <ul className="qv-queue__list">
        {ordered.map((run) => {
          // The open run's live chip, unless the server already ended the run and
          // the live view still thinks it is going (never "Đang chạy" for a terminal run).
          const live = run.id === selectedId && selectedChip ? selectedChip : null;
          const chip = live && !(isTerminalRun(run) && live.label === "Đang chạy") ? live : listChip(run, sandboxShop);
          const card = cardFor(run);
          return (
            <li key={run.id}>
              <button
                aria-pressed={run.id === selectedId}
                className="qv-queue__row"
                data-run-id={run.id}
                onClick={() => onSelect(run.id)}
                type="button"
              >
                <span className="qv-queue__id">
                  {card?.sku ? <span className="qv-queue__sku">{card.sku}</span> : null}
                  <span
                    className={card?.sku ? "qv-queue__name" : "qv-queue__sku"}
                    title={card?.fullTitle ?? run.product_name}
                  >
                    {card?.title ?? shortProductName(run.product_name)}
                  </span>
                </span>
                <span className={`qv-chip qv-tone--${chip.tone}`}>{chip.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
