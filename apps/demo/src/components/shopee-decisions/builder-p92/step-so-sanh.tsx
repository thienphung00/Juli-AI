"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { DASH, fmt, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderApi, BuilderEvaluation, BuilderOutcome, ChooseResult, GroupResult } from "../../../lib/shopee-decisions/builder-api";
import { breachesOfOutcome } from "../../../lib/shopee-decisions/builder-p92";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import type { Breach } from "../../../lib/shopee-decisions/types";
import { ackText, breachWarnLines } from "../../../lib/shopee-decisions/versions";
import { NavLink, errorText } from "../ui";
import { BreachDialog } from "../versions";
import { perDayText, periodLabel, resultDays, signedCount, signedMoney } from "../option-card/format";
import { GROUP_MIN_DAYS, TogetherResult, type Entry } from "./compare";
import { verdictOf } from "./results";

/**
 * Step ④ So sánh & lưu (artboard Flow4): Δ lợi nhuận bars for the whole period (zero line in the middle, a gain
 * grey, a loss red), the table of Δ GMV · Chi phí · Đơn QC · CPA / hoà vốn · ROI · Kết luận, the main version
 * (the others are kept as phiên bản), "Đưa lên Quyết định ngay" and Lưu (`POST /builder/choose`).
 */

export interface StepSoSanhProps {
  readonly productName: string;
  readonly api: BuilderApi;
  readonly costLink: string;
  readonly entries: readonly Entry[];
  readonly narrow: boolean;
  readonly onAdd: () => void;
  /** Sửa phương án: back to step ③. */
  readonly onBack: () => void;
  readonly onEdit: (i: number) => void;
  readonly onRemove: (i: number) => void;
  readonly planHref: string | null;
  readonly readOnly: boolean;
  readonly staffDraft: boolean;
  readonly onSaved?: (r: ChooseResult) => void;
}

type Load = { readonly key: string; readonly state: { readonly status: "ready"; readonly result: BuilderEvaluation } | { readonly status: "error"; readonly message: string } };

interface Row {
  readonly i: number;
  readonly name: string;
  readonly outcome: BuilderOutcome | undefined;
  readonly r: OptionResult | null;
  readonly profit: number | null;
}

const profitOf = (r: OptionResult | null): number | null => (r && r.estimable ? (r.delta.profit?.value ?? null) : null);

/** Bar geometry: the zero line is at 50 %, the longest bar reaches an edge. */
export function barWidth(value: number, max: number): number {
  return max > 0 ? (Math.abs(value) / max) * 50 : 0;
}

function cpaText(r: OptionResult | null): string {
  const a = r?.ads;
  if (!a || a.break_even_cpa === null) return DASH;
  return `${a.cpa.after === null ? DASH : fmt(a.cpa.after, 0)} / ${fmt(a.break_even_cpa, 0)}`;
}

function ordersText(r: OptionResult | null): string {
  const a = r?.ads;
  if (!a || a.orders.after === null) return DASH;
  const d = a.orders.now === null ? null : a.orders.after - a.orders.now;
  return `${fmt(a.orders.after, 0)}${d === null ? "" : ` (${signedCount(d)})`}`;
}

function costText(r: OptionResult | null): string {
  if (!r) return DASH;
  const a = r.ads;
  if (a && a.spend.after !== null && a.spend.now !== null) return `${vnd(a.spend.after)} (${signedMoney(a.spend.after - a.spend.now)})`;
  return r.cost.total > 0 ? vnd(r.cost.total) : r.cost.total < 0 ? `Giảm ${vnd(-r.cost.total)}` : "0đ";
}

export function StepSoSanh(p: StepSoSanhProps) {
  const { api, entries } = p;
  const versions = useMemo(() => entries.map((e) => ({ ...e.version, label: e.version.label })), [entries]);
  const key = JSON.stringify(versions);
  const [load, setLoad] = useState<Load | null>(null);
  const seq = useRef(0);
  const [main, setMain] = useState<number | null>(null);
  const [primary, setPrimary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ readonly index: number; readonly result: ChooseResult; readonly ack: string | null } | null>(null);
  const [warn, setWarn] = useState<readonly Breach[] | null>(null);
  const [ticked, setTicked] = useState<readonly number[]>([]);
  const [daysText, setDaysText] = useState("7");
  const [startText, setStartText] = useState("");
  const [together, setTogether] = useState<GroupResult | null>(null);
  const [togetherWarn, setTogetherWarn] = useState<readonly Breach[] | null>(null);

  useEffect(() => {
    if (versions.length === 0) return;
    const n = ++seq.current;
    const call = versions.length >= 2 ? api.compare(versions) : api.evaluate(versions);
    call.then(
      (result) => n === seq.current && setLoad({ key, state: { status: "ready", result } }),
      (e: unknown) => n === seq.current && setLoad({ key, state: { status: "error", message: errorText(e) } }),
    );
    // `key` says the versions changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = load?.key === key ? load.state : null;
  const outcomes = current?.status === "ready" ? current.result.versions : [];
  const rows: Row[] = entries.map((_, i) => {
    const o = outcomes[i];
    const r = o?.ok && o.result ? o.result : null;
    return { i, name: `P${i + 1}`, outcome: o, r, profit: profitOf(r) };
  });
  const days = rows.find((x) => x.r)?.r ? resultDays(rows.find((x) => x.r)!.r!) : null;
  const best = rows.reduce<Row | null>((b, x) => (x.profit !== null && (b === null || x.profit > (b.profit ?? -Infinity)) ? x : b), null);
  const mainIndex = main !== null && main < entries.length ? main : (best?.i ?? 0);
  const max = Math.max(0, ...rows.map((x) => Math.abs(x.profit ?? 0)));
  const finding = !best
    ? null
    : (best.profit ?? 0) > 0
      ? `${best.name} lãi thêm nhiều nhất: ${signedMoney(best.profit)} trong ${days ?? "?"} ngày`
      : "Không phương án nào lãi thêm";

  const save = async (ack: boolean, breaches: readonly Breach[]) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.choose({ versions, chosen: mainIndex, primary, acknowledgeBreaches: ack });
      setWarn(null);
      setSaved({ index: mainIndex, result: out, ack: ack && breaches.length > 0 ? ackText(breaches, new Date().toISOString()) : null });
      p.onSaved?.(out);
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code === "reco_breach_not_acknowledged" && Array.isArray(e.detail?.["breaches"])) setWarn(e.detail["breaches"] as Breach[]);
      else setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const onSave = () => {
    const o = outcomes[mainIndex];
    const b = o ? (breachesOfOutcome(o) as Breach[]) : [];
    if (b.length > 0) setWarn(b);
    else void save(false, []);
  };
  const tickedNow = ticked.filter((i) => i < entries.length && outcomes[i]?.ok);
  const toggleTick = (i: number) => setTicked((t) => (t.includes(i) ? t.filter((x) => x !== i) : [...t, i].sort((a, b) => a - b)));
  const daysNum = Number(daysText);
  const daysProblem = !Number.isInteger(daysNum) || daysNum < GROUP_MIN_DAYS ? `Nhóm chạy ít nhất ${GROUP_MIN_DAYS} ngày.` : daysNum > 90 ? "Nhóm chạy tối đa 90 ngày." : null;
  const runTogether = async (ack: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.group({ versions, members: tickedNow, days: daysNum, start: startText || null, acknowledgeBreaches: ack });
      setTogetherWarn(null);
      setTogether(out);
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code === "reco_breach_not_acknowledged" && Array.isArray(e.detail?.["breaches"])) setTogetherWarn(e.detail["breaches"] as Breach[]);
      else setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const others = rows.filter((x) => x.i !== mainIndex).map((x) => x.name);
  const saveDisabled = p.readOnly || busy || saved !== null || !outcomes[mainIndex]?.ok;

  return (
    <section className="p4" data-testid="p4-step">
      <div className="p3-head">
        <div className="sa-eyebrow">SO SÁNH · {days ? periodLabel(days).toUpperCase() : p.productName.toUpperCase()}</div>
        <h2 className="sa-h2" data-testid="p4-title">
          {finding ?? p.productName}
        </h2>
      </div>
      {current === null ? (
        <p className="sa-hint" role="status">
          Đang tính…
        </p>
      ) : null}
      {current?.status === "error" ? (
        <p className="sd-error" role="alert">
          {current.message}
        </p>
      ) : null}
      {current?.status === "ready" ? (
        <>
          <div className="sa-card p4-bars" data-testid="p4-bars">
            <div className="p4-bars__title">Δ lợi nhuận {days ? periodLabel(days) : "cả kỳ"}</div>
            {rows.map((x) => {
              const per = perDayText(x.profit, x.r ? resultDays(x.r) : null);
              const loss = (x.profit ?? 0) < 0;
              return (
                <div className="p4-bar" data-testid={`p4-bar-${x.i + 1}`} key={x.i}>
                  <div className="p4-bar__name">
                    {x.name} · {String(entries[x.i]?.version.label ?? "")}
                  </div>
                  <div className="p4-bar__track">
                    <div className="p4-bar__zero" />
                    {x.profit !== null ? (
                      <div
                        className={`p4-bar__fill ${loss ? "p4-bar__fill--loss" : "p4-bar__fill--gain"}`}
                        data-sign={loss ? "loss" : "gain"}
                        data-testid={`p4-bar-fill-${x.i + 1}`}
                        style={loss ? { right: "50%", width: `${barWidth(x.profit, max)}%` } : { left: "50%", width: `${barWidth(x.profit, max)}%` }}
                      />
                    ) : null}
                  </div>
                  <div className="p4-bar__value">
                    <b className={loss ? "sa-tone--down" : "sa-tone--up"} data-testid={`p4-profit-${x.i + 1}`}>
                      {x.profit === null ? DASH : signedMoney(x.profit)}
                    </b>
                    {per ? <span className="sa-hint" data-testid={`p4-profit-perday-${x.i + 1}`}>{per}</span> : null}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="sa-card p4-table-wrap">
            <table className="sa-table p4-table" data-testid="p4-table">
              <thead>
                <tr>
                  <th>{days ? periodLabel(days) : "Cả kỳ"}</th>
                  <th>Δ GMV</th>
                  <th>Chi phí</th>
                  <th>Đơn QC</th>
                  <th>CPA / hoà vốn</th>
                  <th>ROI</th>
                  <th>Kết luận</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((x) => {
                  const v = x.r ? verdictOf(x.r) : null;
                  const gmvPer = x.r && x.r.estimable ? perDayText(x.r.delta.gmv.value, resultDays(x.r)) : null;
                  return (
                    <tr data-testid={`p4-row-${x.i + 1}`} key={x.i}>
                      <th scope="row">{x.name}</th>
                      <td data-testid={`p4-gmv-${x.i + 1}`}>
                        {x.r && x.r.estimable ? signedMoney(x.r.delta.gmv.value) : DASH}
                        {gmvPer ? <span className="sa-hint"> {gmvPer}</span> : null}
                      </td>
                      <td>{costText(x.r)}</td>
                      <td>{ordersText(x.r)}</td>
                      <td>{cpaText(x.r)}</td>
                      <td>{x.r?.roi?.value !== null && x.r?.roi?.value !== undefined ? fmt(x.r.roi.value, 2) : DASH}</td>
                      <td>{v ? <span className={`p3-verdict p3-verdict--${v.tone}`} data-testid={`p4-verdict-${x.i + 1}`}>{v.text}</span> : DASH}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      {current?.status === "ready" ? (
        <div className="sa-card p2-together" data-testid="p2-together">
          <h3 className="sa-h2">Chạy cùng nhau</h3>
          <div className="p4-main">
            {rows.map((x) => (
              <label className="p2-together__tick" key={x.i}>
                <input aria-label={`Chạy cùng nhau ${x.name}`} checked={ticked.includes(x.i)} disabled={!outcomes[x.i]?.ok || together !== null} onChange={() => toggleTick(x.i)} type="checkbox" /> {x.name}
              </label>
            ))}
          </div>
          <div className="p2-grid">
            <label className="p2-field">
              <span className="sd-field__label">Số ngày chạy (ít nhất {GROUP_MIN_DAYS})</span>
              <input aria-label="Số ngày của nhóm" className="p2-text" inputMode="numeric" onChange={(e) => setDaysText(e.target.value)} type="text" value={daysText} />
              {daysProblem ? <span className="sd-error">{daysProblem}</span> : null}
            </label>
            <label className="p2-field">
              <span className="sd-field__label">Bắt đầu</span>
              <input aria-label="Ngày bắt đầu của nhóm" className="p2-text" onChange={(e) => setStartText(e.target.value)} type="date" value={startText} />
            </label>
          </div>
          <div className="sd-actions">
            <button className="sa-btn sa-btn--primary" data-testid="p2-together-go" disabled={p.readOnly || busy || tickedNow.length < 1 || daysProblem !== null || together !== null} onClick={() => void runTogether(false)} type="button">
              Chạy cùng nhau ({tickedNow.length} phương án)
            </button>
          </div>
          {together ? <TogetherResult planHref={p.planHref} result={together} /> : null}
        </div>
      ) : null}
      <div className="sa-card p4-save">
        <div className="p4-main" role="radiogroup" aria-label="Phương án chính">
          {rows.map((x) => (
            <label className="sb-check" key={x.i}>
              <input checked={mainIndex === x.i} name="p4-main" onChange={() => setMain(x.i)} type="radio" value={x.i} /> {x.name} là phương án chính
            </label>
          ))}
        </div>
        {others.length > 0 ? (
          <div className="sa-hint" data-testid="p4-others">
            {others.join(" · ")} lưu làm phiên bản
          </div>
        ) : null}
        <label className="sb-check">
          <input checked={primary} onChange={() => setPrimary((v) => !v)} type="checkbox" /> Đưa lên Quyết định ngay
        </label>
        <div className="sd-actions">
          <button className="sa-btn" data-testid="p4-edit" onClick={p.onBack} type="button">
            Sửa phương án
          </button>
          <button className="sa-btn sa-btn--primary" data-testid="p4-save" disabled={saveDisabled} onClick={onSave} type="button">
            Lưu
          </button>
        </div>
        {err ? (
          <p className="sd-error" role="alert">
            {err}
          </p>
        ) : null}
        {saved ? (
          <div className="sa-notice sa-notice--info" data-testid="p4-saved" role="status">
            <b>
              Đã lưu · {saved.result.code ?? saved.result.id} · {rows[saved.index]?.name ?? `P${saved.index + 1}`} là phương án chính
            </b>
            {saved.result.status === "draft" || p.staffDraft ? " · nháp" : ""}
            {p.planHref ? (
              <>
                {" · "}
                <NavLink className="sa-link" href={p.planHref}>
                  Kế hoạch ›
                </NavLink>
              </>
            ) : null}
            {saved.ack ? <b className="sd-ack" data-testid="p2-ack"> {saved.ack}</b> : null}
          </div>
        ) : null}
      </div>
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể chạy cùng nhau. Juli ghi lại rằng bạn đã xác nhận, kèm giờ."
        lines={togetherWarn ? breachWarnLines(togetherWarn as Breach[]) : []}
        onBack={() => setTogetherWarn(null)}
        onGo={() => void runTogether(true)}
        open={togetherWarn !== null}
        sheet={p.narrow}
        title="Chạy cùng nhau dù chạm giá sàn?"
      />
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể lưu. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ."
        lines={warn ? breachWarnLines(warn as Breach[]) : []}
        onBack={() => setWarn(null)}
        onGo={() => warn && void save(true, warn)}
        open={warn !== null}
        sheet={p.narrow}
        title={`Lưu P${mainIndex + 1} dù chạm giá sàn?`}
      />
    </section>
  );
}
