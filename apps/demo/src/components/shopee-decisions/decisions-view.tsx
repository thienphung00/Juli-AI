"use client";

import { useState } from "react";

import { DASH, fmt, sv } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { TABS, isWorthTrying, sectionsFor, statusLabel, tabCounts, tabOfParam, type DecisionTab } from "../../lib/shopee-decisions/model";
import type { CardList, CardSummary } from "../../lib/shopee-decisions/types";
import { Empty, Notice, PageHead, Section, TextChip } from "../shopee-analytics/ui";
import { CardPage } from "./card-page";
import { NavLink, RecoState, StatusChip, errorText } from "./ui";

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

function StaffBar({ onChanged }: { readonly onChanged: () => void }) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const act = async (label: string, call: () => Promise<string>) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(`${label}: ${await call()}`);
      onChanged();
    } catch (e) {
      setMsg(`${label}: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="sa-card sd-staff" data-testid="sd-staffbar">
      <div className="sa-card__head">
        <h2 className="sa-h2">Việc của Ops</h2>
        <span className="sa-hint">Tạo thẻ từ số liệu mới nhất (nháp), gửi cho shop, hoặc tính lại thẻ khi thông số shop đổi.</span>
      </div>
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" disabled={busy} onClick={() => void act("Tạo đề xuất", async () => `${(await host.reco.generate({ topN: 10 })).persisted} thẻ nháp`)} type="button">
          Tạo đề xuất
        </button>
        <button className="sa-btn" disabled={busy} onClick={() => void act("Gửi cho shop", async () => `${(await host.reco.publish(null)).sent.length} thẻ đã gửi`)} type="button">
          Gửi tất cả nháp cho shop
        </button>
        <button className="sa-btn" disabled={busy} onClick={() => void act("Tính lại thẻ cũ", async () => JSON.stringify(await host.reco.rerunStale()))} type="button">
          Tính lại thẻ cũ
        </button>
      </div>
      {msg ? (
        <p className="sa-hint" data-testid="sd-staff-msg" role="status">
          {msg}
        </p>
      ) : null}
    </section>
  );
}

function ListBody({ tab, from }: { readonly tab: DecisionTab; readonly from: string | null }) {
  const host = useReco();
  const [tick, setTick] = useState(0);
  const res = useResource<CardList>(() => host.reco.list({}), `${host.shopKey}|list|${tick}`);
  return (
    <>
      {host.staff ? <StaffBar onChanged={() => setTick((t) => t + 1)} /> : null}
      <RecoState resource={res}>
        {(data) => {
          const counts = tabCounts(data.cards);
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
              {sections.length === 0 ? (
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
  if (the) return <CardPage from={params.get("from")} id={the} />;
  return (
    <div className="sa-page" data-testid="sd-list">
      <PageHead
        eyebrow="QUYẾT ĐỊNH"
        right={host.shopName ?? undefined}
        title="Đề xuất cho shop Shopee"
      />
      {host.readOnly ? <Notice tone="info">Chế độ xem: đọc và thử “nếu đổi”, không duyệt hay ghi được thay seller.</Notice> : null}
      <ListBody from={params.get("from")} key={host.shopKey} tab={tab} />
    </div>
  );
}
