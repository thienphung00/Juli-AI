"use client";

import { useEffect, useState } from "react";

import { DASH, fmt, sv } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { TABS, isWorthTrying, sectionsFor, statusLabel, tabCounts, tabOfParam, type DecisionTab } from "../../lib/shopee-decisions/model";
import type { CardList, CardSummary } from "../../lib/shopee-decisions/types";
import { Empty, Notice, Section, TextChip } from "../shopee-analytics/ui";
import { BuilderView } from "./builder";
import { BuilderP92View } from "./builder-p92";
import { CardPage } from "./card-page";
import type { KolCandidate } from "./kol-builder";
import { OpsRecoList } from "./ops-list";
import { PlanView } from "./plan";
import { StaffBar } from "./staff-bar";
import { FlashNotice, NO_FLASH, TopCards, topEntries, type Flash } from "./top-cards";
import { NavLink, RecoState, StatusChip } from "./ui";

/**
 * Quyết định for a Shopee shop: the cards in sections by family (Quảng cáo, Khuyến mãi, Voucher,
 * Sale, Combo, Tiếp thị liên kết, Mega sale), each in ranking order, under three tabs - Đề xuất,
 * Đang thực hiện, Đo lường. `?the=<card id>` opens one card (the analytics screens link there).
 */

const TAB_HINT: Readonly<Record<DecisionTab, string>> = {
  "de-xuat": "Thẻ đang chờ bạn quyết định. Xếp theo mức đáng làm nhất ở mỗi nhóm.",
  "dang-thuc-hien": "Thẻ đã duyệt: làm trên Seller Centre rồi bấm “Đã làm”, hoặc đang chờ Juli xác minh.",
  "do-luong": "Thẻ đã làm và đã xác minh: đếm ngược 14/28 ngày và kết quả.",
};

const EMPTY: Readonly<Record<DecisionTab, string>> = {
  "de-xuat": "Chưa có đề xuất nào đang chờ. Khi Juli có thẻ mới, thẻ hiện ở đây.",
  "dang-thuc-hien": "Chưa có thẻ nào đang thực hiện.",
  "do-luong": "Chưa có thẻ nào đang được đo.",
};

/** A figure over the card's own days, per day. */
function perDay(n: number | null | undefined, days: number): number | null {
  return typeof n === "number" ? n / Math.max(1, days || 1) : null;
}

function moneyRange(q: { readonly p10: number | null; readonly p90: number | null }): string {
  if (q.p10 === null || q.p90 === null) return DASH;
  const lo = Math.min(q.p10, q.p90);
  const hi = Math.max(q.p10, q.p90);
  return Math.round(lo) === Math.round(hi) ? sv(lo) : `${sv(lo)} – ${sv(hi)}`;
}

function CardRow({ card, from }: { readonly card: CardSummary; readonly from: string | null }) {
  const host = useReco();
  return (
    <li className="sd-row" data-testid={`sd-card-${card.id}`}>
      <div className="sd-row__main">
        <NavLink className="sd-row__title" href={host.href({ the: card.id, from })}>
          {card.title}
        </NavLink>
        <span className="sd-row__chips">
          {isWorthTrying(card) ? <TextChip tone="pink">đáng thử</TextChip> : null}
          <StatusChip status={card.status} />
          {card.stale ? <TextChip tone="warn">Đang cập nhật</TextChip> : null}
          {!card.floor_ok ? <TextChip tone="down">Chạm giá sàn</TextChip> : null}
          {card.bundle ? <TextChip tone="info">Đo như một gói</TextChip> : null}
        </span>
        {card.reason ? <span className="sa-hint sd-row__reason">{card.reason}</span> : null}
      </div>
      <dl className="sd-row__nums">
        <div>
          <dt>Chắc chắn / ngày</dt>
          <dd>
            {sv(perDay(card.certain_summary.dprofit_month, card.predicted_summary.effect_days))} lợi nhuận · {fmt(card.predicted_summary.effect_days, 0)} ngày: {sv(card.certain_summary.dprofit_month)}
          </dd>
        </div>
        <div>
          <dt>Dự kiến / ngày</dt>
          <dd>
            {moneyRange({ p10: perDay(card.predicted_summary.dprofit_month.p10, card.predicted_summary.effect_days), p90: perDay(card.predicted_summary.dprofit_month.p90, card.predicted_summary.effect_days) })} lợi nhuận · {fmt(card.predicted_summary.effect_days, 0)} ngày: {moneyRange(card.predicted_summary.dprofit_month)}
          </dd>
        </div>
        <div>
          <dt>Đo</dt>
          <dd>{card.plan}</dd>
        </div>
      </dl>
    </li>
  );
}

function ListBody({ tab, from }: { readonly tab: DecisionTab; readonly from: string | null }) {
  const host = useReco();
  const [tick, setTick] = useState(0);
  const [flash, setFlash] = useState<Flash>(NO_FLASH);
  const res = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|list|${tick}`);
  return (
    <>
      {host.staff ? <StaffBar onChanged={() => setTick((t) => t + 1)} /> : null}
      <FlashNotice flash={flash} />
      <RecoState resource={res}>
        {(data) => {
          const cards = data.cards;
          const tops = topEntries(cards);
          const counts = { ...tabCounts(cards), "de-xuat": tops.length };
          const sections = sectionsFor(cards, tab);
          return (
            <>
              <nav aria-label="Quyết định" className="sa-seg sa-seg--round sa-tabs" data-testid="sd-tabs">
                {TABS.map(([key, label]) => (
                  <NavLink className={`sa-seg__item ${tab === key ? "sa-seg__item--on" : ""}`} href={host.href({ tab: key })} key={key}>
                    {label} · {fmt(counts[key], 0)}
                  </NavLink>
                ))}
              </nav>
              <p className="sa-hint">{TAB_HINT[tab]}</p>
              {tab === "de-xuat" ? (
                tops.length === 0 ? (
                  <Empty testId="sd-empty">{EMPTY[tab]}</Empty>
                ) : (
                  <TopCards cards={cards} flash={flash} onChanged={() => setTick((t) => t + 1)} onFlash={setFlash} />
                )
              ) : sections.length === 0 ? (
                <Empty testId="sd-empty">{EMPTY[tab]}</Empty>
              ) : (
                sections.map((s) => (
                  <Section aside={`${fmt(s.cards.length, 0)} thẻ`} key={s.family} testId={`sd-section-${s.family}`} title={s.title}>
                    <ul className="sd-list">
                      {s.cards.map((c) => (
                        <CardRow card={c} from={from} key={c.id} />
                      ))}
                    </ul>
                  </Section>
                ))
              )}
              {host.staff ? <p className="sa-hint">Trạng thái các thẻ: {[...new Set(cards.map((c) => statusLabel(c.status)))].join(" · ") || DASH}.</p> : null}
            </>
          );
        }}
      </RecoState>
    </>
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
  const planRes = useResource(() => (host.plan ? host.plan.api.get().then((p) => p.cards.length) : Promise.resolve(null)), `${host.shopKey}|plan-count`);
  const planCount = planRes.status === "ready" ? planRes.data : null;
  const the = params.get("the");
  const tab = tabOfParam(params.get("tab"));
  if (the) return <CardPage from={params.get("from")} id={the} version={Number(params.get("v")) || null} />;
  if (params.get("ke-hoach")) return <PlanView />;
  if (params.get("tu-tao")) return host.builder ? <BuilderWithP98 from={params.get("from")} productId={params.get("sp")} /> : <BuilderView from={params.get("from")} productId={params.get("sp")} />;
  if (host.staff) return <OpsRecoList />;
  return (
    <div className="sa-page" data-testid="sd-list">
      <header className="sa-head">
        <div className="sa-eyebrow">QUYẾT ĐỊNH · ĐỀ XUẤT</div>
        <div className="sa-head__line sq-head">
          <h1 className="sa-h1">{tab === "de-xuat" ? "Mỗi sản phẩm một thẻ, thẻ kế tiếp lên ngay" : "Đề xuất cho shop Shopee"}</h1>
          {host.shopName ? <span className="sa-head__right">{host.shopName}</span> : null}
        </div>
        {tab === "de-xuat" ? <p className="sa-hint">Thẻ đóng (bỏ qua, hết hạn), đã thực hiện hoặc đã thêm vào kế hoạch thì thẻ kế tiếp của sản phẩm lên Quyết định ngay.</p> : null}
        {!host.readOnly ? (
          <div className="sq-head__actions">
            <NavLink className="sa-btn sa-btn--s" href={host.href({ builder: true, from: "quyet-dinh" })} testId="sq-builder-link">
              + Tự tạo phương án
            </NavLink>
            {host.plan ? (
              <NavLink className="sa-btn sa-btn--s" href={host.href({ plan: true })} testId="sq-plan-link">
                Kế hoạch{planCount === null ? "" : ` (${planCount})`}
              </NavLink>
            ) : null}
          </div>
        ) : null}
      </header>
      {host.readOnly ? <Notice tone="info">Chế độ xem: đọc và thử “nếu đổi”, không duyệt hay ghi được thay seller.</Notice> : null}
      <ListBody from={params.get("from")} key={host.shopKey} tab={tab} />
    </div>
  );
}
