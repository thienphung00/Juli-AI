"use client";

import { useState } from "react";

import { DASH, fmt, sv } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { TABS, isWorthTrying, sectionsFor, statusLabel, tabCounts, tabOfParam, type DecisionTab } from "../../lib/shopee-decisions/model";
import type { CardList, CardSummary } from "../../lib/shopee-decisions/types";
import { Empty, Notice, PageHead, Section, TextChip } from "../shopee-analytics/ui";
import { BuilderView } from "./builder";
import { CardPage } from "./card-page";
import { OpsRecoList } from "./ops-list";
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
          {card.stale ? <TextChip tone="warn">Cần tính lại</TextChip> : null}
          {!card.floor_ok ? <TextChip tone="down">Chạm giá sàn</TextChip> : null}
          {card.bundle ? <TextChip tone="info">Đo như một gói</TextChip> : null}
        </span>
        {card.reason ? <span className="sa-hint sd-row__reason">{card.reason}</span> : null}
      </div>
      <dl className="sd-row__nums">
        <div>
          <dt>Chắc chắn / tháng</dt>
          <dd>{sv(card.certain_summary.dprofit_month)} lợi nhuận</dd>
        </div>
        <div>
          <dt>Dự kiến / tháng</dt>
          <dd>{moneyRange(card.predicted_summary.dprofit_month)} lợi nhuận</dd>
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
          const tops = topEntries(data.cards);
          const counts = { ...tabCounts(data.cards), "de-xuat": tops.length };
          const sections = sectionsFor(data.cards, tab);
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
                  <TopCards cards={data.cards} flash={flash} onChanged={() => setTick((t) => t + 1)} onFlash={setFlash} />
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
              {host.staff ? <p className="sa-hint">Trạng thái các thẻ: {[...new Set(data.cards.map((c) => statusLabel(c.status)))].join(" · ") || DASH}.</p> : null}
            </>
          );
        }}
      </RecoState>
    </>
  );
}

export function DecisionsView({ params }: { readonly params: URLSearchParams }) {
  const host = useReco();
  const the = params.get("the");
  const tab = tabOfParam(params.get("tab"));
  if (the) return <CardPage from={params.get("from")} id={the} version={Number(params.get("v")) || null} />;
  if (params.get("tu-tao")) return <BuilderView from={params.get("from")} productId={params.get("sp")} />;
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
                Kế hoạch
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
