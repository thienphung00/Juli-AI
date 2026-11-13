"use client";

import { useState } from "react";

import type { PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import type { BuilderP98Api, KolResponse } from "../../../lib/shopee-decisions/builder-p98-api";
import { errorText } from "../ui";
import { Field, ResultCards, num, vnd } from "../builder-p92/p98-shared";

export interface KolCandidate {
  readonly kol_key: string;
  readonly handle: string | null;
  /** "kol" (gets samples) or "cashback" / "coupon" (trang hoàn tiền / mã giảm giá). */
  readonly kind?: "kol" | "cashback" | "coupon";
}

export const CASHBACK_LABEL = "trang hoàn tiền / mã giảm giá";

interface Draft {
  items: readonly string[];
  commission: string;
  sampleOn: boolean;
  sampleItem: string;
  qty: string;
  ship: string;
}
const empty: Draft = { items: [], commission: "10", sampleOn: false, sampleItem: "", qty: "1", ship: "0" };

export function KolBuilder({ api, products, kols }: { readonly api: BuilderP98Api; readonly products: readonly PickerProduct[]; readonly kols: readonly KolCandidate[] }) {
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [drafts, setDrafts] = useState<Readonly<Record<string, Draft>>>({});
  const [data, setData] = useState<KolResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = (k: string): Draft => drafts[k] ?? empty;
  const patch = (k: string, p: Partial<Draft>) => setDrafts((d) => ({ ...d, [k]: { ...(d[k] ?? empty), ...p } }));
  const isCash = (k: string) => (kols.find((c) => c.kol_key === k)?.kind ?? "kol") !== "kol";
  const nameOf = (id: string) => products.find((p) => p.item_id === id)?.name ?? id;
  const toggleKol = (k: string) => setPicked(picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k]);
  const toggleItem = (k: string, id: string) => patch(k, { items: draft(k).items.includes(id) ? draft(k).items.filter((x) => x !== id) : [...draft(k).items, id] });

  const valid = picked.length > 0 && picked.every((k) => draft(k).items.length > 0 && num(draft(k).commission) !== null);
  const calc = () => {
    setBusy(true);
    api
      .kol({
        kols: picked.map((k) => {
          const d = draft(k);
          const sampleItem = d.sampleItem || d.items[0] || "";
          return {
            kol_key: k,
            item_ids: d.items,
            commission_pct: num(d.commission) ?? 0,
            ...(d.sampleOn && !isCash(k) && d.items.includes(sampleItem) ? { sample: { item_id: sampleItem, qty: num(d.qty) ?? 1, ship_fee: num(d.ship) ?? 0 } } : {}),
          };
        }),
      })
      .then(
        (r) => {
          setData(r);
          setError(null);
        },
        (e: unknown) => setError(errorText(e)),
      )
      .finally(() => setBusy(false));
  };

  return (
    <div className="sa-page" data-testid="kol-builder">
      <h2 className="sa-h1">Thiết lập KOL</h2>
      <section className="sa-card">
        <h3 className="sa-h2">① Chọn KOL</h3>
        <div className="sb-pills">
          {kols.map((k) => (
            <button aria-pressed={picked.includes(k.kol_key)} className={`sb-pill ${picked.includes(k.kol_key) ? "sb-pill--on" : ""}`} key={k.kol_key} onClick={() => toggleKol(k.kol_key)} type="button">
              {k.handle ?? k.kol_key}
              {k.kind && k.kind !== "kol" ? ` (${CASHBACK_LABEL})` : ""}
            </button>
          ))}
        </div>
      </section>
      {picked.map((k) => {
        const d = draft(k);
        const cash = isCash(k);
        return (
          <section className="sa-card" data-testid={`kol-setup-${k}`} key={k}>
            <h3 className="sa-h2">{kols.find((c) => c.kol_key === k)?.handle ?? k}</h3>
            {cash ? <p className="sa-hint">{CASHBACK_LABEL}: không gửi hàng mẫu.</p> : null}
            <div className="sb-pills">
              {products.slice(0, 40).map((p) => (
                <button aria-pressed={d.items.includes(p.item_id)} className={`sb-pill ${d.items.includes(p.item_id) ? "sb-pill--on" : ""}`} key={p.item_id} onClick={() => toggleItem(k, p.item_id)} type="button">
                  {p.name}
                </button>
              ))}
            </div>
            <Field label={`Hoa hồng ${k} (%)`}>
              <input inputMode="decimal" onChange={(e) => patch(k, { commission: e.target.value })} value={d.commission} />
            </Field>
            {cash ? null : (
              <>
                <label>
                  <input checked={d.sampleOn} onChange={(e) => patch(k, { sampleOn: e.target.checked })} type="checkbox" />
                  Gửi hàng mẫu
                </label>
                {d.sampleOn ? (
                  <div data-testid={`kol-sample-${k}`}>
                    <Field label="Sản phẩm mẫu">
                      <select onChange={(e) => patch(k, { sampleItem: e.target.value })} value={d.sampleItem || d.items[0] || ""}>
                        {d.items.map((id) => (
                          <option key={id} value={id}>
                            {nameOf(id)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Số lượng mẫu">
                      <input inputMode="numeric" onChange={(e) => patch(k, { qty: e.target.value })} value={d.qty} />
                    </Field>
                    <Field label="Phí ship (đ)">
                      <input inputMode="numeric" onChange={(e) => patch(k, { ship: e.target.value })} value={d.ship} />
                    </Field>
                  </div>
                ) : null}
              </>
            )}
          </section>
        );
      })}
      <button className="sa-btn sa-btn--primary" data-testid="kol-calc" disabled={!valid || busy} onClick={calc} type="button">
        Tính chi phí và hoà vốn
      </button>
      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <section className="sa-card" data-testid="kol-out">
          {data.setups.map((s) => (
            <div key={s.kol.kol_key}>
              <h3 className="sa-h3">
                {s.kol.handle ?? s.kol.kol_key} · hoa hồng {s.commission_pct}%
              </h3>
              {s.sample ? (
                <p>
                  Chi phí hàng mẫu: <b>{vnd(s.sample.cost)}</b> {s.sample.cost_note ? <span className="sa-hint">{s.sample.cost_note}</span> : null}
                </p>
              ) : (
                <p className="sa-hint">Không gửi hàng mẫu.</p>
              )}
            </div>
          ))}
          <ResultCards items={data.setups.map((s) => ({ title: s.kol.handle ?? s.kol.kol_key, result: s.result }))} />
        </section>
      ) : null}
    </div>
  );
}
