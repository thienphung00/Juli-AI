"use client";

import { useEffect, useState, type ReactNode } from "react";

import type { BuilderApi, BuilderOutcome, PickerProduct, VariationRow } from "../../../lib/shopee-decisions/builder-api";
import { useVariationList } from "./variations";

/** Small form pieces of the P92 builder (classes in `app/shopee-p92.css`). */

export function Field({ label, hint, children, wide }: { readonly label: string; readonly hint?: ReactNode; readonly children: ReactNode; readonly wide?: boolean }) {
  return (
    <label className={`p2-field ${wide ? "p2-field--wide" : ""}`}>
      <span className="sd-field__label">{label}</span>
      {children}
      {hint ? <span className="sa-hint">{hint}</span> : null}
    </label>
  );
}

/** A typed number: the raw text is kept by the caller (no sliders, from 0). */
export function NumIn({ label, value, onChange, suffix, placeholder, hint, wide }: { readonly label: string; readonly value: string; readonly onChange: (v: string) => void; readonly suffix?: string; readonly placeholder?: string; readonly hint?: ReactNode; readonly wide?: boolean }) {
  return (
    <Field hint={hint} label={label} wide={wide}>
      <span className="p2-num">
        <input aria-label={label} inputMode="decimal" onChange={(e) => onChange(e.target.value)} placeholder={placeholder} type="text" value={value} />
        {suffix ? <span className="p2-num__suffix">{suffix}</span> : null}
      </span>
    </Field>
  );
}

export function TextIn({ label, value, onChange, placeholder, hint, type = "text", wide }: { readonly label: string; readonly value: string; readonly onChange: (v: string) => void; readonly placeholder?: string; readonly hint?: ReactNode; readonly type?: "text" | "date" | "datetime-local"; readonly wide?: boolean }) {
  return (
    <Field hint={hint} label={label} wide={wide}>
      <input aria-label={label} className="p2-text" onChange={(e) => onChange(e.target.value)} placeholder={placeholder} type={type} value={value} />
    </Field>
  );
}

export function Seg<T extends string>({ label, value, options, onChange }: { readonly label: string; readonly value: T; readonly options: readonly (readonly [T, string])[]; readonly onChange: (v: T) => void }) {
  return (
    <div className="p2-field">
      <span className="sd-field__label">{label}</span>
      <div aria-label={label} className="sa-seg sa-seg--round p2-seg" role="group">
        {options.map(([k, text]) => (
          <button aria-pressed={value === k} className={`sa-seg__item ${value === k ? "sa-seg__item--on" : ""}`} key={k} onClick={() => onChange(k)} type="button">
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Pills<T extends string>({ label, value, options, onChange }: { readonly label: string; readonly value: T; readonly options: readonly (readonly [T, string])[]; readonly onChange: (v: T) => void }) {
  return (
    <div className="p2-field">
      <span className="sd-field__label">{label}</span>
      <div className="sb-chips" role="radiogroup" aria-label={label}>
        {options.map(([k, text]) => (
          <button aria-checked={value === k} className={`sb-pill ${value === k ? "sb-pill--on" : ""}`} key={k} onClick={() => onChange(k)} role="radio" type="button">
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Replace row `i` of a list. */
export function setAt<T>(list: readonly T[], i: number, patch: Partial<T>): T[] {
  return list.map((x, k) => (k === i ? { ...x, ...patch } : x));
}


/** What every kind panel gets besides its own form. */
export interface PanelCtx {
  readonly api: BuilderApi;
  readonly product: PickerProduct;
  /** The variations chosen in step 2. */
  readonly variations: readonly VariationRow[];
  /** Every active listing (for combo partners, add-ons, gifts). */
  readonly products: readonly PickerProduct[];
  readonly aov: number | null;
  readonly outcome: BuilderOutcome | null;
  readonly narrow: boolean;
  readonly costLink: string;
}

export function ProductSelect({ label, value, onChange, products, allowEmpty = true }: { readonly label: string; readonly value: string; readonly onChange: (id: string) => void; readonly products: readonly PickerProduct[]; readonly allowEmpty?: boolean }) {
  return (
    <select aria-label={label} className="p2-select" onChange={(e) => onChange(e.target.value)} value={value}>
      {allowEmpty ? <option value="">—</option> : null}
      {products.map((p) => (
        <option key={p.item_id} value={p.item_id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

/** The variations of one listing as a select; picks the first one by itself when none is set. */
export function VariationSelect({ api, itemId, value, onChange, label }: { readonly api: BuilderApi; readonly itemId: string; readonly value: string; readonly onChange: (id: string) => void; readonly label: string }) {
  const state = useVariationList(itemId ? api : undefined, itemId || null);
  const rows = state.status === "ready" ? state.data.variations : [];
  const first = rows[0]?.variation_id;
  useEffect(() => {
    if (state.status === "ready" && first !== undefined && !rows.some((r) => r.variation_id === value)) onChange(first);
    // Only when the list arrives or the product changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status, itemId]);
  if (!itemId) return <span className="sd-muted">—</span>;
  return (
    <select aria-label={label} className="p2-select" disabled={rows.length === 0} onChange={(e) => onChange(e.target.value)} value={value}>
      {rows.length === 0 ? <option value="">Đang tải…</option> : null}
      {rows.map((r) => (
        <option key={r.variation_id || "default"} value={r.variation_id}>
          {r.name}
        </option>
      ))}
    </select>
  );
}

/** A draft call (LLM): idle / busy / ready / failed; `off` when the model is off (503 `llm_off`). */
export type Draft<T> = { readonly status: "idle" } | { readonly status: "busy" } | { readonly status: "ready"; readonly data: T } | { readonly status: "off"; readonly message: string } | { readonly status: "error"; readonly message: string };

export function useDraft<T>(run: () => Promise<T>): [Draft<T>, () => void] {
  const [state, setState] = useState<Draft<T>>({ status: "idle" });
  const go = () => {
    setState({ status: "busy" });
    run().then(
      (data) => setState({ status: "ready", data }),
      (e: unknown) => {
        const code = (e as { code?: string } | null)?.code;
        const status = (e as { status?: number } | null)?.status;
        const message = e instanceof Error ? e.message : "";
        if (code === "llm_off" || status === 503) setState({ status: "off", message: message || "LLM tắt" });
        else if (code === "llm_no_valid_draft") setState({ status: "error", message: "Chưa có bản nháp nào đạt kiểm tra (quá dài, thiếu từ khoá hoặc có thông tin shop chưa cung cấp). Thử lại hoặc tự viết." });
        else setState({ status: "error", message: message || "Chưa tạo được bản nháp. Thử lại sau ít phút." });
      },
    );
  };
  return [state, go];
}

export function LlmOff({ message }: { readonly message: string }) {
  return (
    <p className="sd-check sd-check--bad p2-llmoff" data-testid="p2-llm-off" role="status">
      <span>
        <b>{message || "LLM tắt"}.</b> Bạn vẫn tự viết ở ô bên dưới; Juli kiểm giới hạn ký tự và từ khoá.
      </span>
    </p>
  );
}
