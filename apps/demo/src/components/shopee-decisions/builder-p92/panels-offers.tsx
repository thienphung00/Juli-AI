"use client";

import { useEffect, useState } from "react";

import { MarketPriceMarker } from "../../shopee-analytics/market-price-marker";
import { fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { CoPurchase } from "../../../lib/shopee-decisions/builder-api";
import { DEAL_SOC_TYPES, MAX_ADDONS, belowPaidHint, belowPaidProblem, MAX_COMBO_NAME, MAX_COMBO_TIERS, MAX_PROGRAMME_NAME, MAX_TITLE, kmoney, marginText, newTier, num, voucherChips, type AddonRow, type ComboTierRow, type Forms, type GiftForm, type NewVariation } from "../../../lib/shopee-decisions/builder-p92";
import { NumIn, Pills, ProductSelect, Seg, TextIn, VariationSelect, setAt, type PanelCtx } from "./shared";
import { ProductTargets } from "./targets";

/**
 * Input panels of the offer strategies (artboard `TuTaoPhuongAnKinds`): Voucher, Combo nhiều sản phẩm, Deal Sốc,
 * Chương Trình Của Shop, Giá bán + Flash sale, Phân loại / set. Typed numbers only (no sliders). The figures the
 * server computed for the version (`details`) are shown next to the inputs.
 */

type P<K extends keyof Forms> = { readonly form: Forms[K]; readonly set: (patch: Partial<Forms[K]>) => void; readonly ctx: PanelCtx };

const dn = (o: Readonly<Record<string, unknown>> | undefined, k: string): number | null => (typeof o?.[k] === "number" ? (o[k] as number) : null);
const details = (ctx: PanelCtx): Readonly<Record<string, unknown>> => ctx.outcome?.details ?? {};

function Calc({ rows, testId }: { readonly rows: readonly (readonly [string, string])[]; readonly testId: string }) {
  return (
    <dl className="p2-calc" data-testid={testId}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── Voucher ──────────────────────────────────────────────────────────────

const SCOPES = [
  ["shop", "Voucher shop (cả shop)"],
  ["product", "Voucher sản phẩm"],
  ["follower", "Người theo dõi / khách mới"],
  ["livestream", "Livestream / video"],
] as const;

export function VoucherPanel({ form, set, ctx }: P<"voucher">) {
  const d = details(ctx);
  const q = dn(d, "qualifying_orders");
  const t = dn(d, "total_orders");
  const chips = voucherChips(ctx.aov);
  return (
    <div className="p2-panel" data-testid="p2-panel-voucher">
      <Pills label="Loại voucher" onChange={(scope) => set({ scope })} options={SCOPES} value={form.scope} />
      {form.scope === "product" ? (
        <label className="p2-check" data-testid="p2-voucher-many">
          <input checked={form.items.length > 0} onChange={(e) => set({ items: e.target.checked ? [ctx.product.item_id] : [] })} type="checkbox" /> Áp cho nhiều sản phẩm (danh sách sản phẩm của voucher)
        </label>
      ) : null}
      {form.scope === "product" && form.items.length > 0 ? (
        <ProductTargets ctx={ctx} onChange={(items) => set({ items })} selected={form.items} title="Sản phẩm của voucher" />
      ) : null}
      <Seg label="Cách giảm" onChange={(dtype) => set({ dtype })} options={[["amount", "Số tiền (đ)"], ["pct", "Phần trăm (%)"]]} value={form.dtype} />
      <div className="p2-grid">
        <NumIn label="Giá trị" onChange={(value) => set({ value })} suffix={form.dtype === "pct" ? "%" : "đ"} value={form.value} />
        <NumIn label="Đơn tối thiểu" onChange={(min) => set({ min })} suffix="đ" value={form.min} />
        {form.dtype === "pct" ? <NumIn label="Giảm tối đa (khi giảm %)" onChange={(max) => set({ max })} suffix="đ" value={form.max} /> : null}
        <NumIn label="Số lượt dùng tối đa" onChange={(usage) => set({ usage })} value={form.usage} />
        <NumIn label="Giới hạn mỗi người" onChange={(perBuyer) => set({ perBuyer })} value={form.perBuyer} />
        <TextIn label="Bắt đầu" onChange={(start) => set({ start })} type="date" value={form.start} />
        <TextIn label="Kết thúc" onChange={(end) => set({ end })} type="date" value={form.end} />
      </div>
      <div className="p2-field">
        <span className="sd-field__label">Gợi ý từ AOV của shop{ctx.aov ? ` (${vnd(ctx.aov)})` : ""}</span>
        <div className="sb-chips">
          {chips.map((c) => (
            <button className="sb-pill" key={c.label} onClick={() => set({ dtype: "amount", value: String(c.value), min: String(c.min) })} type="button">
              {c.label}
            </button>
          ))}
        </div>
      </div>
      {q !== null && t ? (
        <p className="sa-hint" data-testid="p2-voucher-qualify">
          Đơn đủ điều kiện (30 ngày): {fmt(q)} / {fmt(t)} ({fmt((q / t) * 100, 0)}%)
          {dn(d, "voucher_cost_scenario") !== null ? ` · Chi phí voucher: ${vnd(dn(d, "voucher_cost_scenario"))}` : ""}
        </p>
      ) : null}
    </div>
  );
}

// ── Combo khuyến mãi ─────────────────────────────────────────────────────

const COMBO_TYPE_OPTIONS = [
  ["pct", "Giảm giá theo %"],
  ["amount", "Giảm giá theo số tiền"],
  ["special_price", "Giảm giá đặc biệt"],
] as const;

type TierDetail = { readonly units: number; readonly text: string; readonly discount_pct: number | null; readonly margin_pct: number | null; readonly below_floor: boolean };

/**
 * Combo Khuyến Mãi in Shopee's own form (recon 2026-11-09, P97 D85.15): the product list without quantity or
 * variation per item, Loại Combo, "Thêm mức ưu đãi" rows "Mua [N] sản phẩm → …", Giới hạn đặt hàng, Tên (≤ 25)
 * and the dates. The inline voucher and the gift are their own strategies.
 */
export function ComboPanel({ form, set, ctx }: P<"combo">) {
  const [co, setCo] = useState<CoPurchase | null>(null);
  useEffect(() => {
    let live = true;
    ctx.api.coPurchase(ctx.product.item_id).then(
      (r) => live && setCo(r),
      () => live && setCo(null),
    );
    return () => {
      live = false;
    };
    // One lookup per product.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.product.item_id]);
  const d = details(ctx);
  const tiers = form.tiers;
  const rows = (Array.isArray(d["tiers"]) ? d["tiers"] : []) as TierDetail[];
  const unit = form.dtype === "pct" ? "%" : "đ";
  const valueLabel = form.dtype === "special_price" ? "Chỉ với giá" : "Giảm";
  const valueSuffix = form.dtype === "pct" ? "%GIẢM" : unit;
  const updTier = (i: number, patch: Partial<ComboTierRow>) => set({ tiers: setAt(tiers, i, patch) });
  const addPartner = (partner: string) => set({ items: form.items.includes(partner) ? form.items : [...form.items, partner] });
  return (
    <div className="p2-panel" data-testid="p2-panel-combo">
      <TextIn hint={`${[...form.name].length}/${MAX_COMBO_NAME} ký tự`} label="Tên Combo Khuyến Mãi" onChange={(name) => set({ name })} value={form.name} />
      <ProductTargets ctx={ctx} onChange={(items) => set({ items })} selected={form.items} title="Sản phẩm của Combo" />
      <Pills label="Loại Combo" onChange={(dtype) => set({ dtype })} options={COMBO_TYPE_OPTIONS} value={form.dtype} />
      <div className="p2-rows" data-testid="p2-combo-tiers">
        {tiers.map((t, i) => (
          <div className="p2-row p2-row--wrap" data-testid={`p2-tier-${i + 1}`} key={i}>
            <span className="sb-item__n">{i + 1}</span>
            <span>Mua</span>
            <NumIn label={`Mức ${i + 1} · số sản phẩm`} onChange={(qty) => updTier(i, { qty })} value={t.qty} />
            <span>sản phẩm để được {valueLabel.toLowerCase()}</span>
            <NumIn label={`Mức ${i + 1} · ${valueLabel.toLowerCase()}`} onChange={(value) => updTier(i, { value })} suffix={valueSuffix} value={t.value} />
            {tiers.length > 1 ? (
              <button aria-label={`Bỏ mức ${i + 1}`} className="sa-btn sa-btn--s" onClick={() => set({ tiers: tiers.filter((_, k) => k !== i) })} type="button">
                ×
              </button>
            ) : null}
            {rows[i] ? (
              <span className="sa-hint" data-testid={`p2-tier-calc-${i + 1}`}>
                {rows[i]!.text}
                {rows[i]!.discount_pct !== null ? ` · giảm ${fmt(rows[i]!.discount_pct, 1)}% đơn giá` : ""} · biên {marginText(rows[i]!.margin_pct)}
                {rows[i]!.below_floor ? " · dưới giá sàn" : ""}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {tiers.length < MAX_COMBO_TIERS ? (
        <button className="sa-btn sa-btn--s" data-testid="p2-add-tier" onClick={() => set({ tiers: [...tiers, newTier(String(Math.max(2, ...tiers.map((t) => num(t.qty) ?? 0)) + 1), "")] })} type="button">
          + Thêm mức ưu đãi
        </button>
      ) : null}
      <div className="p2-grid">
        <NumIn label="Giới hạn đặt hàng" onChange={(limit) => set({ limit })} value={form.limit} />
      </div>
      <fieldset className="p2-grid" data-testid="p2-combo-time">
        <legend className="sa-hint">Thời gian chạy Combo</legend>
        <TextIn label="Bắt đầu" onChange={(start) => set({ start })} type="date" value={form.start} />
        <NumIn label="Giờ bắt đầu" onChange={(startHour) => set({ startHour })} value={form.startHour ?? ""} />
        <TextIn label="Kết thúc" onChange={(end) => set({ end })} type="date" value={form.end} />
        <NumIn label="Giờ kết thúc" onChange={(endHour) => set({ endHour })} value={form.endHour ?? ""} />
      </fieldset>
      {dn(d, "avg_unit_price") !== null ? (
        <Calc
          rows={[
            ["Đơn giá trung bình các sản phẩm", vnd(dn(d, "avg_unit_price"))],
            ["Đơn 30 ngày qua đã đủ điều kiện", `${fmt(dn(d, "qualifying_orders"))} / ${fmt(dn(d, "total_orders"))} đơn`],
            ["Giảm cho các đơn đó", vnd(dn(d, "extra_cost_on_existing_orders"))],
          ]}
          testId="p2-combo-calc"
        />
      ) : null}
      <div className="p2-suggest" data-testid="p2-copurchase">
        <b>Gợi ý ghép · Sản phẩm hay mua cùng {ctx.product.name} (90 ngày)</b>
        {co && co.suggestions.length > 0 ? (
          <ul>
            {co.suggestions.map((sg) => (
              <li key={sg.item_id}>
                <span>{sg.name}</span>
                <span>{fmt(sg.together)} lần</span>
                <button className="sa-btn sa-btn--s" onClick={() => addPartner(sg.item_id)} type="button">
                  Thêm vào combo ›
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sa-hint">—</p>
        )}
      </div>
    </div>
  );
}

// ── Deal Sốc ─────────────────────────────────────────────────────────────

type TimeForm = { readonly start: string; readonly end: string; readonly startHour: string; readonly endHour: string };

/** "Thời gian …" with hour precision (0–23, empty = the whole day), as Seller Centre's programme forms. */
function TimeWindow({ legend, testId, form, set }: { readonly legend: string; readonly testId: string; readonly form: TimeForm; readonly set: (patch: Partial<TimeForm>) => void }) {
  return (
    <fieldset className="p2-grid" data-testid={testId}>
      <legend className="sa-hint">{legend}</legend>
      <TextIn label="Bắt đầu" onChange={(start) => set({ start })} type="date" value={form.start} />
      <NumIn label="Giờ bắt đầu" onChange={(startHour) => set({ startHour })} value={form.startHour} />
      <TextIn label="Kết thúc" onChange={(end) => set({ end })} type="date" value={form.end} />
      <NumIn label="Giờ kết thúc" onChange={(endHour) => set({ endHour })} value={form.endHour} />
    </fieldset>
  );
}

/**
 * Deal Sốc in Shopee's one form (P100 wave 2, brief C): "Loại Deal Sốc" = Mua Kèm Deal Sốc | Mua Để Nhận Quà, then
 * Tên chương trình, Thời gian bắt đầu / kết thúc (at least 1 hour) and the type's own fields. The version keeps the
 * kinds `add_on` / `gift` the engine already prices (cost inside the result).
 */
export function DealSocPanel({ form, set, ctx }: P<"deal_soc">) {
  const gift = form.gift;
  const setGift = (patch: Partial<GiftForm>) => set({ gift: { ...gift, ...patch } });
  return (
    <div className="p2-panel" data-testid="p2-panel-dealsoc">
      <Pills label="Loại Deal Sốc" onChange={(type) => set({ type })} options={DEAL_SOC_TYPES} value={form.type} />
      <TextIn hint={`${[...form.name].length}/${MAX_PROGRAMME_NAME} ký tự`} label="Tên chương trình" onChange={(name) => set({ name })} value={form.name} />
      <TimeWindow form={form} legend="Thời gian bắt đầu / kết thúc" set={(patch) => set(patch)} testId="p2-dealsoc-time" />
      {form.type === "add_on" ? <AddOnFields ctx={ctx} form={form} set={set} /> : <GiftFields ctx={ctx} form={gift} set={setGift} />}
    </div>
  );
}

function AddOnFields({ form, set, ctx }: P<"deal_soc">) {
  const d = details(ctx);
  const lines = (Array.isArray(d["addons"]) ? d["addons"] : []) as Readonly<Record<string, unknown>>[];
  const rows = form.addons;
  const upd = (i: number, patch: Partial<AddonRow>) => set({ addons: setAt(rows, i, patch) });
  return (
    <div className="p2-panel" data-testid="p2-panel-addon">
      <p className="sa-hint">
        Sản Phẩm Chính: <b>{ctx.product.name}</b>
      </p>
      <NumIn label="Giới hạn sản phẩm mua kèm" onChange={(addonLimit) => set({ addonLimit })} value={form.addonLimit} />
      <div className="p2-rows">
        {rows.map((a, i) => (
          <div className="p2-row p2-row--wrap" data-testid={`p2-addon-${i + 1}`} key={i}>
            <span className="sb-item__n">{i + 1}</span>
            <ProductSelect label={`Sản phẩm mua kèm ${i + 1}`} onChange={(id) => upd(i, { itemId: id, variationId: "" })} products={ctx.products.filter((p) => p.item_id !== ctx.product.item_id)} value={a.itemId} />
            <VariationSelect api={ctx.api} itemId={a.itemId} label={`Phân loại mua kèm ${i + 1}`} onChange={(v) => upd(i, { variationId: v })} value={a.variationId} />
            <Seg label="Cách nhập giá mua kèm" onChange={(mode) => upd(i, { mode })} options={[["price", "Giá mua kèm (đ)"], ["pct", "% giảm"]]} value={a.mode} />
            <NumIn label={`Giá trị mua kèm ${i + 1}`} onChange={(value) => upd(i, { value })} suffix={a.mode === "pct" ? "%" : "đ"} value={a.value} />
            <NumIn label={`Giới hạn mỗi đơn ${i + 1}`} onChange={(limit) => upd(i, { limit })} value={a.limit} />
            {rows.length > 1 ? (
              <button aria-label={`Bỏ mua kèm ${i + 1}`} className="sa-btn sa-btn--s" onClick={() => set({ addons: rows.filter((_, k) => k !== i) })} type="button">
                ×
              </button>
            ) : null}
            {lines[i] ? (
              <span className="sa-hint" data-testid={`p2-addon-margin-${i + 1}`}>
                {vnd(dn(lines[i], "price_before"))} → {vnd(dn(lines[i], "price_after"))} · biên {marginText(dn(lines[i], "margin_pct"))}
                {lines[i]!["below_floor"] === true ? " · dưới giá sàn" : ""}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {rows.length < MAX_ADDONS ? (
        <button className="sa-btn sa-btn--s" onClick={() => set({ addons: [...rows, { itemId: "", variationId: "", mode: "pct", value: "15", limit: "1" }] })} type="button">
          + Thêm Sản Phẩm Mua Kèm
        </button>
      ) : null}
      {lines.length > 0 ? (
        <Calc
          rows={lines.flatMap((l, i): [string, string][] => [
            [`Tỉ lệ mua kèm hôm nay · ${i + 1}`, pp(typeof l["attach_rate_now"] === "number" ? (l["attach_rate_now"] as number) * 100 : null, 1)],
            [`Tỉ lệ mua kèm hoà vốn · ${i + 1}`, pp(typeof l["attach_rate_break_even"] === "number" ? (l["attach_rate_break_even"] as number) * 100 : null, 1)],
            [`Giảm cho khách đã mua cùng sẵn · ${i + 1}`, vnd(dn(l, "discount_cost_on_existing"))],
          ])}
          testId="p2-addon-calc"
        />
      ) : null}
    </div>
  );
}

function GiftFields({ form, set, ctx }: { readonly form: GiftForm; readonly set: (patch: Partial<GiftForm>) => void; readonly ctx: PanelCtx }) {
  const g = (ctx.outcome?.details?.["gift"] ?? {}) as Readonly<Record<string, unknown>>;
  return (
    <div className="p2-panel" data-testid="p2-panel-gift">
      <p className="sa-hint">
        Sản Phẩm Chính: <b>{ctx.product.name}</b>
      </p>
      <fieldset className="p2-grid" data-testid="p2-gift-condition">
        <legend className="sa-hint">Điều kiện nhận quà</legend>
        <NumIn label="Mua" onChange={(minSpend) => set({ minSpend })} suffix="₫" value={form.minSpend} />
        <NumIn label="Để nhận (quà tặng)" onChange={(qty) => set({ qty })} value={form.qty} />
      </fieldset>
      <Seg label="Quà tặng là" onChange={(source) => set({ source })} options={[["listing", "Sản phẩm trong danh sách"], ["unsold", "Quà không bán"]]} value={form.source} />
      {form.source === "listing" ? (
        <div className="p2-field">
          <span className="sd-field__label">Sản phẩm làm quà</span>
          <ProductSelect label="Sản phẩm làm quà" onChange={(giftItemId) => set({ giftItemId })} products={ctx.products} value={form.giftItemId} />
        </div>
      ) : (
        <div className="p2-grid">
          <TextIn label="Quà không bán · tên" onChange={(label) => set({ label })} value={form.label} />
          <NumIn label="Chi phí mỗi quà" onChange={(unitCost) => set({ unitCost })} suffix="đ" value={form.unitCost} />
        </div>
      )}
      <div className="p2-grid">
        <NumIn label="Đóng gói mỗi quà" onChange={(packaging) => set({ packaging })} suffix="đ" value={form.packaging} />
      </div>
      {dn(g, "cost_per_gift") !== null ? (
        <Calc
          rows={[
            ["Chi phí mỗi quà = giá vốn + đóng gói", vnd(dn(g, "cost_per_gift"))],
            ["Đơn nhận quà", `${fmt(dn(g, "qualifying_orders"))} đơn`],
            ["Chi phí quà trong kỳ", vnd(dn(g, "gift_cost_window"))],
            ["Tồn kho quà", dn(g, "stock") === null ? "Quà không bán: không theo dõi tồn" : `${fmt(dn(g, "stock"))} · dùng ${fmt(dn(g, "units_used_in_window"))}`],
          ]}
          testId="p2-gift-calc"
        />
      ) : null}
    </div>
  );
}

// ── Giảm giá, Giá bán + Flash sale ───────────────────────────────────────

/** The price a buyer sees after the typed row: the final price, or the list price moved by the percentage. */
function draftPrice(selling: number | null, mode: "pct" | "final_price", raw: string, direction: "off" | "change"): number | null {
  const n = num(raw);
  if (n === null) return null;
  if (mode === "final_price") return n > 0 ? n : null;
  if (selling === null) return null;
  const price = direction === "off" ? selling * (1 - n / 100) : selling * (1 + n / 100);
  return price > 0 ? price : null;
}

/** "Giảm" only where the number is a decrease; a list-price change is ± (+ = price up). */
export function pctLabel(mode: "pct" | "final_price", direction: "off" | "change"): string {
  if (mode !== "pct") return "Giá mới";
  return direction === "change" ? "Thay đổi" : "Giảm";
}

function VarRows({ ctx, rows, mode, direction, onRow, labels, bounded }: { readonly bounded?: boolean; readonly labels?: { readonly pct: string; readonly final: string }; readonly ctx: PanelCtx; readonly direction: "off" | "change"; readonly rows: readonly { readonly variationId: string; readonly value: string }[]; readonly mode: "pct" | "final_price"; readonly onRow: (id: string, value: string) => void }) {
  const skus = (Array.isArray(ctx.outcome?.details?.["skus"]) ? ctx.outcome!.details!["skus"] : []) as Readonly<Record<string, unknown>>[];
  return (
    <div className="p2-rows" data-testid="p2-varrows">
      {ctx.variations.map((v, i) => {
        const val = rows.find((r) => r.variationId === v.variation_id)?.value ?? "";
        const sku = skus[i];
        const bound = bounded ? belowPaidHint(v) : null;
        const under = bounded ? belowPaidProblem(v, mode, val) : null;
        return (
          <div className="p2-row p2-row--wrap" key={v.variation_id || "default"}>
            <span className="p2-row__name">
              <b>{v.name}</b>
              <span className="sa-hint">giá hiện tại {vnd(v.selling_price)}</span>
            </span>
            <NumIn label={`${labels ? (mode === "pct" ? labels.pct : labels.final) : pctLabel(mode, direction)} · ${v.name}`} onChange={(x) => onRow(v.variation_id, x)} suffix={mode === "pct" ? "%" : "đ"} value={val} />
            {bound && (mode === "pct" ? bound.min !== null : bound.paid !== null) ? (
              <span className="sa-hint" data-testid={`p2-min-${i + 1}`}>
                {mode === "pct" ? `Tối thiểu ${bound.min} % · đang bán ${vnd(bound.paid)}` : `Đang bán ${vnd(bound.paid)}`}
              </span>
            ) : null}
            {under ? (
              <span className="sd-error" data-testid={`p2-under-${i + 1}`} role="alert">
                {under}
              </span>
            ) : null}
            {sku ? (
              <span className="sa-hint" data-testid={`p2-sku-${i + 1}`}>
                {vnd(dn(sku, "price_before"))} → {vnd(dn(sku, "price_after"))} · biên {marginText(dn(sku, "margin_pct_before"))} → {marginText(dn(sku, "margin_pct_after"))}
              </span>
            ) : null}
            {ctx.market && val.trim() !== "" ? (
              <MarketPriceMarker draftPrice={draftPrice(v.selling_price, mode, val, direction)} itemId={ctx.product.item_id} scope={ctx.market} variationId={v.variation_id || undefined} />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function upsert(rows: readonly { variationId: string; value: string }[], id: string, value: string) {
  return rows.some((r) => r.variationId === id) ? rows.map((r) => (r.variationId === id ? { ...r, value } : r)) : [...rows, { variationId: id, value }];
}

/** Shopee's own labels of the programme's price columns: "Giá sau giảm" or "% GIẢM". */
const PROGRAMME_LABELS = { pct: "% GIẢM", final: "Giá sau giảm" } as const;

/**
 * Chương Trình Của Shop in Shopee's form (P100 wave 2, brief C): Tên chương trình khuyến mãi, Thời gian khuyến mãi (hours,
 * at most 180 days), per variation Giá sau giảm or % GIẢM, Số lượng sản phẩm khuyến mãi (empty = Không giới hạn) and
 * Giới hạn đặt hàng. A variation left empty is not in the programme (Shopee's Bật / Tắt).
 */
export function DiscountPanel({ form, set, ctx }: P<"product_discount">) {
  return (
    <div className="p2-panel" data-testid="p2-panel-discount">
      <TextIn hint={`${[...form.name].length}/${MAX_PROGRAMME_NAME} ký tự, người mua không thấy`} label="Tên chương trình khuyến mãi" onChange={(name) => set({ name })} value={form.name} />
      <Seg label="Áp dụng cho" onChange={(v) => set({ multi: v === "many", targets: v === "many" && form.targets.length === 0 ? [ctx.product.item_id] : form.targets })} options={[["one", "Sản phẩm đã chọn"], ["many", "Nhiều sản phẩm cùng một mức giảm"]]} value={form.multi ? "many" : "one"} />
      {form.multi ? (
        <>
          <NumIn label="% GIẢM cho tất cả" onChange={(pct) => set({ pct })} suffix="%" value={form.pct} />
          <ProductTargets ctx={ctx} onChange={(targets) => set({ targets })} selected={form.targets} title="Sản phẩm được giảm giá" />
        </>
      ) : (
        <>
          <Seg label="Nhập giảm theo" onChange={(mode) => set({ mode })} options={[["pct", "% GIẢM"], ["final_price", "Giá sau giảm (₫)"]]} value={form.mode} />
          <VarRows bounded ctx={ctx} direction="off" labels={PROGRAMME_LABELS} mode={form.mode} onRow={(id, v) => set({ rows: upsert(form.rows, id, v) })} rows={form.rows} />
        </>
      )}
      <TimeWindow form={form} legend="Thời gian khuyến mãi" set={(patch) => set(patch)} testId="p2-discount-time" />
      <div className="p2-grid">
        <NumIn label="Số lượng sản phẩm khuyến mãi" onChange={(promoQty) => set({ promoQty })} value={form.promoQty} />
        <NumIn label="Giới hạn đặt hàng" onChange={(perBuyer) => set({ perBuyer })} value={form.perBuyer} />
      </div>
    </div>
  );
}

export function PriceFlashPanel({ form, set, ctx }: P<"price_flash">) {
  return (
    <div className="p2-panel" data-testid="p2-panel-flash">
      <Pills label="Loại thay đổi" onChange={(what) => set({ what })} options={[["price", "Đổi giá niêm yết"], ["flash_sale", "Flash sale của shop"]]} value={form.what} />
      <Seg label={form.what === "price" ? "Nhập giá theo" : "Nhập giảm theo"} onChange={(mode) => set({ mode })} options={[["pct", form.what === "price" ? "Thay đổi (%)" : "Giảm (%)"], ["final_price", form.what === "price" ? "Giá bán mới (đ)" : "Giá flash sale (đ)"]]} value={form.mode} />
      <VarRows bounded={form.what === "flash_sale"} ctx={ctx} direction={form.what === "price" ? "change" : "off"} mode={form.mode} onRow={(id, v) => set({ rows: upsert(form.rows, id, v) })} rows={form.rows} />
      {form.what === "flash_sale" ? (
        <div className="p2-grid">
          <NumIn label="Số lượng (suất)" onChange={(units) => set({ units })} value={form.units} />
          <NumIn label="Số giờ của khung" onChange={(slotHours) => set({ slotHours })} value={form.slotHours} />
          <TextIn label="Khung giờ bắt đầu" onChange={(slotStart) => set({ slotStart })} type="datetime-local" value={form.slotStart} />
        </div>
      ) : null}
    </div>
  );
}

// ── Phân loại / set ──────────────────────────────────────────────────────

export function SetPanel({ form, set, ctx }: P<"variation_set">) {
  const out = (Array.isArray(ctx.outcome?.details?.["new_variations"]) ? ctx.outcome!.details!["new_variations"] : []) as Readonly<Record<string, unknown>>[];
  const rows = form.rows;
  const upd = (i: number, patch: Partial<NewVariation>) => set({ rows: setAt(rows, i, patch) });
  return (
    <div className="p2-panel" data-testid="p2-panel-set">
      <div className="p2-rows">
        {rows.map((r, i) => (
          <div className="p2-row p2-row--wrap" data-testid={`p2-set-${i + 1}`} key={i}>
            <TextIn label={`Tên phân loại ${i + 1}`} onChange={(name) => upd(i, { name })} placeholder="Set 7 hộp" value={r.name} />
            <TextIn label={`SKU ${i + 1}`} onChange={(sku) => upd(i, { sku })} value={r.sku} />
            <NumIn label={`Giá ${i + 1}`} onChange={(price) => upd(i, { price })} suffix="đ" value={r.price} />
            <NumIn label={`Số lượng trong gói ${i + 1}`} onChange={(packCount) => upd(i, { packCount })} value={r.packCount} />
            <NumIn label={`Tồn ${i + 1}`} onChange={(stock) => upd(i, { stock })} value={r.stock} />
            {rows.length > 1 ? (
              <button aria-label={`Bỏ phân loại ${i + 1}`} className="sa-btn sa-btn--s" onClick={() => set({ rows: rows.filter((_, k) => k !== i) })} type="button">
                ×
              </button>
            ) : null}
            {out[i] ? (
              <span className="sa-hint" data-testid={`p2-set-calc-${i + 1}`}>
                {vnd(dn(out[i], "price_per_unit"))}/đơn vị · biên {out[i]!["margin_label"] ? String(out[i]!["margin_label"]) : marginText(dn(out[i], "margin_pct"))}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {rows.length < 12 ? (
        <button className="sa-btn sa-btn--s" onClick={() => set({ rows: [...rows, { name: "", price: "", sku: "", packCount: "", stock: "" }] })} type="button">
          + Thêm phân loại
        </button>
      ) : null}
    </div>
  );
}
