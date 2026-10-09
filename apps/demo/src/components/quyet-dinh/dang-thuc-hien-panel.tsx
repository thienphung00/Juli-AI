"use client";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { listChip, type Chip } from "../../lib/quyet-dinh/run-model";
import { RUN_LEDGER_EMPTY_STATE } from "../../lib/run-ledger/copy";
import { groupRunsIntoLedgerSections } from "../../lib/run-ledger/sections";

/**
 * "Hàng chờ thẻ tối ưu" — Run.dc.html's right column: one row per run
 * (SKU, product, status chip), the run waiting on the seller first, then
 * running, queued and finished ones. A row opens that run.
 */

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
}: {
  readonly runs: readonly QdRun[];
  readonly selectedId: string | null;
  /** The open run's live chip (its SSE phase), when known. */
  readonly selectedChip: Chip | null;
  readonly cardFor: (run: QdRun) => CardView | null;
  readonly onSelect: (runId: string) => void;
}) {
  const ordered = orderRuns(runs);
  return (
    <aside aria-labelledby="qd-queue" className="qv-queue" data-testid="run-queue">
      <h2 className="qv-queue__title" id="qd-queue">
        Hàng chờ thẻ tối ưu
      </h2>
      <p className="qv-queue__text">Juli chạy lần lượt, không bao giờ hai thay đổi cùng lúc trên một sản phẩm.</p>
      {ordered.length === 0 ? <p className="qv-queue__text">{RUN_LEDGER_EMPTY_STATE}</p> : null}
      <ul className="qv-queue__list">
        {ordered.map((run) => {
          const chip = run.id === selectedId && selectedChip ? selectedChip : listChip(run);
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
                  <span className={card?.sku ? "qv-queue__name" : "qv-queue__sku"}>{card?.title ?? run.product_name}</span>
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
