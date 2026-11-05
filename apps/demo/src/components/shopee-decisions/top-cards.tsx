"use client";

import { useState } from "react";

import { fmt } from "../../lib/shopee-analytics/format";
import { useReco } from "../../lib/shopee-decisions/context";
import type { CardSummary } from "../../lib/shopee-decisions/types";
import { firstVersionRange, isOpen, measuringDaysLeft, measuringNote, rangeTone } from "../../lib/shopee-decisions/versions";
import { Notice, TextChip } from "../shopee-analytics/ui";
import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import type { Breach } from "../../lib/shopee-decisions/types";
import { breachNoun, breachWarnLines } from "../../lib/shopee-decisions/versions";
import { DismissDialog } from "./dialogs";
import { BreachDialog } from "./versions";
import { NavLink, StatusChip, errorText } from "./ui";

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

function ProductCard({ entry, justUp, canAct, onSkip, onPlan }: { readonly entry: TopEntry; readonly justUp: string | null; readonly canAct: boolean; readonly onSkip: (e: TopEntry) => void; readonly onPlan: (e: TopEntry) => void }) {
  const host = useReco();
  const c = entry.top;
  const left = measuringDaysLeft(c.product_measuring ?? null, host.now?.() ?? new Date());
  const q = c.predicted_summary.dprofit_month;
  const tone = rangeTone(q.p10, q.p90);
  const nVersions = c.versions?.length ?? 1;
  const code = c.code ?? c.id;
  return (
    <article className="sq-card" data-testid={`sq-card-${c.id}`}>
      <div className="sq-card__head">
        <span className="sd-code">{code}</span>
        {c.product_id ? <span className="sa-chip sa-chip--outline">SP · {c.product_id}</span> : null}
        <h2 className="sq-card__title">
          <NavLink href={host.href({ the: c.id, from: "quyet-dinh" })}>{c.title}</NavLink>
        </h2>
        {justUp ? <TextChip tone="pink">{justUp}</TextChip> : null}
        {c.origin === "manual" ? <TextChip tone="info">Thủ công</TextChip> : null}
        <StatusChip status={c.status} />
        {c.stale ? <TextChip tone="warn">Đang cập nhật</TextChip> : null}
        {!c.floor_ok ? <TextChip tone="down">Chạm giá sàn</TextChip> : null}
      </div>
      <div className="sq-card__sum">
        <span>
          {c.family_label} · {nVersions} phiên bản
        </span>
        <b className={tone === "up" ? "sa-tone--up" : tone === "down" ? "sa-tone--down" : ""}>Δ lợi nhuận V1 {firstVersionRange(c)}</b>
      </div>
      {left > 0 ? (
        <div className="sd-measuring" data-testid="sq-measuring" role="status">
          <b>Sản phẩm đang đo: còn {left} ngày</b>
          <span>{measuringNote(c.product_measuring ?? null)}</span>
        </div>
      ) : null}
      <div className="sd-next" data-testid="sq-next">
        <b>Tiếp theo cho sản phẩm này:</b>
        {entry.next ? (
          <>
            <span className="sd-code">{entry.next.code ?? entry.next.id}</span>
            <span>
              {entry.next.family_label} · {entry.next.title}
            </span>
          </>
        ) : (
          <span>Không còn thẻ xếp hàng.</span>
        )}
        <span className="sd-next__q" data-testid="sq-queue">
          #1 · còn {fmt(entry.behind, 0)} thẻ xếp hàng
        </span>
      </div>
      <div className="sd-actions">
        <NavLink className="sa-btn sa-btn--primary" href={host.href({ the: c.id, from: "quyet-dinh" })}>
          Mở thẻ để chọn phiên bản
        </NavLink>
        {host.plan ? (
          <button className="sa-btn" data-testid="sq-plan" disabled={!canAct} onClick={() => onPlan(entry)} type="button">
            Thêm vào kế hoạch
          </button>
        ) : null}
        <button className="sa-btn" disabled={!canAct} onClick={() => onSkip(entry)} type="button">
          Bỏ qua
        </button>
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

export function TopCards({ cards, flash, onFlash, onChanged }: { readonly cards: readonly CardSummary[]; readonly flash: Flash; readonly onFlash: (f: Flash) => void; readonly onChanged: () => void }) {
  const host = useReco();
  const entries = topEntries(cards);
  const [skip, setSkip] = useState<TopEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const justUp = flash.justUp;
  const [planning, setPlanning] = useState<{ readonly entry: TopEntry; readonly breaches: readonly Breach[] } | null>(null);
  const addToPlan = async (entry: TopEntry, acknowledge: boolean) => {
    const plan = host.plan;
    if (!plan) return;
    setBusy(true);
    try {
      await plan.api.add(entry.top.id, 1, acknowledge);
      const gone = entry.top.code ?? entry.top.id;
      const nx = entry.next;
      onFlash({
        notice: { text: `Đã thêm ${gone}-V1 vào kế hoạch (chưa thực hiện). ${nx ? `${nx.code ?? nx.id} đã lên Quyết định.` : ""}`.trim(), tone: "ok", planLink: true },
        justUp: nx ? { ...justUp, [nx.id]: `Vừa lên thay thẻ ${gone} (đã vào kế hoạch)` } : justUp,
      });
      setPlanning(null);
      onChanged();
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code.startsWith("reco_breach") && Array.isArray(e.detail?.["breaches"])) setPlanning({ entry, breaches: e.detail["breaches"] as Breach[] });
      else onFlash({ notice: { text: errorText(e), tone: "plain" }, justUp });
    } finally {
      setBusy(false);
    }
  };
  const canAct = !host.readOnly && !host.staff;
  const dismiss = async (choice: { readonly reasonCode: string | null; readonly note: string | null }) => {
    if (!skip) return;
    setBusy(true);
    setError(null);
    try {
      await host.reco.dismiss(skip.top.id, choice);
      const gone = skip.top.code ?? skip.top.id;
      const nx = skip.next;
      onFlash({
        notice: { text: `Đã bỏ qua ${gone}. ${nx ? `${nx.code ?? nx.id} đã lên Quyết định thay thế.` : "Không còn thẻ cho sản phẩm này."}`, tone: "plain" },
        justUp: nx ? { ...justUp, [nx.id]: `Vừa lên thay thẻ ${gone} (đã bỏ qua)` } : justUp,
      });
      setSkip(null);
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {entries.map((e) => (
        <ProductCard canAct={canAct} entry={e} justUp={justUp[e.top.id] ?? null} key={e.top.id} onPlan={(x) => void addToPlan(x, false)} onSkip={setSkip} />
      ))}
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể tiếp tục. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ này."
        goLabel="Vẫn tiếp tục"
        lines={planning ? breachWarnLines(planning.breaches) : []}
        onBack={() => setPlanning(null)}
        onGo={() => planning && void addToPlan(planning.entry, true)}
        open={planning !== null}
        title={planning ? `Thêm ${planning.entry.top.code ?? planning.entry.top.id} vào kế hoạch dù ${breachNoun(planning.breaches)}?` : ""}
      />
      <DismissDialog busy={busy} error={error} onCancel={() => setSkip(null)} onSubmit={(c) => void dismiss(c)} open={skip !== null} />
    </>
  );
}
