import { useId, useMemo, useState, type ReactNode } from "react";

import { saveBlob, keHoachFileName } from "../../lib/shopee-analytics/download";
import { DASH, dayMonth, vnd } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { metricsOfCard } from "../../lib/shopee-decisions/model";
import { aggRows, cardBreaches, confirmWarnings, cutText, isHard, isStacked, kolRows, kolSummary, mdeText, planProducts, productMde, productName, stackBreaches, stackWarning, windowText } from "../../lib/shopee-decisions/plan-model";
import type { DateSpan, PlanApi, PlanGroup, PlanNotice, PlanResponse, WindowProductRow } from "../../lib/shopee-decisions/plan-types";
import type { CardList, CardSummary, Family } from "../../lib/shopee-decisions/types";
import { ackText } from "../../lib/shopee-decisions/versions";
import { MetricChip } from "../metrics/metric-chip";
import { Notice, TextChip } from "../shopee-analytics/ui";
import { DataMissingNotice } from "./plan-results";
import { mil } from "../shopee-analytics/tong-quan";
import { PlanSteps } from "./plan-steps";
import { rangeText } from "./top-cards";
import { NavLink, RecoState, errorText } from "./ui";

/**
 * Đề xuất › Kế hoạch nháp (P100): month bars, the table of the cards in the draft with their Δ totals,
 * the group-run and window settings, and "Duyệt kế hoạch". Adding a card executes nothing; only
 * "Duyệt kế hoạch" approves the draft in one go. A floor or spend-cap breach never blocks: the dialog
 * warns, "Vẫn tiếp tục" is recorded. The numbers come from the plan API (`plan-types.ts`).
 */

const toneClass = (t: string): string => (t === "up" ? "sa-tone--up" : t === "down" ? "sa-tone--down" : "");

export function PlanView(props: PlanFrameProps = {}) {
  const host = useReco();
  const api = host.plan?.api;
  if (!api) {
    return (
      <div className="sa-page" data-testid="kh-off">
        <Notice tone="info">Kế hoạch chưa bật</Notice>
      </div>
    );
  }
  return <PlanScreen api={api} {...props} />;
}

type Dialog = null | { readonly kind: "confirm" };

export interface PlanFrameProps {
  readonly frame?: (title: string, children: ReactNode) => ReactNode;
  readonly onChanged?: () => void;
  readonly counts?: unknown;
}

const NO_FRAME = (_t: string, children: ReactNode): ReactNode => <div className="sa-page kh">{children}</div>;

/** "Tháng 11" of a plan month ("2026-11"). */
const monthName = (m: string): string => `Tháng ${Number(m.slice(5, 7)) || m}`;

function PlanScreen({ api, frame = NO_FRAME, onChanged }: { readonly api: PlanApi } & PlanFrameProps) {
  const host = useReco();
  const [tick, setTick] = useState(0);
  const [override, setOverride] = useState<{ readonly tick: number; readonly plan: PlanResponse } | null>(null);
  const loaded = useResource<PlanResponse>(() => api.get(), `${host.shopKey}|plan|${tick}`);
  const cards = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|plan-cands|${tick}`);
  const products = useResource(() => (host.products ? host.products() : Promise.resolve([])), `${host.shopKey}|plan-products`);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<string | null>(null);
  const [doneOnce, setDoneOnce] = useState(false);
  const [notice, setNotice] = useState<PlanNotice | null>(null);
  // D85.4: the answer of an action is shown until the refetch lands, then dropped, so a stale
  // override can never hide what the server now says.
  const shown = override !== null && override.tick === tick && loaded.status === "loading" ? override.plan : null;
  const plan = shown ?? (loaded.status === "ready" ? loaded.data : null);

  const act = async (call: () => Promise<PlanResponse>, after?: (p: PlanResponse) => void) => {
    setBusy(true);
    setError(null);
    try {
      const p = await call();
      setOverride({ tick: tick + 1, plan: p });
      setNotice(p.notice ?? null);
      after?.(p);
      setTick((t) => t + 1);
      onChanged?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const byId = new Map((cards.status === "ready" ? cards.data.cards : []).map((c) => [c.id, c]));
  const names = new Map((products.status === "ready" ? products.data : []).map((p) => [p.id, p.name]));
  const draft = plan ? draftRows(plan) : null;
  const title = plan && draft ? `Nháp thêm ${draft.profit} lợi nhuận${plan.month ? ` ${monthName(plan.month.with_draft.month).toLowerCase()}` : ""}` : "Kế hoạch nháp";

  return frame(
    title,
    <div className="kh" data-testid="kh-page">
      <RecoState resource={plan ? { status: "ready", data: plan } : loaded}>
        {(p) => <DraftPlan ack={ack} api={api} busy={busy} byId={byId} error={error} names={names} notice={notice} onAct={act} onConfirm={() => setDialog({ kind: "confirm" })} plan={p} />}
      </RecoState>
      {plan ? (
        <ConfirmDialog
          busy={busy}
          dialog={dialog}
          onBack={() => setDialog(null)}
          onGo={() => {
            if (!dialog) return;
            const warned = confirmWarnings(plan);
            void act(() => api.confirm({ acknowledgeBreaches: warned.length > 0 }), (p) => {
              if (warned.length > 0) setAck(ackText(p.plan?.acknowledged_breaches?.breaches ?? plan.aggregate?.breaches ?? [{ type: "floor" }], p.plan?.acknowledged_breaches?.at ?? new Date().toISOString()));
              setDoneOnce(true);
              setDialog(null);
            });
          }}
          plan={plan}
          sheet={false}
        />
      ) : null}
      {doneOnce && (plan?.plan?.status ?? "draft") !== "draft" ? <span hidden data-testid="kh-done-flag" /> : null}
    </div>,
  );
}

/** One table row of Kế hoạch nháp: what the card runs on and its Δ totals over its own days. */
export interface DraftRow {
  readonly card: PlanResponse["cards"][number];
  readonly dates: DateSpan | null;
  readonly days: number | null;
  readonly profit: { readonly p10: number | null; readonly p90: number | null };
  readonly gmv: { readonly p10: number | null; readonly p90: number | null };
}

const numOrNull = (n: unknown): number | null => (typeof n === "number" && Number.isFinite(n) ? n : null);

export function rowsOfPlan(plan: PlanResponse): DraftRow[] {
  return plan.cards.map((card) => {
    const r = plan.aggregate?.cards.find((c) => c.card_id === card.card_id)?.result ?? card.evaluation?.result;
    const alone = card.evaluation?.alone;
    const dates = r?.own_dates ?? r?.counted_dates ?? r?.horizon ?? null;
    const days = numOrNull(r?.own_days) ?? numOrNull(r?.counted_days) ?? dates?.days ?? null;
    return {
      card,
      dates,
      days,
      profit: { p10: numOrNull(r?.delta?.p10.dprofit) ?? numOrNull(alone?.dprofit.p10), p90: numOrNull(r?.delta?.p90.dprofit) ?? numOrNull(alone?.dprofit.p90) },
      gmv: { p10: numOrNull(r?.delta?.p10.dgmv), p90: numOrNull(r?.delta?.p90.dgmv) },
    };
  });
}

const sumRange = (rows: readonly { readonly p10: number | null; readonly p90: number | null }[]): { readonly p10: number | null; readonly p90: number | null } => {
  if (rows.length === 0 || rows.some((r) => r.p10 === null || r.p90 === null)) return { p10: null, p90: null };
  return { p10: rows.reduce((a, r) => a + Math.min(r.p10!, r.p90!), 0), p90: rows.reduce((a, r) => a + Math.max(r.p10!, r.p90!), 0) };
};

/** The draft's total Δ lợi nhuận / Δ GMV over the cards' own days, as text ranges. */
function draftRows(plan: PlanResponse): { readonly profit: string; readonly gmv: string } {
  const rows = rowsOfPlan(plan);
  return { profit: rangeText(sumRange(rows.map((r) => r.profit))), gmv: rangeText(sumRange(rows.map((r) => r.gmv))) };
}

/** Month bars: "Đang chạy" grey, the draft's addition pink (same totals as Tổng quan). */
function MonthBars({ plan, api }: { readonly plan: PlanResponse; readonly api: PlanApi }) {
  const host = useReco();
  const [failed, setFailed] = useState(false);
  const m = plan.month;
  if (!m) return null;
  const bar = (label: string, key: string, goal: number | null, baseline: number | null, withDraft: number | null) => {
    // nothing running: the level today is the bar (the server sends it as the goal; an older answer only has the baseline)
    const run = goal ?? baseline;
    const top = Math.max(run ?? 0, withDraft ?? 0);
    const added = run !== null && withDraft !== null ? Math.max(0, withDraft - run) : 0;
    // the draft's addition is a sliver of a big base: when it would be under 15 % of the bar, the axis starts below the base so it shows
    const span = added > 0 ? Math.min(top, added / 0.15) : top;
    const from = top - span;
    const pct = (v: number) => (span > 0 ? Math.min(100, Math.max(0, ((v - from) / span) * 100)) : 0);
    const runPct = run !== null ? pct(run) : 0;
    const addPct = run !== null ? (withDraft !== null ? Math.min(100 - runPct, pct(withDraft) - runPct) : 0) : withDraft !== null ? 100 : 0;
    return (
      <div className="dx-bar" data-testid={`kh-month-${key}`}>
        <div className="dx-bar__label">{label}</div>
        <div className="dx-bar__track">
          <div className="dx-bar__run" data-testid={`kh-month-${key}-run-bar`} style={{ width: `${runPct}%` }} />
          <div className="dx-bar__add" data-testid={`kh-month-${key}-add-bar`} style={{ left: `${runPct}%`, width: `${Math.max(0, addPct)}%` }} />
        </div>
        <div className="dx-bar__nums">
          <span>Hiện tại</span> <b data-testid={`kh-month-${key}-running`}>{run === null ? DASH : mil(run)}</b> → <span>Nếu áp dụng nháp</span> <b data-testid={`kh-month-${key}-draft`}>{withDraft === null ? DASH : mil(withDraft)}</b>
        </div>
      </div>
    );
  };
  return (
    <section aria-label={monthName(m.with_draft.month)} className="dx-month" data-testid="kh-month">
      <div className="dx-month__head">
        <b>{monthName(m.with_draft.month)}</b>
        <span>
          {m.with_draft.day}/{m.with_draft.days_in_month} ngày
        </span>
        {api.exportKeHoach ? (
          <button
            className="sa-btn sa-btn--s"
            data-testid="kh-export"
            onClick={() => {
              setFailed(false);
              api.exportKeHoach!(m.with_draft.month).then(
                (blob) => saveBlob(blob, keHoachFileName(host.shopName || "Shop", m.with_draft.month)),
                () => setFailed(true),
              );
            }}
            type="button"
          >
            Tải Excel
          </button>
        ) : null}
        {failed ? <span className="sd-error">Chưa tải được tệp Excel</span> : null}
      </div>
      {bar("GMV", "gmv", m.running.goal_gmv, m.running.baseline_gmv, m.with_draft.goal_gmv)}
      {bar("Lợi nhuận", "profit", m.running.goal_profit, m.running.baseline_profit, m.with_draft.goal_profit)}
      <div className="dx-month__legend">
        <span className="dx-dot dx-dot--run" />
        Đang chạy
        <span className="dx-dot dx-dot--add" />
        Nếu áp dụng nháp
      </div>
    </section>
  );
}

const dmSpan = (d: DateSpan | null): string => (d ? `${dayMonth(d.from)} – ${dayMonth(d.to)}` : DASH);

function DraftPlan({ plan, api, byId, names, busy, error, ack, notice, onAct, onConfirm }: { readonly plan: PlanResponse; readonly api: PlanApi; readonly byId: ReadonlyMap<string, CardSummary>; readonly names: ReadonlyMap<string, string>; readonly busy: boolean; readonly error: string | null; readonly ack: string | null; readonly notice: PlanNotice | null; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void>; readonly onConfirm: () => void }) {
  const host = useReco();
  const head = plan.plan;
  const done = (head?.status ?? "draft") !== "draft";
  const products = planProducts(plan);
  const warns = stackBreaches(plan).map((b) => stackWarning(plan, b));
  const rows = aggRows(plan);
  const cost = plan.aggregate?.cost;
  const shownAck = ack ?? (head?.acknowledged_breaches?.breaches?.length ? ackText(head.acknowledged_breaches.breaches, head.acknowledged_breaches.at) : null);
  const kol = kolSummary(plan);
  const horizonCap = cost && typeof cost.horizon_spend_after === "number" && typeof cost.horizon_cap === "number" && cost.horizon_cap > 0 && cost.cost_complete !== false ? cost : null;
  const dayCap = cost && cost.horizon_spend_after === undefined && cost.cap_per_day ? cost : null;
  const capBar = horizonCap
    ? { text: `Chi tiêu 30 ngày tới so với trần ${vnd(horizonCap.horizon_cap)}`, pct: Math.min(100, Math.round((horizonCap.horizon_spend_after! / horizonCap.horizon_cap!) * 100)) }
    : dayCap
      ? { text: `Chi phí toàn shop mỗi ngày so với trần ${vnd(dayCap.cap_per_day)}`, pct: Math.min(100, Math.round((dayCap.per_day_after / dayCap.cap_per_day!) * 100)) }
      : null;
  const missing = plan.aggregate?.data_missing ?? null;
  const table = rowsOfPlan(plan);
  const total = { profit: sumRange(table.map((r) => r.profit)), gmv: sumRange(table.map((r) => r.gmv)) };
  const horizon = plan.aggregate?.horizon ?? null;
  const perDay = (q: { readonly p10: number | null; readonly p90: number | null }, days: number | null): string | null => (days && days > 0 && q.p10 !== null && q.p90 !== null ? `≈ ${rangeText(q, days)}/ngày` : null);
  return (
    <section className="kh-plan" data-testid="kh-plan">
      <div className="kh-plan__head">
        <TextChip tone={done ? "info" : "flat"}>{done ? "Đã xác nhận" : "Nháp"}</TextChip>
        <span className="sa-hint" data-testid="kh-count">
          {plan.cards.length} thẻ · {products.length} sản phẩm
        </span>
        {head?.code ? (
          <span className="sd-code" data-testid="kh-code">
            {head.code}
          </span>
        ) : null}
        {shownAck ? (
          <b className="sd-ack" data-testid="kh-ack">
            {shownAck}
          </b>
        ) : null}
      </div>

      {done ? (
        <Notice tone="info" testId="kh-done">
          <b>Đã xác nhận kế hoạch {head?.code}.</b> {plan.cards.length} thẻ chuyển sang “Đã duyệt”.
        </Notice>
      ) : null}

      <MonthBars api={api} plan={plan} />
      {missing ? <DataMissingNotice missing={missing} /> : null}

      {missing ? null : <PlanSteps api={api} busy={busy} done={done} onAct={onAct} plan={plan} />}

      <div aria-label="Thẻ trong nháp" className="dx-table" data-testid="kh-rows" role="table">
        <div className="dx-table__row dx-table__row--head" role="row">
          <div>Bước</div>
          <div>Thẻ</div>
          <div>Chạy</div>
          <div>Δ lợi nhuận cả kỳ</div>
          <div>Δ GMV cả kỳ</div>
          <div />
        </div>
        {table.map((r, i) => {
          const c = r.card;
          const sum = byId.get(c.card_id);
          const chips = metricsOfCard(sum ?? { family: (c.family ?? "listing") as Family, change_kind: c.change_kind ?? "", section: null, metric: { key: "", critical_id: null, critical_kpi: null, flow: null, at_stake_per_day: null } });
          const pid = c.product_id;
          return (
            <div className={`dx-table__row ${isStacked(plan, c) ? "kh-row--bad" : ""}`} data-testid={`kh-row-${c.card_id}`} key={c.card_id} role="row">
              <div>{i + 1}</div>
              <div className="dx-table__card">
                <b>{c.title ?? c.change_kind}</b>
                <span className="dx-table__sub">
                  {pid ? (names.get(pid) ?? productName(plan, pid)) : null}
                  {chips.map((m) => (
                    <MetricChip key={m} metric={m} />
                  ))}
                  {(c.groups ?? []).map((g) => (
                    <TextChip key={`${g.letter}-${g.version}`} tone="info">
                      Nhóm {g.letter} · V{g.version}
                    </TextChip>
                  ))}
                  {isStacked(plan, c) || cardBreaches(plan, c) ? <TextChip tone="down">{cardBreaches(plan, c) ? "Chạm giá sàn" : "Chạm giá sàn khi xếp chồng"}</TextChip> : null}
                </span>
              </div>
              <div data-testid="kh-row-dates">
                {dmSpan(r.dates)}
                {r.days ? ` · ${r.days} ngày` : ""}
              </div>
              <div>
                <div className="dx-table__big" data-testid="kh-row-profit">
                  {rangeText(r.profit)}
                </div>
                <div className="dx-table__small">{perDay(r.profit, r.days)}</div>
              </div>
              <div>
                <div className="dx-table__big" data-testid="kh-row-gmv">
                  {rangeText(r.gmv)}
                </div>
                <div className="dx-table__small">{perDay(r.gmv, r.days)}</div>
              </div>
              <div className="dx-table__act">
                <NavLink className="sa-link" href={host.href({ the: c.card_id, from: "quyet-dinh" })}>
                  Sửa
                </NavLink>
                <button className="sa-btn sa-btn--s" disabled={done || busy} onClick={() => void onAct(() => api.remove(c.card_id))} type="button">
                  Bỏ khỏi kế hoạch
                </button>
              </div>
            </div>
          );
        })}
        {table.length === 0 ? <p className="sa-hint" data-testid="kh-empty">—</p> : null}
        {table.length > 0 ? (
          <div className="dx-table__row dx-table__row--total" data-testid="kh-total" role="row">
            <div />
            <div>
              <b>Cả nháp</b>
            </div>
            <div>{dmSpan(horizon)}</div>
            <div className="dx-table__big" data-testid="kh-total-profit">
              {rangeText(total.profit)}
            </div>
            <div className="dx-table__big" data-testid="kh-total-gmv">
              {rangeText(total.gmv)}
            </div>
            <div />
          </div>
        ) : null}
      </div>

      <GroupsSection api={api} busy={busy} done={done} notice={notice} onAct={onAct} plan={plan} />

      {warns.map((w, i) => (
        <div className="sd-check sd-check--bad kh-warn" key={i} role="alert">
          <span>
            <b>{w.title}</b> <span className="sd-check__line">{w.body}</span>
            <span className="sd-check__line">{w.fix}</span>
          </span>
        </div>
      ))}

      {kol ? (
        <div className="kh-kol" data-testid="kh-kol">
          <b>Mẫu và KOL trong kế hoạch</b>
          {kolRows(kol).map((q) => (
            <div key={q.k}>
              <span>{q.k}</span>
              <b>{q.v}</b>
            </div>
          ))}
        </div>
      ) : null}

      {rows.length > 0 ? (
        <div className="kh-agg" data-testid="kh-agg">
          <h3>Cả kế hoạch: hôm nay → sau kế hoạch</h3>
          <div className="kh-agg__table">
            <div className="kh-agg__row kh-agg__row--head">
              <span>Chỉ số</span>
              <span>Hôm nay</span>
              <span>Sau kế hoạch</span>
            </div>
            {rows.map((r) => (
              <div className={`kh-agg__row ${r.bad ? "kh-agg__row--bad" : ""}`} data-testid={`kh-agg-${r.key}`} key={r.key}>
                <span>{r.label}</span>
                <span className="sd-muted">{r.today}</span>
                <span>
                  <b className={r.key === "sure" || r.key === "exp" ? toneClass(r.tone) : ""}>{r.after}</b>
                  {r.d ? <span className={`sv-cell__d sv-cell__d--${r.tone === "plain" ? "flat" : r.tone}`}>{r.d}</span> : null}
                </span>
              </div>
            ))}
          </div>
          {capBar ? (
            <div className="kh-cap" data-testid="kh-cap">
              <span>{capBar.text}</span>
              <span className="kh-cap__bar">
                <span className={cost?.over_cap ? "kh-cap__fill kh-cap__fill--over" : "kh-cap__fill"} style={{ width: `${capBar.pct}%` }} />
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      {plan.windows ? <WindowBox api={api} busy={busy || done} onAct={onAct} plan={plan} /> : null}

      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="sd-actions">
        <NavLink className="sa-btn" href={host.href({})} testId="kh-add-more">
          Thêm thẻ
        </NavLink>
        <button className="sa-btn sa-btn--primary" data-testid="kh-confirm" disabled={plan.cards.length === 0 || done || busy} onClick={onConfirm} type="button">
          Duyệt kế hoạch
        </button>
      </div>
    </section>
  );
}

const dm = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

/**
 * "Nhóm A, B ..." (P97 D85.14 / P94): options that run together with one period (at least 3 days). Each group
 * is judged on its own with the plan math over its members; the groups run one after another. An option that
 * wants a field another option already holds (giá bán, tên, ngân sách…) moves to the next group, said here.
 */
function GroupsSection({ plan, api, busy, done, notice, onAct }: { readonly plan: PlanResponse; readonly api: PlanApi; readonly busy: boolean; readonly done: boolean; readonly notice: PlanNotice | null; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void> }) {
  const groups = plan.groups ?? [];
  if (groups.length === 0 && !notice) return null;
  return (
    <div className="kh-groups" data-testid="kh-groups">
      <div className="sa-card__head">
        <h3>Nhóm chạy cùng nhau</h3>
      </div>
      {notice ? (
        <div className="sd-check sd-check--warn" data-testid="kh-notice" role="status">
          <span>
            <b>Chạy lần lượt:</b> {notice.message}
          </span>
        </div>
      ) : null}
      {groups.map((g) => (
        <GroupBox api={api} busy={busy || done} g={g} key={`${g.id}|${g.days}|${g.start_fixed ? g.start : ""}`} onAct={onAct} plan={plan} />
      ))}
    </div>
  );
}

function GroupBox({ g, plan, api, busy, onAct }: { readonly g: PlanGroup; readonly plan: PlanResponse; readonly api: PlanApi; readonly busy: boolean; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void> }) {
  const [days, setDays] = useState(String(g.days));
  const [start, setStart] = useState(g.start_fixed ? g.start : "");
  const n = Number(days);
  const problem = !Number.isInteger(n) || n < g.min_days ? `Nhóm chạy ít nhất ${g.min_days} ngày.` : n > 90 ? "Nhóm chạy tối đa 90 ngày." : null;
  const rows = aggRows({ ...plan, aggregate: g.aggregate });
  const approved = g.status === "approved";
  return (
    <div className="kh-group" data-testid={`kh-group-${g.letter}`}>
      <div className="kh-group__head">
        <b>{g.name}</b>
        {g.code ? <span className="sd-code">{g.code}</span> : null}
        <span data-testid={`kh-group-period-${g.letter}`}>
          {dm(g.start)} – {dm(g.end)} · {g.days} ngày
        </span>
        {approved ? <TextChip tone="info">Đã duyệt</TextChip> : null}
      </div>
      <ul className="kh-group__members">
        {g.members.map((m) => (
          <li data-testid={`kh-gm-${m.entry_id}`} key={m.entry_id}>
            <span className="sd-code">{m.version_code ?? `${m.code}-V${m.version}`}</span> <b>{m.title ?? m.change_kind}</b>
            {m.n_targets > 0 ? <span className="sa-hint"> · {m.n_targets} đối tượng</span> : null}
            {api.removeGroupMember ? (
              <button aria-label={`Bỏ ${m.version_code ?? m.code} khỏi ${g.name}`} className="sa-link kh-linkbtn" disabled={busy} onClick={() => void onAct(() => api.removeGroupMember!(g.id, { cardId: m.card_id, version: m.version }))} type="button">
                Bỏ khỏi nhóm
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {rows.length > 0 ? (
        <div className="kh-agg__table" data-testid={`kh-group-agg-${g.letter}`}>
          {rows.map((r) => (
            <div className={`kh-agg__row ${r.bad ? "kh-agg__row--bad" : ""}`} key={r.key}>
              <span>{r.label}</span>
              <span className="sd-muted">{r.today}</span>
              <span>
                <b>{r.after}</b>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="sa-hint">{DASH}</p>
      )}
      {approved || !api.setGroupPeriod ? null : (
        <div className="kh-group__edit">
          <label>
            <span className="sd-field__label">Số ngày</span>
            <input aria-label={`Số ngày ${g.name}`} className="p2-text" inputMode="numeric" onChange={(e) => setDays(e.target.value)} type="text" value={days} />
          </label>
          <label>
            <span className="sd-field__label">Bắt đầu</span>
            <input aria-label={`Bắt đầu ${g.name}`} className="p2-text" onChange={(e) => setStart(e.target.value)} type="date" value={start} />
          </label>
          <button className="sa-btn sa-btn--s" disabled={busy || problem !== null} onClick={() => void onAct(() => api.setGroupPeriod!(g.id, { days: n, ...(start ? { start } : { clearStart: true }) }))} type="button">
            Lưu thời gian
          </button>
          {api.cancelGroup ? (
            <button className="sa-btn sa-btn--s" disabled={busy} onClick={() => void onAct(() => api.cancelGroup!(g.id))} type="button">
              Bỏ nhóm
            </button>
          ) : null}
          {problem ? <span className="sd-error">{problem}</span> : null}
        </div>
      )}
    </div>
  );
}

function WindowBox({ plan, api, busy, onAct }: { readonly plan: PlanResponse; readonly api: PlanApi; readonly busy: boolean; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void> }) {
  const w = plan.windows!;
  const days = plan.plan?.window_days ?? null;
  const auto = days === null;
  const custom = days !== null && !w.presets.includes(days) ? days : 10;
  const anyHard = w.per_product.some(isHard);
  const setDays = (n: number | null) => void onAct(() => api.setWindow(n));
  const codesOf = (r: WindowProductRow) => plan.aggregate?.products?.find((b) => b.product_id === r.product_id)?.codes.join(" + ") ?? "";
  return (
    <div className="kh-win" data-testid="kh-win">
      <div className="sa-card__head">
        <h3>Đo trong bao lâu</h3>
      </div>
      <div className="kh-win__opts" role="radiogroup" aria-label="Cửa sổ đo">
        <button aria-checked={auto} className={`kh-opt ${auto ? "kh-opt--on" : ""}`} disabled={busy} onClick={() => setDays(null)} role="radio" type="button">
          <span>
            <b>Tự động theo sản phẩm</b> <TextChip tone="pink">Đề xuất</TextChip>
          </span>
        </button>
        {w.presets.map((n) => (
          <button aria-checked={days === n} className={`kh-opt ${days === n ? "kh-opt--on" : ""}`} disabled={busy} key={n} onClick={() => setDays(n)} role="radio" type="button">
            <span>
              <b>{n} ngày cho cả kế hoạch</b>
            </span>
            <span className="sa-hint">chỉ thấy thay đổi {mdeText(w.per_product, n)}</span>
          </button>
        ))}
      </div>
      <div className="kh-win__custom">
        <span>Tuỳ chọn</span>
        <button aria-label="Giảm số ngày" disabled={busy || custom <= w.min_days} onClick={() => setDays(Math.max(w.min_days, custom - 1))} type="button">
          −
        </button>
        <b data-testid="kh-custom">{custom} ngày</b>
        <button aria-label="Tăng số ngày" disabled={busy || custom >= w.max_days} onClick={() => setDays(Math.min(w.max_days, custom + 1))} type="button">
          +
        </button>
        <span className="sa-hint">
          từ {w.min_days} đến {w.max_days} ngày
        </span>
      </div>
      {anyHard ? (
        <div className="sd-check sd-check--warn" data-testid="kh-hard">
          <span>
            <b>Khó kết luận.</b>
          </span>
        </div>
      ) : null}
      <div className="kh-sets">
        <span className="sd-field__label">Từng sản phẩm</span>
        {w.per_product.map((r) => {
          const mde = productMde(r);
          const rec = r.recommended_days;
          const own = r.source === "custom";
          return (
            <div className="kh-set" data-testid={`kh-set-${r.product_id}`} key={r.product_id}>
              <b>{r.name ?? r.product_id}</b>
              <span className="sa-hint">{codesOf(r)}</span>
              <span className="kh-set__opts">
                {[0, ...w.presets].map((n) => {
                  const on = n === 0 ? !own : own && r.days === n;
                  const label = n === 0 ? (auto ? `Tự động (${r.days} ngày)` : `Theo kế hoạch (${days} ngày)`) : `${n} ngày${n === rec ? " · Đề xuất" : ""}`;
                  return (
                    <button aria-pressed={on} className={`sb-pill ${on ? "sb-pill--on" : ""}`} disabled={busy} key={n} onClick={() => void onAct(() => api.setWindow(n === 0 ? null : n, r.product_id))} type="button">
                      {label}
                    </button>
                  );
                })}
              </span>
              <span className="sa-hint">
                {isHard(r)
                  ? `${rec === null ? "Chưa cửa sổ nào đủ" : `Dưới mức đề xuất (${rec} ngày)`}: khó kết luận${mde === null ? "" : `, chỉ thấy ≥ ${mde}%`}`
                  : own
                    ? `Riêng nhóm này · ${r.days} ngày${mde === null ? "" : ` · chỉ thấy ≥ ${mde}%`}`
                    : auto
                      ? `Tự động: ${r.days} ngày${mde === null ? "" : `, chỉ thấy ≥ ${mde}%`}`
                      : "Theo kế hoạch"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ConfirmDialog({ dialog, plan, busy, sheet, onBack, onGo }: { readonly dialog: Dialog; readonly plan: PlanResponse; readonly busy: boolean; readonly sheet: boolean; readonly onBack: () => void; readonly onGo: () => void }) {
  const id = useId();
  const warned = useMemo(() => (dialog?.kind === "confirm" ? confirmWarnings(plan) : []), [dialog, plan]);
  if (!dialog) return null;
  const blocked = warned.length > 0;
  const cutsHere = (plan.plan?.measurement_cut ?? []).filter((c) => planProducts(plan).includes(c.product_id));
  return (
    <div className={`qv-overlay ${sheet ? "sv-overlay--sheet" : ""}`} data-testid="kh-dialog">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className={`qv-dialog ${sheet ? "sv-warn--sheet" : ""}`} role="dialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          {blocked ? "Duyệt kế hoạch dù có cảnh báo?" : `Duyệt kế hoạch ${plan.cards.length} thẻ?`}
        </h3>
        <p className="qv-dialog__body">Cửa sổ đo: {windowText(plan)}.</p>
        {blocked ? (
          <div className="sv-warn__lines" role="alert">
            <b>Cảnh báo</b>
            {warned.map((t, i) => (
              <span data-testid="kh-warn-line" key={i}>
                {t}
              </span>
            ))}
            <span>Bạn vẫn có thể tiếp tục. Juli ghi lại xác nhận kèm giờ.</span>
          </div>
        ) : null}
        {cutsHere.length > 0 ? (
          <div className="sd-measuring" data-testid="kh-cuts">
            <b>{sheet ? "Phép đo đang chạy sẽ bị cắt hôm nay" : "Phép đo đang chạy của các sản phẩm này sẽ bị cắt hôm nay"}</b>
            {cutsHere.map((c) => (
              <span key={c.change_set}>{cutText(c)}</span>
            ))}
          </div>
        ) : null}
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onBack} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" disabled={busy} onClick={onGo} type="button">
            {blocked ? "Vẫn tiếp tục" : "Duyệt kế hoạch"}
          </button>
        </div>
      </div>
    </div>
  );
}

