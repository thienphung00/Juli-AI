"use client";

import { METRIC_LABELS, STRATEGY_GROUPS, kindName92, type Kind92, type MetricKey } from "../../../lib/shopee-decisions/builder-p92";

/** Step ② Chiến lược (artboard Flow2): three groups, each with its metric chips; "Chi phí" only where it costs. */

export function MetricChip({ metric }: { readonly metric: MetricKey }) {
  return <span className={`p2-m p2-m--${metric}`}>{METRIC_LABELS[metric]}</span>;
}

export function StepChienLuoc({
  kinds,
  selected,
  onSelect,
  onBack,
  onNext,
}: {
  readonly kinds: ReadonlySet<Kind92>;
  readonly selected: Kind92 | null;
  readonly onSelect: (k: Kind92) => void;
  readonly onBack: () => void;
  readonly onNext: () => void;
}) {
  return (
    <section data-testid="p2-kinds">
      <div className="p2-groups">
        {STRATEGY_GROUPS.map((g) => {
          const items = g.kinds.filter((k) => kinds.has(k.key));
          if (items.length === 0) return null;
          return (
            <section className="p2-group" data-testid={`p2-group-${g.key}`} key={g.key}>
              <div>
                <h2 className="sa-h2">{g.title}</h2>
                <div className="p2-group__metrics">
                  {g.metrics.map((m) => (
                    <MetricChip key={m} metric={m} />
                  ))}
                </div>
                {g.cost ? (
                  <div className="sa-hint">
                    <b>Chi phí:</b> {g.cost}
                  </div>
                ) : null}
              </div>
              {items.map((k) => (
                <button aria-pressed={selected === k.key} className={`p2-kind ${selected === k.key ? "p2-kind--on" : ""}`} data-testid={`p2-kind-${k.key}`} key={k.key} onClick={() => onSelect(k.key)} type="button">
                  <b>{kindName92(k.key)}</b>
                  <span>{k.what}</span>
                </button>
              ))}
            </section>
          );
        })}
      </div>
      <div className="p2-foot">
        <button className="sa-link p2-linkbtn" onClick={onBack} type="button">
          Quay lại
        </button>
        <button className="sa-btn sa-btn--primary" data-testid="p2-knext" disabled={!selected} onClick={onNext} type="button">
          {selected ? `Tiếp tục với ${kindName92(selected)}` : "Tiếp tục"}
        </button>
      </div>
    </section>
  );
}
