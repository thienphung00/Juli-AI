"use client";

import { useId, useMemo, useState } from "react";

import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import { vnd } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { aggRows, cardBreaches, confirmWarnings, cutText, hasBreach, isHard, isStacked, kolRows, kolSummary, mdeText, planProducts, productMde, productName, stackBreaches, stackWarning, tradeoffText, windowText, withoutText } from "../../lib/shopee-decisions/plan-model";
import type { PlanApi, PlanResponse, WindowProductRow } from "../../lib/shopee-decisions/plan-types";
import type { Breach, CardList } from "../../lib/shopee-decisions/types";
import { ackText, breachNoun, breachWarnLines, firstVersionRange, svk } from "../../lib/shopee-decisions/versions";
import { useNarrow } from "../quyet-dinh/use-narrow";
import { Notice, PageHead, TextChip } from "../shopee-analytics/ui";
import { topEntries } from "./top-cards";
import { NavLink, RecoState, errorText } from "./ui";
import { BreachDialog } from "./versions";

/**
 * Kế hoạch (`KeHoach.dc.html`, mobile `KeHoachMobile.dc.html`): "Thêm vào kế hoạch" executes nothing
 * and sends nothing to the team; the plan shows the whole package (cards of one product are evaluated
 * together on the same orders), the measurement window per product (D-8), and only "Xác nhận kế hoạch"
 * approves it in one go. A floor or spend-cap breach never blocks: the dialog warns, "Vẫn tiếp tục" is
 * recorded. The numbers come from the plan API (`plan-types.ts` mirrors the backend answer).
 */

const BREACH_CODES = new Set(["reco_breach_not_acknowledged"]);
const toneClass = (t: string): string => (t === "up" ? "sa-tone--up" : t === "down" ? "sa-tone--down" : "");

export function PlanView() {
  const host = useReco();
  const api = host.plan?.api;
  if (!api) {
    return (
      <div className="sa-page" data-testid="kh-off">
        <Notice tone="info">Kế hoạch chưa bật cho shop này.</Notice>
      </div>
    );
  }
  return <PlanScreen api={api} />;
}

type Dialog = null | { readonly kind: "confirm" } | { readonly kind: "add"; readonly cardId: string; readonly code: string; readonly breaches: readonly Breach[] };

function PlanScreen({ api }: { readonly api: PlanApi }) {
  const host = useReco();
  const narrow = useNarrow();
  const [tick, setTick] = useState(0);
  const [override, setOverride] = useState<PlanResponse | null>(null);
  const loaded = useResource<PlanResponse>(() => api.get(), `${host.shopKey}|plan|${tick}`);
  const cards = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|plan-cands|${tick}`);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<string | null>(null);
  const [doneOnce, setDoneOnce] = useState(false);
  const plan = override ?? (loaded.status === "ready" ? loaded.data : null);

  const act = async (call: () => Promise<PlanResponse>, after?: (p: PlanResponse) => void) => {
    setBusy(true);
    setError(null);
    try {
      const p = await call();
      setOverride(p);
      after?.(p);
      setTick((t) => t + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sa-page kh" data-testid="kh-page">
      <PageHead eyebrow="QUYẾT ĐỊNH · KẾ HOẠCH" title="Kế hoạch: xem cả gói thay đổi trước khi làm" />
      <p className="sa-hint">“Thêm vào kế hoạch” chưa thực hiện gì và chưa gửi gì cho đội Juli. Chỉ “Xác nhận kế hoạch” mới duyệt cả gói một lần.</p>
      <NavLink className="sa-link" href={host.href({})}>
        ‹ Quyết định
      </NavLink>
      <RecoState resource={loaded.status === "ready" || override ? { status: "ready", data: plan! } : loaded}>
        {(p) => (
          <div className="kh-grid">
            {narrow ? null : (
              <Candidates
                busy={busy}
                cards={cards.status === "ready" ? cards.data : null}
                inPlan={new Set(p.cards.map((c) => c.card_id))}
                locked={(p.plan?.status ?? "draft") !== "draft"}
                onAdd={(id, code) =>
                  void (async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      const next = await api.add(id, 1, false);
                      setOverride(next);
                      setTick((t) => t + 1);
                    } catch (e) {
                      if (e instanceof ShopeeApiError && BREACH_CODES.has(e.code) && Array.isArray(e.detail?.["breaches"])) setDialog({ kind: "add", cardId: id, code, breaches: e.detail["breaches"] as Breach[] });
                      else setError(errorText(e));
                    } finally {
                      setBusy(false);
                    }
                  })()
                }
              />
            )}
            <DraftPlan
              ack={ack}
              api={api}
              busy={busy}
              error={error}
              narrow={narrow}
              onAct={act}
              onConfirm={() => setDialog({ kind: "confirm" })}
              plan={p}
            />
          </div>
        )}
      </RecoState>
      {plan ? (
        <ConfirmDialog
          busy={busy}
          dialog={dialog}
          onBack={() => setDialog(null)}
          onGo={() => {
            if (!dialog) return;
            if (dialog.kind === "add") {
              void act(() => api.add(dialog.cardId, 1, true), () => {
                setAck(ackText(dialog.breaches, new Date().toISOString()));
                setDialog(null);
              });
              return;
            }
            const warned = confirmWarnings(plan);
            void act(() => api.confirm({ acknowledgeBreaches: warned.length > 0 }), (p) => {
              if (warned.length > 0) setAck(ackText(p.plan?.acknowledged_breaches?.breaches ?? plan.aggregate?.breaches ?? [{ type: "floor" }], p.plan?.acknowledged_breaches?.at ?? new Date().toISOString()));
              setDoneOnce(true);
              setDialog(null);
            });
          }}
          plan={plan}
          sheet={narrow}
        />
      ) : null}
      {doneOnce && (plan?.plan?.status ?? "draft") !== "draft" ? <span hidden data-testid="kh-done-flag" /> : null}
    </div>
  );
}

function Candidates({ cards, inPlan, locked, busy, onAdd }: { readonly cards: CardList | null; readonly inPlan: ReadonlySet<string>; readonly locked: boolean; readonly busy: boolean; readonly onAdd: (id: string, code: string) => void }) {
  const entries = cards ? topEntries(cards.cards).map((e) => e.top) : [];
  const all = entries.every((c) => inPlan.has(c.id));
  return (
    <section className="sa-card kh-cands" data-testid="kh-cands">
      <h2 className="sa-h2">Thẻ đang chờ trong Quyết định</h2>
      <p className="sa-hint">Mỗi sản phẩm một thẻ. Thêm một thẻ vào kế hoạch thì thẻ kế tiếp của sản phẩm đó lên Quyết định ngay.</p>
      {entries.map((c) => {
        const ip = inPlan.has(c.id);
        return (
          <div className={`kh-cand ${ip ? "kh-cand--in" : ""}`} data-testid={`kh-cand-${c.id}`} key={c.id}>
            <div>
              <span className="sd-code">{c.code ?? c.id}</span> <span>{c.family_label}</span>
            </div>
            <span className="sa-hint">
              {c.versions?.length ?? 1} phiên bản{c.versions?.[0]?.label ? ` · V1 ${c.versions[0].label}` : ""}
            </span>
            <div className="kh-cand__act">
              <b>{firstVersionRange(c)}</b>
              <button className="sa-btn sa-btn--s" disabled={ip || locked || busy} onClick={() => onAdd(c.id, c.code ?? c.id)} type="button">
                {ip ? "Đã trong kế hoạch" : "Thêm vào kế hoạch"}
              </button>
            </div>
          </div>
        );
      })}
      {entries.length === 0 || all ? <p className="sa-hint">Mọi thẻ chờ đã nằm trong kế hoạch.</p> : null}
    </section>
  );
}

function DraftPlan({ plan, api, narrow, busy, error, ack, onAct, onConfirm }: { readonly plan: PlanResponse; readonly api: PlanApi; readonly narrow: boolean; readonly busy: boolean; readonly error: string | null; readonly ack: string | null; readonly onAct: (call: () => Promise<PlanResponse>) => Promise<void>; readonly onConfirm: () => void }) {
  const head = plan.plan;
  const done = (head?.status ?? "draft") !== "draft";
  const products = planProducts(plan);
  const warns = stackBreaches(plan).map((b) => stackWarning(plan, b));
  const rows = aggRows(plan);
  const trade = tradeoffText(plan);
  const breaching = hasBreach(plan);
  const cost = plan.aggregate?.cost;
  const shownAck = ack ?? (head?.acknowledged_breaches?.breaches?.length ? ackText(head.acknowledged_breaches.breaches, head.acknowledged_breaches.at) : null);
  const kol = kolSummary(plan);
  const winLabel = windowText(plan);
  return (
    <section className="sa-card kh-plan" data-testid="kh-plan">
      <div className="kh-plan__head">
        <h2 className="sa-h2">Kế hoạch nháp</h2>
        <TextChip tone={done ? "info" : "flat"}>{done ? "Đã xác nhận" : "Chưa thực hiện"}</TextChip>
        <span className="sa-hint" data-testid="kh-count">
          {plan.cards.length} thẻ · {products.length} sản phẩm
        </span>
        <span className="sd-code" data-testid="kh-code">
          {head?.code ?? "Mã kế hoạch cấp khi xác nhận"}
        </span>
        {shownAck ? (
          <b className="sd-ack" data-testid="kh-ack">
            {shownAck}
          </b>
        ) : null}
      </div>

      {done ? (
        <Notice tone="info" testId="kh-done">
          <b>Đã xác nhận kế hoạch {head?.code}.</b> {plan.cards.length} thẻ chuyển sang “Đã duyệt”, đội Juli thực hiện cùng một ngày{head?.planned_date ? ` (dự kiến ${head.planned_date.slice(8, 10)}/${head.planned_date.slice(5, 7)}/${head.planned_date.slice(0, 4)})` : ""}. {narrow ? "" : "Các phiên bản không chọn đóng cùng thẻ. "}Phép đo theo cửa sổ {winLabel} bắt đầu từ ngày thực hiện.
        </Notice>
      ) : null}

      <div className="kh-rows">
        {plan.cards.map((r) => (
          <div className={`kh-row ${isStacked(plan, r) ? "kh-row--bad" : ""}`} data-testid={`kh-row-${r.card_id}`} key={r.card_id}>
            <div className="kh-row__main">
              <div className="kh-row__top">
                <span className="sd-code">{r.chosen_version_code ?? `${r.code}-V${r.chosen_version}`}</span>
                {done && (r.plan_code ?? head?.code) ? <span className="sd-code">{r.plan_code ?? head?.code}</span> : null}
                <b>
                  {r.title ?? r.change_kind} · {productName(plan, r.product_id)}
                </b>
                <span className="sa-hint">{r.versions.find((v) => v.version === r.chosen_version)?.label}</span>
                {isStacked(plan, r) || cardBreaches(plan, r) ? <TextChip tone="down">{cardBreaches(plan, r) ? "Chạm giá sàn" : "Chạm giá sàn khi xếp chồng"}</TextChip> : null}
              </div>
              <div className="kh-row__vers">
                <span className="sa-hint">Phiên bản:</span>
                {r.versions.map((v) => (
                  <button
                    aria-pressed={v.version === r.chosen_version}
                    className={`sb-pill ${v.version === r.chosen_version ? "sb-pill--on" : ""}`}
                    disabled={done || busy || v.status === "refused"}
                    key={v.version}
                    onClick={() => void onAct(() => api.setVersion(r.card_id, v.version))}
                    type="button"
                  >
                    V{v.version}
                  </button>
                ))}
              </div>
              <div className="kh-row__why">
                Đóng góp:{" "}
                <b className={(r.evaluation?.contribution.dprofit_p50 ?? 0) >= 0 ? "sa-tone--up" : "sa-tone--down"}>{svk(r.evaluation?.contribution.dprofit_p50)}/tháng (giữa khoảng)</b> · Bỏ thẻ này thì: {withoutText(r)}
              </div>
            </div>
            <button className="sa-btn sa-btn--s" disabled={done || busy} onClick={() => void onAct(() => api.remove(r.card_id))} type="button">
              Bỏ khỏi kế hoạch
            </button>
          </div>
        ))}
        {plan.cards.length === 0 ? <p className="sa-hint" data-testid="kh-empty">Kế hoạch trống. Thêm thẻ từ danh sách bên trái hoặc từ thẻ trong Quyết định.</p> : null}
      </div>

      {warns.map((w, i) => (
        <div className="sd-check sd-check--bad kh-warn" key={i} role="alert">
          <span>
            <b>{w.title}</b> <span className="sd-check__line">{w.body}</span>
            <span className="sd-check__line">{w.fix}</span>
          </span>
        </div>
      ))}
      {trade ? (
        <div className="sb-trade" data-testid="kh-trade">
          <b>Đánh đổi:</b> {trade}
        </div>
      ) : null}

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
          <h3>{narrow ? "Cả kế hoạch: hôm nay → sau" : "Cả kế hoạch: hôm nay → sau kế hoạch"}</h3>
          <p className="sa-hint">Phạm vi: {products.map((id) => productName(plan, id)).join(" và ")} (30 ngày). Các thẻ cùng sản phẩm được tính chung trên cùng các đơn, không cộng rời.</p>
          <div className="kh-agg__table">
            {narrow ? null : (
              <div className="kh-agg__row kh-agg__row--head">
                <span>Chỉ số</span>
                <span>Hôm nay</span>
                <span>Sau kế hoạch (dự kiến)</span>
              </div>
            )}
            {rows.map((r) => (
              <div className={`kh-agg__row ${r.bad ? "kh-agg__row--bad" : ""}`} data-testid={`kh-agg-${r.key}`} key={r.key}>
                <span>{r.label}</span>
                <span className="sd-muted">{narrow ? `${r.today} →` : r.today}</span>
                <span>
                  <b className={r.key === "sure" || r.key === "exp" ? toneClass(r.tone) : ""}>{r.after}</b>
                  {r.d ? <span className={`sv-cell__d sv-cell__d--${r.tone === "plain" ? "flat" : r.tone}`}>{r.d}</span> : null}
                </span>
              </div>
            ))}
          </div>
          {cost && cost.cap_per_day ? (
            <div className="kh-cap" data-testid="kh-cap">
              <span>Chi phí toàn shop mỗi ngày so với trần {vnd(cost.cap_per_day)}</span>
              <span className="kh-cap__bar">
                <span className={cost.over_cap ? "kh-cap__fill kh-cap__fill--over" : "kh-cap__fill"} style={{ width: `${Math.min(100, Math.round((cost.per_day_after / cost.cap_per_day) * 100))}%` }} />
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
        <button className="sa-btn sa-btn--primary" data-testid="kh-confirm" disabled={plan.cards.length === 0 || done || busy} onClick={onConfirm} type="button">
          Xác nhận kế hoạch
        </button>
        {done ? null : (
          <span className={`sa-hint ${breaching ? "sd-hint--warn" : ""}`} data-testid="kh-hint">
            {plan.aggregate?.floor?.ok === false ? "Có thẻ chạm giá sàn: vẫn xác nhận được, Juli hiện cảnh báo trước." : plan.aggregate?.cost?.over_cap ? "Chi phí vượt trần chi mỗi ngày: vẫn xác nhận được, Juli hiện cảnh báo trước." : "Bấm để xem phép đo nào sẽ bị cắt trước khi xác nhận."}
          </span>
        )}
      </div>
    </section>
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
        <span className="sa-hint">Mặc định là tự động theo sản phẩm (cửa sổ ngắn nhất thấy được thay đổi ≥ 30% với lượng đơn của sản phẩm đó). Bạn đổi được, tối thiểu {w.min_days} ngày.</span>
      </div>
      <div className="kh-win__opts" role="radiogroup" aria-label="Cửa sổ đo">
        <button aria-checked={auto} className={`kh-opt ${auto ? "kh-opt--on" : ""}`} disabled={busy} onClick={() => setDays(null)} role="radio" type="button">
          <span>
            <b>Tự động theo sản phẩm</b> <TextChip tone="pink">Đề xuất</TextChip>
          </span>
          <span className="sa-hint">mỗi sản phẩm một cửa sổ ngắn nhất thấy được thay đổi ≥ 30%</span>
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
            <b>Khó kết luận.</b> Có nhóm đặt cửa sổ ngắn hơn mức đề xuất cho sản phẩm đó. Vẫn được chọn, nhưng nhiều khả năng kết quả sẽ không đủ để kết luận.
          </span>
        </div>
      ) : null}
      <p className="sa-hint">Với cửa sổ dài hơn 7 ngày, Juli vẫn đưa kết quả sơ bộ ở ngày 7.</p>
      <div className="kh-sets">
        <span className="sd-field__label">Riêng từng nhóm thay đổi (cùng sản phẩm, cùng ngày thực hiện)</span>
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
  const warned = useMemo(() => (dialog?.kind === "confirm" ? confirmWarnings(plan) : dialog?.kind === "add" ? breachWarnLines(dialog.breaches) : []), [dialog, plan]);
  if (!dialog) return null;
  if (dialog.kind === "add") {
    return (
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể tiếp tục. Juli ghi lại xác nhận kèm giờ."
        goLabel="Vẫn tiếp tục"
        lines={warned}
        onBack={onBack}
        onGo={onGo}
        open
        sheet={sheet}
        title={`Thêm ${dialog.code} vào kế hoạch dù ${breachNoun(dialog.breaches)}?`}
      />
    );
  }
  const blocked = warned.length > 0;
  const cutsHere = (plan.plan?.measurement_cut ?? []).filter((c) => planProducts(plan).includes(c.product_id));
  return (
    <div className={`qv-overlay ${sheet ? "sv-overlay--sheet" : ""}`} data-testid="kh-dialog">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className={`qv-dialog ${sheet ? "sv-warn--sheet" : ""}`} role="dialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          {blocked ? "Xác nhận kế hoạch dù có cảnh báo?" : `Xác nhận kế hoạch ${plan.cards.length} thẻ?`}
        </h3>
        <p className="qv-dialog__body">
          Các thẻ chuyển sang “Đã duyệt” và đội Juli thực hiện cùng một ngày. Mã kế hoạch cấp khi xác nhận. Cửa sổ đo: {windowText(plan)}.
        </p>
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
            {blocked ? "Vẫn tiếp tục" : "Xác nhận kế hoạch"}
          </button>
        </div>
      </div>
    </div>
  );
}

