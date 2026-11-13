"use client";

import type { ReactNode } from "react";

import type { Forms, Kind92 } from "../../../lib/shopee-decisions/builder-p92";
import { MAX_VERSIONS } from "../../../lib/shopee-decisions/builder-p92";
import type { Entry } from "./compare";
import { AdsPanel } from "./panels-listing";
import { OutcomeBody, VersionResult, adsTitle, type ResultState } from "./results";
import type { PanelCtx } from "./shared";

/**
 * Step ③ Phương án (artboard Flow3): the version being edited on the left (the ads panel is drawn here, every
 * other kind's panel comes as `children`), the saved versions as P1…Pn rows, and the live result on the right.
 */

export interface StepPhuongAnProps {
  readonly kind: Kind92;
  readonly kindLabel: string;
  readonly productName: string;
  readonly forms: Forms;
  readonly setForm: <K extends Kind92>(k: K, patch: Partial<Forms[K]>) => void;
  readonly ctx: PanelCtx;
  readonly state: ResultState;
  readonly costLink: string;
  /** P-number − 1 of the version being edited. */
  readonly index: number;
  readonly editing: number | null;
  readonly entries: readonly Entry[];
  readonly entriesCount?: number;
  readonly canAdd: boolean;
  readonly onUntick: (id: string) => void;
  readonly onAdd: () => void;
  readonly onReset: () => void;
  readonly onBack: () => void;
  readonly onSelect?: (i: number) => void;
  readonly onRemove?: (i: number) => void;
  readonly onNext?: () => void;
  /** The panel of every kind but ads. */
  readonly children?: ReactNode;
}

export function StepPhuongAn(p: StepPhuongAnProps) {
  const { state, entries, editing, index } = p;
  const outcome = state.status === "ready" ? state.outcome : null;
  const result = outcome?.ok ? outcome.result : undefined;
  const finding = result ? adsTitle(result) : null;
  const rows = entries.map((e, i) => ({ key: e.id, i, label: String(e.version.label ?? e.kind), on: editing === i }));
  const pending = editing === null;
  const full = entries.length >= MAX_VERSIONS;
  const addDisabled = !p.canAdd || state.status !== "ready" || !state.outcome.ok || (editing === null && full);
  return (
    <section className="p3" data-testid="p3-step">
      <div className="p3-head">
        <div className="sa-eyebrow">{p.kindLabel.toUpperCase()}</div>
        <h2 className="sa-h2" data-testid="p3-title">
          {finding ?? p.productName}
        </h2>
      </div>
      <div className="p2-split">
        <div className="sa-card p2-inputs" data-testid="p2-inputs">
          {p.kind === "ads" ? <AdsPanel ctx={p.ctx} form={p.forms.ads} set={(patch) => p.setForm("ads", patch)} /> : p.children}
          <ul className="p3-versions" data-testid="p3-versions">
            {rows.map((r) => (
              <li key={r.key}>
                <button aria-current={r.on ? "true" : undefined} className={`p3-version ${r.on ? "p3-version--on" : ""}`} data-testid={`p3-version-${r.i + 1}`} onClick={() => p.onSelect?.(r.i)} type="button">
                  <b>P{r.i + 1}</b> <span>{r.label}</span>
                </button>
                {p.onRemove ? (
                  <button aria-label={`Xoá P${r.i + 1}`} className="sa-link p2-linkbtn" onClick={() => p.onRemove?.(r.i)} type="button">
                    Xoá
                  </button>
                ) : null}
              </li>
            ))}
            {pending ? (
              <li>
                <span className="p3-version p3-version--on" data-testid={`p3-version-${index + 1}`}>
                  <b>P{index + 1}</b> <span>{outcome?.label ?? ""}</span>
                </span>
              </li>
            ) : null}
          </ul>
          <div className="sd-actions">
            <button className="sa-btn" data-testid="p2-add" disabled={addDisabled} onClick={p.onAdd} type="button">
              {editing !== null ? `Cập nhật P${editing + 1}` : "+ Thêm phương án"}
            </button>
            <button className="sa-btn" onClick={p.onReset} type="button">
              Đặt lại
            </button>
          </div>
        </div>
        <section aria-label={`Kết quả P${index + 1}`} className="sa-card p2-result" data-testid="p2-result">
          {state.status === "idle" ? <p className="sa-hint">{state.problem ?? "—"}</p> : null}
          {state.status === "busy" ? (
            <p className="sa-hint" role="status">
              Đang tính…
            </p>
          ) : null}
          {state.status === "error" ? (
            <p className="sd-error" role="alert">
              {state.message}
            </p>
          ) : null}
          {outcome && result ? <VersionResult name={`P${index + 1} · ${outcome.label}`} outcome={outcome} result={result} /> : null}
          {outcome && !result ? <OutcomeBody costLink={p.costLink} onUntick={p.onUntick} outcome={outcome} /> : null}
        </section>
      </div>
      <div className="p3-foot">
        <button className="sa-link p2-linkbtn" onClick={p.onBack} type="button">
          Đổi chiến lược
        </button>
        {p.onNext ? (
          <button className="sa-btn sa-btn--primary" data-testid="p3-next" disabled={entries.length === 0} onClick={p.onNext} type="button">
            So sánh {entries.length} phương án
          </button>
        ) : null}
      </div>
    </section>
  );
}
