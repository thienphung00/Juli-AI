"use client";

import { useState } from "react";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import type { BuilderApi, PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { useRecoMaybe } from "../../../lib/shopee-decisions/context";
import type { Breach } from "../../../lib/shopee-decisions/types";
import { breachWarnLines } from "../../../lib/shopee-decisions/versions";
import { BreachDialog } from "../versions";
import type { AdsResponse, BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import { errorText } from "../ui";
import { Field, ResultCards, num, vnd } from "../builder-p92/p98-shared";

/** Shopee's minimum daily budget (the server's `budget_minimum` says the same). */
export const ADS_MIN_BUDGET = 100_000;

interface Setup {
  campaign: "group" | "single";
  items: readonly string[];
  budget: string;
  roasMode: "system" | "custom";
  roas: string;
  start: string;
  end: string;
}
const blank = (): Setup => ({ campaign: "group", items: [], budget: String(ADS_MIN_BUDGET), roasMode: "system", roas: "", start: "", end: "" });

/** The problems of one setup, in Vietnamese; empty = fine. */
export function adsProblems(s: Setup, minimum: number): string[] {
  const out: string[] = [];
  if (s.items.length === 0) out.push("Chọn ít nhất một sản phẩm.");
  if (s.campaign === "single" && s.items.length > 1) out.push("Chiến dịch đơn chỉ có một sản phẩm.");
  const b = num(s.budget);
  if (b === null || b < minimum) out.push(`Ngân sách mỗi ngày tối thiểu ${vnd(minimum)}.`);
  if (s.roasMode === "custom" && !(num(s.roas) && (num(s.roas) ?? 0) > 0)) out.push("Nhập ROAS mục tiêu.");
  if (!s.start) out.push("Chọn ngày bắt đầu.");
  if (s.end && s.start && s.end < s.start) out.push("Ngày kết thúc phải sau ngày bắt đầu.");
  return out;
}

/** A group runs at least 3 days; a setup without an end date is planned for the 30-day horizon. */
export function planDays(days: number | null): number {
  return Math.min(90, Math.max(3, days ?? 30));
}

type Act = { readonly kind: "choose" | "plan"; readonly index: number };

export function AdsBuilder({ api, products }: { readonly api: BuilderP98Api; readonly products: readonly PickerProduct[] }) {
  const [setups, setSetups] = useState<readonly Setup[]>([blank()]);
  const [data, setData] = useState<AdsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const host = useRecoMaybe();
  const builder: BuilderApi | undefined = host?.builder;
  const [acting, setActing] = useState(false);
  const [done, setDone] = useState<Readonly<Record<string, string>>>({});
  const [warn, setWarn] = useState<{ readonly act: Act; readonly breaches: readonly Breach[] } | null>(null);
  const [actError, setActError] = useState<string | null>(null);

  const send = async (act: Act, ack: boolean) => {
    const row = data?.setups[act.index];
    if (!builder || !row?.spec) return;
    setActing(true);
    setActError(null);
    try {
      if (act.kind === "choose") {
        const out = await builder.choose({ versions: [row.spec], chosen: 0, acknowledgeBreaches: ack });
        setDone((d) => ({ ...d, [`choose-${act.index}`]: `Đã chuyển sang Quyết định · thẻ thủ công ${out.code ?? out.id}.` }));
      } else {
        const out = await builder.group({ versions: [row.spec], members: [0], days: planDays(row.days), start: row.spec["start"] ? String(row.spec["start"]) : null, acknowledgeBreaches: ack });
        setDone((d) => ({ ...d, [`plan-${act.index}`]: `Đã thêm vào Kế hoạch (${out.saved.map((c) => c.code ?? c.id).join(", ")}). Chưa thực hiện gì.` }));
      }
      setWarn(null);
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code === "reco_breach_not_acknowledged" && Array.isArray(e.detail?.["breaches"])) setWarn({ act, breaches: e.detail["breaches"] as Breach[] });
      else setActError(errorText(e));
    } finally {
      setActing(false);
    }
  };

  const patch = (i: number, p: Partial<Setup>) => setSetups((all) => all.map((s, k) => (k === i ? { ...s, ...p } : s)));
  const problems = setups.map((s) => adsProblems(s, ADS_MIN_BUDGET));
  const ok = problems.every((p) => p.length === 0);
  const calc = () => {
    setTried(true);
    if (!ok) return;
    setBusy(true);
    api
      .ads({
        setups: setups.map((s) => ({
          campaign: s.campaign,
          item_ids: s.items,
          daily_budget: num(s.budget) ?? 0,
          roas: s.roasMode === "custom" ? { mode: "custom", target: num(s.roas) ?? 0 } : { mode: "system" },
          start_date: s.start,
          ...(s.end ? { end_date: s.end } : {}),
        })),
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
    <div className="sa-page" data-testid="ads-builder">
      <h2 className="sa-h1">Thiết lập Dịch vụ Hiển thị Sản phẩm</h2>
      <p className="sa-hint">Hiện tại bạn nhập thiết lập bằng tay; Juli chưa tự tạo chiến dịch trên Shopee. Đặt cạnh nhau tối đa vài thiết lập để so sánh.</p>
      <div className="p2-split">
        {setups.map((s, i) => (
          <section className="sa-card" data-testid={`ads-setup-${i}`} key={i}>
            <h3 className="sa-h2">Thiết lập {i + 1}</h3>
            <Field label={`Loại chiến dịch ${i + 1}`}>
              <select onChange={(e) => patch(i, { campaign: e.target.value as Setup["campaign"] })} value={s.campaign}>
                <option value="group">Chiến dịch nhóm</option>
                <option value="single">Chiến dịch đơn</option>
              </select>
            </Field>
            <div className="sb-pills">
              {products.slice(0, 40).map((p) => (
                <button
                  aria-pressed={s.items.includes(p.item_id)}
                  className={`sb-pill ${s.items.includes(p.item_id) ? "sb-pill--on" : ""}`}
                  key={p.item_id}
                  onClick={() => patch(i, { items: s.items.includes(p.item_id) ? s.items.filter((x) => x !== p.item_id) : s.campaign === "single" ? [p.item_id] : [...s.items, p.item_id] })}
                  type="button"
                >
                  {p.name}
                </button>
              ))}
            </div>
            <Field label={`Ngân sách mỗi ngày ${i + 1} (đ)`}>
              <input inputMode="numeric" onChange={(e) => patch(i, { budget: e.target.value })} value={s.budget} />
            </Field>
            <Field label={`ROAS ${i + 1}`}>
              <select onChange={(e) => patch(i, { roasMode: e.target.value as Setup["roasMode"] })} value={s.roasMode}>
                <option value="system">Shopee tối ưu</option>
                <option value="custom">Tự đặt</option>
              </select>
            </Field>
            {s.roasMode === "custom" ? (
              <Field label={`ROAS mục tiêu ${i + 1}`}>
                <input inputMode="decimal" onChange={(e) => patch(i, { roas: e.target.value })} value={s.roas} />
              </Field>
            ) : null}
            <Field label={`Ngày bắt đầu ${i + 1}`}>
              <input onChange={(e) => patch(i, { start: e.target.value })} type="date" value={s.start} />
            </Field>
            <Field label={`Ngày kết thúc ${i + 1} (không bắt buộc)`}>
              <input onChange={(e) => patch(i, { end: e.target.value })} type="date" value={s.end} />
            </Field>
            {tried
              ? (problems[i] ?? []).map((p) => (
                  <p className="sd-error" key={p} role="alert">
                    {p}
                  </p>
                ))
              : null}
            {setups.length > 1 ? (
              <button className="sa-btn sa-btn--s" onClick={() => setSetups(setups.filter((_, k) => k !== i))} type="button">
                Bỏ thiết lập {i + 1}
              </button>
            ) : null}
          </section>
        ))}
      </div>
      <div className="sd-actions">
        {setups.length < 4 ? (
          <button className="sa-btn" onClick={() => setSetups([...setups, blank()])} type="button">
            + Thêm thiết lập
          </button>
        ) : null}
        <button className="sa-btn sa-btn--primary" data-testid="ads-calc" disabled={busy} onClick={calc} type="button">
          Tính thiết lập
        </button>
      </div>
      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <section className="sa-card" data-testid="ads-out">
          {data.setups.map((s, i) => (
            <p key={i}>
              {s.campaign_label}: {s.days !== null ? `${s.days} ngày, tổng ngân sách ${vnd(s.total_budget)}` : "chưa có ngày kết thúc"}
            </p>
          ))}
          <ResultCards items={data.setups.map((s, i) => ({ title: `Thiết lập ${i + 1} · ${s.campaign_label}`, result: s.result }))} />
          {builder
            ? data.setups.map((s, i) => (
                <div className="sd-actions" data-testid={`ads-act-${i}`} key={i}>
                  <span className="sa-hint">Thiết lập {i + 1}</span>
                  <button className="sa-btn" data-testid={`ads-choose-${i}`} disabled={acting || host?.readOnly || !s.spec || `choose-${i}` in done} onClick={() => void send({ kind: "choose", index: i }, false)} type="button">
                    Chọn
                  </button>
                  <button className="sa-btn sa-btn--primary" data-testid={`ads-plan-${i}`} disabled={acting || host?.readOnly || !s.spec || `plan-${i}` in done} onClick={() => void send({ kind: "plan", index: i }, false)} type="button">
                    Thêm vào kế hoạch
                  </button>
                  {done[`choose-${i}`] ?? done[`plan-${i}`] ? (
                    <span className="sa-hint" data-testid={`ads-done-${i}`} role="status">
                      {done[`plan-${i}`] ?? done[`choose-${i}`]}
                    </span>
                  ) : null}
                </div>
              ))
            : null}
          {actError ? (
            <p className="sd-error" role="alert">
              {actError}
            </p>
          ) : null}
        </section>
      ) : null}
      <BreachDialog
        busy={acting}
        closing="Bạn vẫn có thể tiếp tục. Juli ghi lại rằng bạn đã xác nhận, kèm giờ."
        lines={warn ? breachWarnLines(warn.breaches as Breach[]) : []}
        onBack={() => setWarn(null)}
        onGo={() => warn && void send(warn.act, true)}
        open={warn !== null}
        sheet={false}
        title="Tiếp tục dù chạm trần chi?"
      />
    </div>
  );
}
