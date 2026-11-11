"use client";

import { useEffect, useState } from "react";

import { MarketPriceMarker } from "../../shopee-analytics/market-price-marker";
import { fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { CoPurchase } from "../../../lib/shopee-decisions/builder-api";
import { MAX_COMBO_MEMBERS, MAX_COMBO_NAME, MAX_COMBO_TIERS, MAX_LISTING_IMAGES, MAX_TITLE, kmoney, marginText, newTier, num, voucherChips, type AddonRow, type ComboTierRow, type Forms, type NewVariation } from "../../../lib/shopee-decisions/builder-p92";
import { NumIn, Pills, ProductSelect, Seg, TextIn, VariationSelect, setAt, type PanelCtx } from "./shared";
import { ProductTargets } from "./targets";

/**
 * Input panels of the offer strategies (artboard `TuTaoPhuongAnKinds`): Voucher, Combo nhiều sản phẩm, Mua kèm,
 * Quà tặng, Giảm giá, Giá bán + Flash sale, Phân loại / set. Typed numbers only (no sliders). The figures the
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
      <p className="sa-hint">
        {form.scope === "product" ? `Voucher sản phẩm: áp cho ${ctx.product.name}. Voucher áp cho cả sản phẩm (mọi phân loại).` : form.scope === "shop" ? "Voucher shop áp cho mọi sản phẩm của shop." : "Voucher người theo dõi / khách mới và livestream / video: chưa có dữ liệu đơn theo loại voucher này để ước tính."}
      </p>
      {form.scope === "product" ? (
        <label className="p2-check" data-testid="p2-voucher-many">
          <input checked={form.items.length > 0} onChange={(e) => set({ items: e.target.checked ? [ctx.product.item_id] : [] })} type="checkbox" /> Áp cho nhiều sản phẩm (danh sách sản phẩm của voucher)
        </label>
      ) : null}
      {form.scope === "product" && form.items.length > 0 ? (
        <ProductTargets ctx={ctx} hint="Một voucher chung cho cả danh sách: kết quả tính chung, từng dòng là nếu voucher chỉ áp cho riêng sản phẩm đó." onChange={(items) => set({ items })} selected={form.items} title="Sản phẩm của voucher" />
      ) : null}
      <Seg label="Cách giảm" onChange={(dtype) => set({ dtype })} options={[["amount", "Số tiền (đ)"], ["pct", "Phần trăm (%)"]]} value={form.dtype} />
      <div className="p2-grid">
        <NumIn label="Giá trị" onChange={(value) => set({ value })} suffix={form.dtype === "pct" ? "%" : "đ"} value={form.value} />
        <NumIn hint="nhập từ 0đ" label="Đơn tối thiểu" onChange={(min) => set({ min })} suffix="đ" value={form.min} />
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
          Đơn đủ điều kiện trong quá khứ: {fmt(q)} / {fmt(t)} đơn ({fmt((q / t) * 100, 0)}%) của 30 ngày qua có giá trị từ {vnd(num(form.min) ?? 0)} trở lên.
          {dn(d, "voucher_cost_scenario") !== null ? ` Voucher ${form.dtype === "amount" ? kmoney(num(form.value) ?? 0) : `${form.value}%`} ở mức dùng dự kiến tốn ${vnd(dn(d, "voucher_cost_scenario"))}.` : ""}
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
      <ProductTargets ctx={ctx} hint="Chọn các sản phẩm của combo. Khách mua đủ số sản phẩm của một mức, ở bất kỳ sản phẩm nào trong danh sách, là được ưu đãi (Shopee không đặt số lượng riêng cho từng sản phẩm)." onChange={(items) => set({ items })} selected={form.items} title="Sản phẩm của Combo" />
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
                {rows[i]!.discount_pct !== null ? ` · tương đương giảm ${fmt(rows[i]!.discount_pct, 1)}% đơn giá` : ""} · biên {marginText(rows[i]!.margin_pct)}
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
        <NumIn hint="Số combo tối đa mỗi người mua; chưa có dữ liệu theo người mua nên không tính vào kết quả." label="Giới hạn đặt hàng" onChange={(limit) => set({ limit })} value={form.limit} />
      </div>
      <fieldset className="p2-grid" data-testid="p2-combo-time">
        <legend className="sa-hint">Thời gian chạy Combo</legend>
        <TextIn label="Bắt đầu" onChange={(start) => set({ start })} type="date" value={form.start} />
        <NumIn hint="0–23, trống = cả ngày" label="Giờ bắt đầu" onChange={(startHour) => set({ startHour })} value={form.startHour ?? ""} />
        <TextIn label="Kết thúc" onChange={(end) => set({ end })} type="date" value={form.end} />
        <NumIn hint="0–23, trống = cả ngày" label="Giờ kết thúc" onChange={(endHour) => set({ endHour })} value={form.endHour ?? ""} />
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
          <p className="sa-hint">Chưa có sản phẩm nào được mua cùng từ 2 lần trong 90 ngày.</p>
        )}
        <span className="sa-hint">Số lần mua cùng đếm từ các dòng đơn của shop, không có thông tin người mua.</span>
      </div>
      <p className="sa-hint">Voucher đi kèm và quà tặng là hai chiến lược riêng: thêm ở “Voucher” và “Quà tặng”. Listing bán combo như một sản phẩm mới ở “Listing combo mới”.</p>
    </div>
  );
}

// ── Listing combo mới ────────────────────────────────────────────────────

/**
 * A new listing that sells existing products together (P97 D85.16). Its estimate starts with no history and no
 * ranking; demand comes from the singles it contains (some of their buyers switch to the combo), which the
 * result states. Images are kept as references (file names); Juli does not upload them. No fill-in yet.
 */
export function ListingComboPanel({ form, set, ctx }: P<"listing_combo">) {
  const d = details(ctx);
  const assumption = typeof d["assumption"] === "string" ? (d["assumption"] as string) : null;
  const singles = (Array.isArray(d["members"]) ? d["members"] : []) as Readonly<Record<string, unknown>>[];
  return (
    <div className="p2-panel" data-testid="p2-panel-listing-combo">
      <TextIn hint={`${[...form.title].length}/${MAX_TITLE} ký tự`} label="Tên listing combo" onChange={(title) => set({ title })} value={form.title} />
      <div className="p2-grid">
        <NumIn label="Giá bán listing combo" onChange={(price) => set({ price })} suffix="đ" value={form.price} />
        <NumIn label="Tồn kho" onChange={(stock) => set({ stock })} value={form.stock} />
        <TextIn label="SKU" onChange={(sku) => set({ sku })} value={form.sku} />
      </div>
      <div className="p2-field" data-testid="p2-lc-images">
        <span className="sd-field__label">Ảnh (tối đa {MAX_LISTING_IMAGES})</span>
        <input
          accept="image/*"
          aria-label="Chọn ảnh listing combo"
          multiple
          onChange={(e) => set({ images: [...form.images, ...Array.from(e.target.files ?? []).map((f) => f.name)].slice(0, MAX_LISTING_IMAGES) })}
          type="file"
        />
        {form.images.length > 0 ? (
          <ul className="p2-sel__list">
            {form.images.map((name, i) => (
              <li className="sb-pill sb-pill--on" key={`${name}-${i}`}>
                {name}
                <button aria-label={`Bỏ ảnh ${name}`} className="p2-sel__x" onClick={() => set({ images: form.images.filter((_, k) => k !== i) })} type="button">
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <span className="sa-hint">Juli chỉ ghi lại tên / mã tham chiếu của ảnh; bạn tải ảnh lên Seller Centre khi tạo listing.</span>
      </div>
      <ProductTargets ctx={ctx} hint="Chọn các sản phẩm thành phần (từ 2 sản phẩm)." max={MAX_COMBO_MEMBERS} onChange={(members) => set({ members })} selected={form.members} title="Sản phẩm thành phần" />
      <p className="sa-hint" data-testid="p2-lc-assumption">
        {assumption ?? "Giả định: listing mới chưa có lịch sử bán và chưa có thứ hạng tìm kiếm. Một phần khách của các sản phẩm lẻ trong combo chuyển sang mua combo (cannibalize); Juli không cộng số đơn đó như đơn mới."}
      </p>
      {singles.length > 0 ? (
        <Calc rows={singles.map((m): [string, string] => [String(m["name"] ?? m["item_id"]), `${fmt(dn(m, "orders_30d"))} đơn / 30 ngày · ${vnd(dn(m, "price"))}`])} testId="p2-lc-members" />
      ) : null}
      <p className="sa-hint">Chưa tự điền vào Seller Centre: form Thêm sản phẩm chưa được ghi lại. Bạn tạo listing thủ công.</p>
    </div>
  );
}

// ── Mua kèm ──────────────────────────────────────────────────────────────

export function AddOnPanel({ form, set, ctx }: P<"add_on">) {
  const d = details(ctx);
  const lines = (Array.isArray(d["addons"]) ? d["addons"] : []) as Readonly<Record<string, unknown>>[];
  const rows = form.addons;
  const upd = (i: number, patch: Partial<AddonRow>) => set({ addons: setAt(rows, i, patch) });
  return (
    <div className="p2-panel" data-testid="p2-panel-addon">
      <p className="sa-hint">
        Sản phẩm chính: <b>{ctx.product.name}</b>
      </p>
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
      {rows.length < 5 ? (
        <button className="sa-btn sa-btn--s" onClick={() => set({ addons: [...rows, { itemId: "", variationId: "", mode: "pct", value: "15", limit: "1" }] })} type="button">
          + Thêm sản phẩm mua kèm
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

// ── Quà tặng ─────────────────────────────────────────────────────────────

export function GiftPanel({ form, set, ctx }: P<"gift">) {
  const g = (ctx.outcome?.details?.["gift"] ?? {}) as Readonly<Record<string, unknown>>;
  return (
    <div className="p2-panel" data-testid="p2-panel-gift">
      <Seg label="Quà tặng là" onChange={(source) => set({ source })} options={[["listing", "Sản phẩm trong danh sách"], ["unsold", "Quà không bán"]]} value={form.source} />
      {form.source === "listing" ? (
        <div className="p2-field">
          <span className="sd-field__label">Sản phẩm làm quà</span>
          <ProductSelect label="Sản phẩm làm quà" onChange={(giftItemId) => set({ giftItemId })} products={ctx.products} value={form.giftItemId} />
        </div>
      ) : (
        <div className="p2-grid">
          <TextIn label="Quà không bán · tên" onChange={(label) => set({ label })} value={form.label} />
          <NumIn hint="Quà không bán không trừ tồn kho trong Juli." label="Chi phí mỗi quà" onChange={(unitCost) => set({ unitCost })} suffix="đ" value={form.unitCost} />
        </div>
      )}
      <div className="p2-grid">
        <NumIn label="Đóng gói mỗi quà" onChange={(packaging) => set({ packaging })} suffix="đ" value={form.packaging} />
        <NumIn label="Số lượng quà" onChange={(qty) => set({ qty })} value={form.qty} />
      </div>
      <Seg label="Điều kiện nhận quà" onChange={(trigger) => set({ trigger })} options={[["buy_item", "Mua sản phẩm X"], ["min_spend", "Đơn từ mức tối thiểu"]]} value={form.trigger} />
      {form.trigger === "min_spend" ? (
        <NumIn label="Đơn tối thiểu" onChange={(minSpend) => set({ minSpend })} suffix="đ" value={form.minSpend} />
      ) : (
        <div className="p2-field">
          <span className="sd-field__label">Sản phẩm phải mua</span>
          <ProductSelect allowEmpty={false} label="Sản phẩm phải mua" onChange={(triggerItemId) => set({ triggerItemId })} products={ctx.products} value={form.triggerItemId || ctx.product.item_id} />
        </div>
      )}
      {dn(g, "cost_per_gift") !== null ? (
        <Calc
          rows={[
            ["Chi phí mỗi quà = giá vốn + đóng gói", vnd(dn(g, "cost_per_gift"))],
            ["Đơn nhận quà dự kiến", `${fmt(dn(g, "qualifying_orders"))} đơn`],
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

function VarRows({ ctx, rows, mode, direction, onRow }: { readonly ctx: PanelCtx; readonly direction: "off" | "change"; readonly rows: readonly { readonly variationId: string; readonly value: string }[]; readonly mode: "pct" | "final_price"; readonly onRow: (id: string, value: string) => void }) {
  const skus = (Array.isArray(ctx.outcome?.details?.["skus"]) ? ctx.outcome!.details!["skus"] : []) as Readonly<Record<string, unknown>>[];
  return (
    <div className="p2-rows" data-testid="p2-varrows">
      {ctx.variations.map((v, i) => {
        const val = rows.find((r) => r.variationId === v.variation_id)?.value ?? "";
        const sku = skus[i];
        return (
          <div className="p2-row p2-row--wrap" key={v.variation_id || "default"}>
            <span className="p2-row__name">
              <b>{v.name}</b>
              <span className="sa-hint">giá hiện tại {vnd(v.selling_price)}</span>
            </span>
            <NumIn label={`${pctLabel(mode, direction)} · ${v.name}`} onChange={(x) => onRow(v.variation_id, x)} suffix={mode === "pct" ? "%" : "đ"} value={val} />
            {mode === "pct" && direction === "change" ? <span className="sa-hint">−5 = giảm 5%, +5 = tăng 5%</span> : null}
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

export function DiscountPanel({ form, set, ctx }: P<"product_discount">) {
  return (
    <div className="p2-panel" data-testid="p2-panel-discount">
      <Seg label="Áp dụng cho" onChange={(v) => set({ multi: v === "many", targets: v === "many" && form.targets.length === 0 ? [ctx.product.item_id] : form.targets })} options={[["one", "Sản phẩm đã chọn"], ["many", "Nhiều sản phẩm cùng một mức giảm"]]} value={form.multi ? "many" : "one"} />
      {form.multi ? (
        <>
          <NumIn hint="Một mức giảm cho mọi phân loại của từng sản phẩm; mỗi sản phẩm tính riêng, tổng cộng lại." label="Mức giảm cho tất cả" onChange={(pct) => set({ pct })} suffix="%" value={form.pct} />
          <ProductTargets ctx={ctx} hint="Chọn các sản phẩm cùng được giảm giá. Bỏ tick ở phần kết quả để loại sản phẩm chạm giá sàn." onChange={(targets) => set({ targets })} selected={form.targets} title="Sản phẩm được giảm giá" />
        </>
      ) : (
        <>
          <Seg label="Nhập giảm theo" onChange={(mode) => set({ mode })} options={[["pct", "Phần trăm (%)"], ["final_price", "Giá cuối (đ)"]]} value={form.mode} />
          <VarRows ctx={ctx} direction="off" mode={form.mode} onRow={(id, v) => set({ rows: upsert(form.rows, id, v) })} rows={form.rows} />
        </>
      )}
      <div className="p2-grid">
        <TextIn label="Bắt đầu" onChange={(start) => set({ start })} type="date" value={form.start} />
        <TextIn label="Kết thúc" onChange={(end) => set({ end })} type="date" value={form.end} />
        <NumIn label="Giới hạn mỗi người" onChange={(perBuyer) => set({ perBuyer })} value={form.perBuyer} />
      </div>
    </div>
  );
}

export function PriceFlashPanel({ form, set, ctx }: P<"price_flash">) {
  return (
    <div className="p2-panel" data-testid="p2-panel-flash">
      <Pills label="Loại thay đổi" onChange={(what) => set({ what })} options={[["price", "Đổi giá niêm yết"], ["flash_sale", "Flash sale của shop"]]} value={form.what} />
      <Seg label={form.what === "price" ? "Nhập giá theo" : "Nhập giảm theo"} onChange={(mode) => set({ mode })} options={[["pct", form.what === "price" ? "Thay đổi (%)" : "Giảm (%)"], ["final_price", form.what === "price" ? "Giá bán mới (đ)" : "Giá flash sale (đ)"]]} value={form.mode} />
      <VarRows ctx={ctx} direction={form.what === "price" ? "change" : "off"} mode={form.mode} onRow={(id, v) => set({ rows: upsert(form.rows, id, v) })} rows={form.rows} />
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
      <p className="sa-hint">Chỉ thêm / gộp phân loại với giá và SKU riêng. Juli không tự tạo phân loại ở Seller Centre; bạn lưu thủ công. Giá vốn lấy từ Thông số shop.</p>
    </div>
  );
}
