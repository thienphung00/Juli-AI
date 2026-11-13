"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import type { ShopeeLinks } from "../../lib/shopee-analytics/links";
import { DASH, fmt } from "../../lib/shopee-analytics/format";
import type { RecoApi } from "../../lib/shopee-decisions/client";
import type { CardSummary, CardVersion } from "../../lib/shopee-decisions/types";
import { sm, srange, unitsOf } from "../../lib/shopee-decisions/units";
import { PRODUCT_GROUPS, firstVersionRange, isOpen, queueLabel, rangeTone, versionFlag, versionsOf, CLOSED_STATUSES } from "../../lib/shopee-decisions/versions";
import { TextChip } from "../shopee-analytics/ui";

/**
 * Sản phẩm › Đề xuất (`SanPhamDeXuat.dc.html`, mobile `SanPhamDeXuatMobile.dc.html`): every open card of
 * one product, grouped by family or in queue order, each with its code, its place in the queue
 * (`#1 · Đang ở Quyết định`, `#2 · Xếp hàng` …) and its versions one tap away. Quyết định shows only
 * the first of them; the rest wait here.
 */

type View = "family" | "queue";

const toneClass = (t: ReturnType<typeof rangeTone>): string => (t === "up" ? "sa-tone--up" : t === "down" ? "sa-tone--down" : "");

export function openCardsOf(cards: readonly CardSummary[]): CardSummary[] {
  return cards.filter(isOpen).sort((a, b) => (a.product_queue ?? 1e6) - (b.product_queue ?? 1e6));
}

export function ProposalsTab({
  cards,
  links,
  reco,
  builderHref,
  historyHref,
}: {
  readonly reco: RecoApi;
  readonly cards: readonly CardSummary[];
  readonly links: ShopeeLinks;
  readonly builderHref: string;
  readonly historyHref: string;
}) {
  const open = useMemo(() => openCardsOf(cards), [cards]);
  const [view, setView] = useState<View>("family");
  const [expanded, setExpanded] = useState<readonly string[]>(() => open.slice(0, 1).map((c) => c.id));
  const toggle = (id: string) => setExpanded((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const closed = cards.filter((c) => CLOSED_STATUSES.includes(c.status));
  const closedParts = [
    closed.filter((c) => c.status === "executed").length ? `${closed.filter((c) => c.status === "executed").length} đã thực hiện` : "",
    closed.filter((c) => c.status === "rejected").length ? `${closed.filter((c) => c.status === "rejected").length} bỏ qua` : "",
    closed.filter((c) => c.status === "expired").length ? `${closed.filter((c) => c.status === "expired").length} hết hạn` : "",
  ].filter(Boolean);
  const groups = view === "family" ? PRODUCT_GROUPS.map(([k, name]) => ({ name, cards: open.filter((c) => c.family === k) })).filter((g) => g.cards.length > 0) : [{ name: "", cards: open }];

  return (
    <section className="sa-card sp" data-testid="sp-proposals">
      <div className="sa-card__head sp-head">
        <div>
          <h2 className="sa-h2">Đề xuất cho sản phẩm này</h2>
          <p className="sa-hint" data-testid="sp-intro">
            {open.length} thẻ đang mở, nhóm theo họ đề xuất. Quyết định chỉ hiện thẻ số 1 của sản phẩm; các thẻ còn lại xếp hàng và lên Quyết định ngay khi thẻ trước đóng, được thực hiện hoặc được thêm vào kế hoạch.
          </p>
        </div>
        <Link className="sa-btn sa-btn--s" data-testid="sp-builder" href={builderHref}>
          + Tự tạo phương án
        </Link>
      </div>

      <div className="sp-bar">
        <div className="sa-seg sa-seg--round">
          {(
            [
              ["family", "Theo họ đề xuất"],
              ["queue", "Theo thứ tự hàng đợi"],
            ] as const
          ).map(([k, label]) => (
            <button aria-pressed={view === k} className={`sa-seg__item ${view === k ? "sa-seg__item--on" : ""}`} key={k} onClick={() => setView(k)} type="button">
              {label}
            </button>
          ))}
        </div>
        <div className="sp-dots" data-testid="sp-dots">
          <span className="sa-hint">Hàng đợi:</span>
          {open.map((c) => (
            <span className={`sp-dot ${c.product_queue === 1 ? "sp-dot--top" : ""}`} key={c.id} title={`${c.code ?? c.id} · ${c.family_label}`}>
              {c.product_queue ?? "·"}
            </span>
          ))}
        </div>
      </div>

      {open.length === 0 ? <p className="sa-hint" data-testid="sp-empty">Sản phẩm này chưa có đề xuất nào đang mở.</p> : null}

      {groups.map((g) => (
        <div className="sp-group" key={g.name || "all"}>
          {g.name ? (
            <div className="sp-group__head">
              <h3>{g.name}</h3>
              <span className="sa-hint">{g.cards.length} thẻ</span>
            </div>
          ) : null}
          {g.cards.map((c) => (
            <CardBlock card={c} expanded={expanded.includes(c.id)} key={c.id} links={links} onToggle={() => toggle(c.id)} reco={reco} />
          ))}
        </div>
      ))}

      <div className="sp-foot">
        <span>
          Đã đóng gần đây: {closed.length} thẻ{closedParts.length ? ` (${closedParts.join(", ")})` : ""} ·{" "}
          <Link className="sa-link" href={historyHref}>
            Xem lịch sử thẻ ›
          </Link>
        </span>
        <span className="sa-hint">Mã thẻ (JC-…) dùng để tra cứu thẻ.</span>
      </div>
    </section>
  );
}

function CardBlock({ card, expanded, onToggle, links, reco }: { readonly card: CardSummary; readonly expanded: boolean; readonly onToggle: () => void; readonly links: ShopeeLinks; readonly reco: RecoApi }) {
  const top = card.product_queue === 1;
  const q = card.predicted_summary.dprofit_month;
  const briefs = card.versions ?? [];
  const [full, setFull] = useState<readonly CardVersion[] | null>(null);
  useEffect(() => {
    if (!expanded || full) return;
    let live = true;
    reco.detail(card.id).then(
      (d) => live && setFull(versionsOf(d.card)),
      () => live && setFull([]),
    );
    return () => {
      live = false;
    };
  }, [expanded, full, reco, card.id]);
  const href = links.card(card.id, "san-pham");
  return (
    <div className={`sp-card ${top ? "sp-card--top" : ""}`} data-testid={`sp-card-${card.id}`}>
      <div className="sp-card__row">
        <span className="sp-card__id">
          <span className="sd-code">{card.code ?? card.id}</span>
          <span className="sa-chip sa-chip--outline">{card.family_label}</span>
        </span>
        <TextChip tone={top ? "pink" : "flat"}>{card.status === "approved" ? "Đang thực hiện" : queueLabel(card.product_queue)}</TextChip>
        <span className="sp-card__title">
          <b>{card.title}</b>
          <span className="sa-hint">
            {briefs.length} phiên bản{briefs.length > 0 ? `: ${briefs.map((v) => `V${v.version}${versionFlag(v) ? ` (${versionFlag(v).toLowerCase()})` : ""}`).join(" · ")}` : ""}
          </span>
        </span>
        <span className="sp-card__d">
          <span className="sa-hint">Δ lợi nhuận (V1, dự kiến)</span>
          <b className={toneClass(rangeTone(q.p10, q.p90))}>{firstVersionRange(card)}</b>
        </span>
        {briefs.length > 0 ? (
          <button aria-expanded={expanded} className="sa-btn sa-btn--s" onClick={onToggle} type="button">
            {expanded ? "Thu gọn" : "Xem phiên bản"}
          </button>
        ) : (
          <Link className="sa-btn sa-btn--s" href={href}>
            Mở thẻ ›
          </Link>
        )}
      </div>
      {expanded && briefs.length > 0
        ? briefs.map((b, i) => {
            const v = full?.find((x) => x.version === b.version);
            const pm = v?.predicted?.money_per_month;
            const t = pm?.total;
            const vu = v?.predicted ? unitsOf(v as { predicted: NonNullable<typeof v.predicted> }) : null;
            return (
              <div className="sp-ver" data-testid={`sp-ver-${card.id}-${b.version}`} key={b.version}>
                <span className="sd-code">{b.code ?? `${card.code ?? ""}-V${b.version}`}</span>
                <b className={i === 0 ? "sp-ver__n sp-ver__n--1" : "sp-ver__n"}>V{b.version}</b>
                <span>
                  {b.label ?? `V${b.version}`}
                  {i === 0 ? " · Juli đề xuất" : ""} {versionFlag(b) ? <TextChip tone="down">{versionFlag(b)}</TextChip> : null}
                </span>
                <span>
                  Chắc chắn <b>{vu ? `${sm(vu.perDay.certain)}/ngày` : full ? DASH : "…"}</b>
                </span>
                <b className={toneClass(rangeTone(t?.p10.dprofit, t?.p90.dprofit))}>{vu ? `${srange(vu.perDay.p10, vu.perDay.p90)}/ngày · ${fmt(vu.days, 0)} ngày: ${srange(vu.period.p10, vu.period.p90)}` : full ? DASH : "…"}</b>
                <Link className="sa-link" href={`${href}&v=${b.version}`}>
                  Mở thẻ ›
                </Link>
              </div>
            );
          })
        : null}
    </div>
  );
}
