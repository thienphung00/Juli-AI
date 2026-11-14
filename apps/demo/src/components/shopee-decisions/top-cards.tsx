"use client";

import { useState } from "react";

import { DASH, fmt, vnd } from "../../lib/shopee-analytics/format";
import { kindLabel, metricsOfCard } from "../../lib/shopee-decisions/model";
import { MetricChip } from "../metrics/metric-chip";
import { useReco } from "../../lib/shopee-decisions/context";
import type { CardSummary } from "../../lib/shopee-decisions/types";
import { isOpen, rangeTone } from "../../lib/shopee-decisions/versions";
import { Notice, TextChip } from "../shopee-analytics/ui";
import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import type { Breach } from "../../lib/shopee-decisions/types";
import { breachNoun, breachWarnLines } from "../../lib/shopee-decisions/versions";
import { BreachDialog } from "./versions";
import { NavLink, errorText } from "./ui";

/**
 * Quyết định · Đề xuất (`QuyetDinhHangDoi.dc.html`): one card per product, the one with
 * `product_queue = 1`; the rest of the product's cards wait behind it ("Tiếp theo cho sản phẩm này").
 * When the card closes - bỏ qua, hết hạn, đã thực hiện, thêm vào kế hoạch - the next one is on top at
 * once. A product still being measured says so on its card; approving stays possible (D-7).
 */

export interface TopEntry {
  readonly top: CardSummary;
  readonly next: CardSummary | null;
  /** Open cards of the product behind the top one. */
  readonly behind: number;
}

/** The top card of each product and what comes next; cards that are about no product stand alone. */
export function topEntries(cards: readonly CardSummary[]): TopEntry[] {
  const open = cards.filter((c) => isOpen(c) && (c.status !== "approved"));
  const byProduct = new Map<string, CardSummary[]>();
  const loose: CardSummary[] = [];
  for (const c of open) {
    if (!c.product_id) loose.push(c);
    else byProduct.set(c.product_id, [...(byProduct.get(c.product_id) ?? []), c]);
  }
  const out: TopEntry[] = [];
  for (const group of byProduct.values()) {
    const sorted = [...group].sort((a, b) => (a.product_queue ?? 1e6) - (b.product_queue ?? 1e6));
    const top = sorted[0]!;
    out.push({ top, next: sorted[1] ?? null, behind: sorted.length - 1 });
  }
  for (const c of loose) out.push({ top: c, next: null, behind: 0 });
  const order = new Map(cards.map((c, i) => [c.id, i]));
  return out.sort((a, b) => (order.get(a.top.id) ?? 0) - (order.get(b.top.id) ?? 0));
}

type Notice_ = { readonly text: string; readonly tone: "plain" | "ok" | "info"; readonly planLink?: boolean };

const MINUS = "−";
const money = (n: number): string => `${n < 0 ? MINUS : "+"}${vnd(Math.abs(Math.round(n)))}`;

/** "+a – b đ" of a quantile pair; "—" without both ends. */
export function rangeText(q: { readonly p10: number | null; readonly p90: number | null }, days = 1): string {
  if (q.p10 === null || q.p90 === null) return DASH;
  const lo = Math.min(q.p10, q.p90) / days;
  const hi = Math.max(q.p10, q.p90) / days;
  return Math.round(lo) === Math.round(hi) ? money(lo) : `${money(lo)} – ${money(hi)}`;
}

/** The card's own days (the Δ totals stand on them). */
export const cardDays = (c: Pick<CardSummary, "predicted_summary">): number => Math.max(1, c.predicted_summary.effect_days || 30);

/** A card with one version is approved from the list; with several the seller picks the version on the card. */
export const approvesInPlace = (card: Pick<CardSummary, "versions">): boolean => (card.versions?.length ?? 1) <= 1;

export function CardRow({ card, name, inPlan, canAct, busy, onPlan, onApprove }: { readonly card: CardSummary; readonly name?: string | null; readonly inPlan: boolean; readonly canAct: boolean; readonly busy: boolean; readonly onPlan: (c: CardSummary, add: boolean) => void; readonly onApprove?: (c: CardSummary) => void }) {
  const host = useReco();
  const days = cardDays(card);
  const q = card.predicted_summary.dprofit_month;
  const tone = rangeTone(q.p10, q.p90);
  const g = card.predicted_summary.dgmv_month;
  const href = host.href({ the: card.id, from: "quyet-dinh" });
  return (
    <article className={`sq-card dx-card ${inPlan ? "dx-card--in" : ""}`} data-testid={`sq-card-${card.id}`}>
      <div className="dx-card__top">
        <div className="dx-card__main">
          <div className="dx-card__group">
            <span>
              {[card.family_label, kindLabel(card)].filter(Boolean).join(" · ")}
            </span>
            {inPlan ? <TextChip tone="pink">Trong kế hoạch nháp</TextChip> : null}
            {card.stale ? <TextChip tone="warn">Đang cập nhật</TextChip> : null}
            {!card.floor_ok ? <TextChip tone="down">Chạm giá sàn</TextChip> : null}
          </div>
          <h2 className="dx-card__title">
            <NavLink href={href}>{card.title}</NavLink>
          </h2>
          {card.product_id ? <div className="dx-card__product">{name ?? card.product_id}</div> : null}
        </div>
        <div className="dx-card__delta">
          <div className="dx-card__label">Δ lợi nhuận cả {fmt(days, 0)} ngày</div>
          <div className={`dx-card__big ${tone === "up" ? "sa-tone--up" : tone === "down" ? "sa-tone--down" : ""}`} data-testid="dx-dprofit">
            {rangeText(q)}
          </div>
          <div className="dx-card__perday" data-testid="dx-perday">
            ≈ {rangeText(q, days)}/ngày
          </div>
        </div>
      </div>
      <div className="dx-card__chips">
        {metricsOfCard(card).map((m) => (
          <MetricChip key={m} metric={m} />
        ))}
        <span data-testid="dx-dgmv">Δ GMV {rangeText(g)}</span>
        {typeof card.cost === "number" && card.cost > 0 ? (
          <span data-testid="dx-cost">
            · <b>Chi phí:</b> {vnd(Math.round(card.cost))}
          </span>
        ) : null}
      </div>
      <div className="sd-actions">
        <NavLink className="sa-btn sa-btn--s" href={href}>
          Xem &amp; sửa
        </NavLink>
        <NavLink className="sa-btn sa-btn--s" href={host.href({ builder: true, productId: card.product_id ?? null, from: "quyet-dinh" })}>
          So sánh
        </NavLink>
        {host.plan ? (
          <button className="sa-btn sa-btn--s" data-testid="sq-plan" disabled={!canAct || busy} onClick={() => onPlan(card, !inPlan)} type="button">
            {inPlan ? "Bỏ khỏi kế hoạch" : "Thêm vào kế hoạch"}
          </button>
        ) : null}
        {onApprove && canAct && approvesInPlace(card) ? (
          <button className="sa-btn sa-btn--s sa-btn--primary" data-testid="sq-approve" disabled={busy} onClick={() => onApprove(card)} type="button">
            Duyệt
          </button>
        ) : (
          <NavLink className="sa-btn sa-btn--s sa-btn--primary" href={href}>
            Duyệt
          </NavLink>
        )}
      </div>
    </article>
  );
}

/** What the last action said, kept by the list so it survives the reload that follows the action. */
export interface Flash {
  readonly notice: Notice_ | null;
  readonly justUp: Readonly<Record<string, string>>;
}

export const NO_FLASH: Flash = { notice: null, justUp: {} };

export function FlashNotice({ flash }: { readonly flash: Flash }) {
  const host = useReco();
  return flash.notice ? (
    <Notice tone="info" testId="sq-notice">
      {flash.notice.text}
      {flash.notice.planLink ? (
        <>
          {" "}
          <NavLink className="sa-link" href={host.href({ plan: true })}>
            Xem kế hoạch ›
          </NavLink>
        </>
      ) : null}
    </Notice>
  ) : null;
}

export function TopCards({ cards, names, inPlan, flash, onFlash, onChanged }: { readonly cards: readonly CardSummary[]; readonly names: Readonly<Record<string, string>>; readonly inPlan: ReadonlySet<string>; readonly flash: Flash; readonly onFlash: (f: Flash) => void; readonly onChanged: () => void }) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState<{ readonly card: CardSummary; readonly breaches: readonly Breach[]; readonly mode: "plan" | "approve" } | null>(null);
  const canAct = !host.readOnly && !host.staff;
  const toggle = async (card: CardSummary, add: boolean, acknowledge: boolean) => {
    const plan = host.plan;
    if (!plan) return;
    setBusy(true);
    try {
      if (add) await plan.api.add(card.id, null, acknowledge);
      else await plan.api.remove(card.id);
      onFlash({ notice: null, justUp: flash.justUp });
      setPlanning(null);
      onChanged();
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code.startsWith("reco_breach") && Array.isArray(e.detail?.["breaches"])) setPlanning({ card, breaches: e.detail["breaches"] as Breach[], mode: "plan" });
      else onFlash({ notice: { text: errorText(e), tone: "plain" }, justUp: flash.justUp });
    } finally {
      setBusy(false);
    }
  };
  // Duyệt on a one-version card: the same approve call as "Duyệt V1" on the card page; the list reloads without it
  const approve = async (card: CardSummary, acknowledge: boolean) => {
    setBusy(true);
    try {
      await host.reco.approve(card.id, { chosenVersion: 1, acknowledgeBreaches: acknowledge });
      onFlash({ notice: { text: `Đã duyệt ${card.code ?? card.title} · chuyển sang Thực hiện`, tone: "ok" }, justUp: flash.justUp });
      setPlanning(null);
      onChanged();
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code.startsWith("reco_breach") && Array.isArray(e.detail?.["breaches"])) setPlanning({ card, breaches: e.detail["breaches"] as Breach[], mode: "approve" });
      else onFlash({ notice: { text: errorText(e), tone: "plain" }, justUp: flash.justUp });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {cards.map((c) => (
        <CardRow name={c.product_id ? names[c.product_id] : null} busy={busy} canAct={canAct} card={c} inPlan={inPlan.has(c.id)} key={c.id} onApprove={(x) => void approve(x, false)} onPlan={(x, add) => void toggle(x, add, false)} />
      ))}
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể tiếp tục. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ này."
        goLabel="Vẫn tiếp tục"
        lines={planning ? breachWarnLines(planning.breaches) : []}
        onBack={() => setPlanning(null)}
        onGo={() => planning && void (planning.mode === "approve" ? approve(planning.card, true) : toggle(planning.card, true, true))}
        open={planning !== null}
        title={planning ? `${planning.mode === "approve" ? "Duyệt" : "Thêm"} ${planning.card.code ?? planning.card.id}${planning.mode === "approve" ? "" : " vào kế hoạch"} dù ${breachNoun(planning.breaches)}?` : ""}
      />
    </>
  );
}
