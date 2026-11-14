"use client";

import { useEffect, useState, type ReactNode } from "react";

import { fmt } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { TABS, filterCards, metricOfParam, metricsOfCard, tabCounts, tabOfParam, xemOfParams, type DecisionTab } from "../../lib/shopee-decisions/model";
import type { CardList, CardSummary } from "../../lib/shopee-decisions/types";
import { METRIC_NAME, METRIC_ORDER, type MetricKey } from "../../lib/metrics";
import { MetricChip } from "../metrics/metric-chip";
import { Empty } from "../shopee-analytics/ui";
import { BuilderView } from "./builder";
import { BuilderP92View } from "./builder-p92";
import { CardPage } from "./card-page";
import { DoLuongView } from "./do-luong";
import type { KolCandidate } from "./kol-builder";
import { OpsRecoList } from "./ops-list";
import { PlanView } from "./plan";
import { ThucHienView } from "./thuc-hien";
import { FlashNotice, NO_FLASH, TopCards, cardDays, rangeText, topEntries, type Flash } from "./top-cards";
import { NavLink, RecoState } from "./ui";

/**
 * Quyết định for a Shopee shop (P100): header, the sub-tabs Đề xuất · Thực hiện · Đo lường, and under
 * Đề xuất the views Thẻ and Kế hoạch nháp. URL: `tab=de-xuat|thuc-hien|do-luong`, `xem=the|ke-hoach`
 * (the old `ke-hoach=1` maps there), `metric` and `product` from Phân tích. `?the=<card id>` opens one card.
 */

const EYEBROW: Readonly<Record<DecisionTab, string>> = {
  "de-xuat": "QUYẾT ĐỊNH · ĐỀ XUẤT",
  "thuc-hien": "QUYẾT ĐỊNH · THỰC HIỆN",
  "do-luong": "QUYẾT ĐỊNH · ĐO LƯỜNG",
};

const EMPTY_DE_XUAT = "Chưa có đề xuất nào.";

export interface Frame {
  readonly eyebrow?: string;
  readonly title: string;
  readonly children: ReactNode;
}

function ShellFrame({ tab, xem, counts, planCount, title, eyebrow, children }: { readonly tab: DecisionTab; readonly xem: "the" | "ke-hoach"; readonly counts: Readonly<Record<DecisionTab, number>>; readonly planCount: number | null; readonly title: string; readonly eyebrow?: string; readonly children: ReactNode }) {
  const host = useReco();
  return (
    <div className="sa-page sa-p100" data-testid="sd-list">
      <header className="sa-head">
        <div className="sa-eyebrow">{eyebrow ?? EYEBROW[tab]}</div>
        <div className="sa-head__line sq-head">
          <h1 className="sa-h1" data-testid="sd-h1">
            {title}
          </h1>
          {host.shopName ? <span className="sa-head__right">{host.shopName}</span> : null}
          {!host.readOnly ? (
            <NavLink className="sa-btn sa-btn--s" href={host.href({ builder: true, from: "quyet-dinh" })} testId="sq-builder-link">
              + Tự tạo phương án
            </NavLink>
          ) : null}
        </div>
      </header>
      <nav aria-label="Quyết định" className="sa-seg sa-seg--round sa-tabs" data-testid="sd-tabs">
        {TABS.map(([key, label]) => (
          <NavLink className={`sa-seg__item ${tab === key ? "sa-seg__item--on" : ""}`} href={host.href({ tab: key })} key={key}>
            {label} · {fmt(counts[key], 0)}
          </NavLink>
        ))}
      </nav>
      {tab === "de-xuat" ? (
        <div aria-label="Xem" className="sa-seg sa-seg--round dx-xem" data-testid="dx-xem" role="tablist">
          <NavLink className={`sa-seg__item ${xem === "the" ? "sa-seg__item--on" : ""}`} href={host.href({})} testId="dx-xem-the">
            Thẻ · {fmt(counts["de-xuat"], 0)}
          </NavLink>
          {host.plan ? (
            <NavLink className={`sa-seg__item ${xem === "ke-hoach" ? "sa-seg__item--on" : ""}`} href={host.href({ plan: true })} testId="sq-plan-link">
              Kế hoạch nháp{planCount === null ? "" : ` · ${fmt(planCount, 0)}`}
            </NavLink>
          ) : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}

/** Đề xuất › Thẻ: filter chips, the product select, one row per open card. */
function CardsView({ cards, names, inPlan, metric, product, flash, setFlash, onChanged }: { readonly cards: readonly CardSummary[]; readonly names: Readonly<Record<string, string>>; readonly inPlan: ReadonlySet<string>; readonly metric: MetricKey | null; readonly product: string | null; readonly flash: Flash; readonly setFlash: (f: Flash) => void; readonly onChanged: () => void }) {
  const host = useReco();
  const go = (href: string) => (host.navigate ? host.navigate(href) : window.location.assign(href));
  const shown = filterCards(cards, metric, product);
  const present = METRIC_ORDER.filter((m) => cards.some((c) => metricsOfCard(c).includes(m)) || m === metric);
  const productIds = [...new Set(cards.map((c) => c.product_id).filter((x): x is string => !!x))];
  return (
    <>
      <div className="dx-filters" data-testid="dx-filters">
        <NavLink className={`jm-chip dx-all ${metric ? "" : "dx-all--on"}`} href={host.href({ product })} testId="dx-f-all">
          Tất cả
        </NavLink>
        {present.map((m) => (
          <NavLink href={host.href({ metric: m, product })} key={m} testId={`dx-f-${m}`}>
            <MetricChip metric={m} on={metric === m}>
              {METRIC_NAME[m]}
            </MetricChip>
          </NavLink>
        ))}
        <label className="dx-prod">
          <span>Sản phẩm</span>
          <select data-testid="dx-product" onChange={(e) => go(host.href({ metric, product: e.target.value || null }))} value={product ?? ""}>
            <option value="">Tất cả sản phẩm</option>
            {productIds.map((id) => (
              <option key={id} value={id}>
                {names[id] ?? id}
              </option>
            ))}
          </select>
        </label>
      </div>
      <FlashNotice flash={flash} />
      {shown.length === 0 ? <Empty testId="sd-empty">{EMPTY_DE_XUAT}</Empty> : <TopCards cards={shown} flash={flash} inPlan={inPlan} names={names} onChanged={onChanged} onFlash={setFlash} />}
    </>
  );
}

/** The finding of the header: "4 thẻ cho CTR · +a – b đ lợi nhuận cả 30 ngày". */
export function findingOf(shown: readonly CardSummary[], metric: MetricKey | null): string {
  if (shown.length === 0) return "Chưa có thẻ nào";
  let lo = 0;
  let hi = 0;
  let ok = true;
  for (const c of shown) {
    const q = c.predicted_summary.dprofit_month;
    if (q.p10 === null || q.p90 === null) ok = false;
    else {
      lo += Math.min(q.p10, q.p90);
      hi += Math.max(q.p10, q.p90);
    }
  }
  const days = cardDays(shown[0]!);
  const head = `${fmt(shown.length, 0)} thẻ${metric ? ` cho ${METRIC_NAME[metric]}` : ""}`;
  return ok ? `${head} · ${rangeText({ p10: lo, p90: hi })} lợi nhuận cả ${fmt(days, 0)} ngày` : head;
}

function ShopShell({ params }: { readonly params: URLSearchParams }) {
  const host = useReco();
  const tab = tabOfParam(params.get("tab"));
  const xem = xemOfParams(params);
  const metric = metricOfParam(params.get("metric"));
  const product = params.get("product");
  const [tick, setTick] = useState(0);
  const [flash, setFlash] = useState<Flash>(NO_FLASH);
  const list = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|list|${tick}`);
  const planRes = useResource(() => (host.plan ? host.plan.api.get() : Promise.resolve(null)), `${host.shopKey}|plan-count|${tick}`);
  const prodRes = useResource(() => (host.products ? host.products() : Promise.resolve([])), `${host.shopKey}|products`);
  const plan = planRes.status === "ready" ? planRes.data : null;
  const names: Record<string, string> = {};
  if (prodRes.status === "ready") for (const p of prodRes.data) names[p.id] = p.name;
  const inPlan = new Set((plan?.cards ?? []).map((c) => c.card_id));
  const planCount = plan?.cards ? plan.cards.length : null;
  const cardsAll = list.status === "ready" ? list.data.cards : [];
  const tops = topEntries(cardsAll).map((e) => e.top);
  const counts = { ...tabCounts(cardsAll), "de-xuat": tops.length };
  const shown = filterCards(tops, metric, product);
  const title = tab === "de-xuat" ? (xem === "ke-hoach" ? "Kế hoạch nháp" : findingOf(shown, metric)) : `${fmt(counts[tab], 0)} thẻ`;
  const frame = (t: string, eyebrow: string | undefined, children: ReactNode) => (
    <ShellFrame counts={counts} eyebrow={eyebrow} planCount={planCount} tab={tab} title={t} xem={xem}>
      {children}
    </ShellFrame>
  );
  if (tab === "de-xuat" && xem === "ke-hoach") return <PlanView frame={(t, children) => frame(t, "QUYẾT ĐỊNH · ĐỀ XUẤT · KẾ HOẠCH NHÁP", children)} onChanged={() => setTick((t) => t + 1)} />;
  return frame(
    title,
    undefined,
    tab === "thuc-hien" ? (
      <ThucHienView />
    ) : tab === "do-luong" ? (
      <DoLuongView />
    ) : (
      <RecoState resource={list}>{() => <CardsView cards={tops} flash={flash} inPlan={inPlan} metric={metric} names={names} onChanged={() => setTick((t) => t + 1)} product={product} setFlash={setFlash} />}</RecoState>
    ),
  );
}

/** The P92 builder; with the P98 client it also gets the shop's KOL rows for the KOL builder. */
function BuilderWithP98({ from, productId }: { readonly from: string | null; readonly productId: string | null }) {
  const host = useReco();
  const [kols, setKols] = useState<readonly KolCandidate[]>([]);
  useEffect(() => {
    let live = true;
    if (host.p98 && host.kols) host.kols().then((k) => live && setKols(k), () => undefined);
    return () => {
      live = false;
    };
    // The list is per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host.shopKey]);
  return <BuilderP92View from={from} kols={kols} p98Api={host.p98} productId={productId} />;
}

export function DecisionsView({ params }: { readonly params: URLSearchParams }) {
  const host = useReco();
  const the = params.get("the");
  if (the) return <CardPage from={params.get("from")} id={the} version={Number(params.get("v")) || null} />;
  if (params.get("tu-tao")) return host.builder ? <BuilderWithP98 from={params.get("from")} productId={params.get("sp")} /> : <BuilderView from={params.get("from")} productId={params.get("sp")} />;
  if (host.staff) return xemOfParams(params) === "ke-hoach" ? <PlanView /> : <OpsRecoList />;
  return <ShopShell params={params} />;
}
