// The page fillers of a fill job: voucher form, ads edit popups, affiliate commission edit. Each
// writes the text / number boxes of the approved card and returns a checklist. 0.3.28 (F5.1/F5.2):
// nothing is ever clicked on Shopee's page. A control that needs a click (a radio, a drop-down, the
// date-time picker, the product picker, "Thêm mức ưu đãi", a pencil, a notice's close) is a numbered
// step for the person, highlighted on the page; it turns ✓ once the form shows the card's value,
// and a box that click reveals is written on the next re-check (FillLog.later). Shopee's Lưu /
// Xác nhận / Gửi / Cập nhật are the person's, as before. Labels are the visible Vietnamese ones
// recorded on ORY's Seller Centre (fasttrack/contracts/p97-recon-2026-11-09.md).

import {
  chooseRadio,
  chooseSelect,
  dateText,
  type Env,
  findDialog,
  findEditPencil,
  findPressable,
  findRow,
  type Guide,
  highlight,
  holdsId,
  noticeDialogs,
  noticeStep,
  noticeTitle,
  pickProducts,
  pickStep,
  type PickResult,
  radioOf,
  radioOptions,
  setDate,
  setRowText,
  setSwitch,
  textBoxesIn,
  waitFor,
  writeBox,
} from "./controls";
import type { AdsPayload, AffiliatePayload, ComboPayload, FillJob, PriceVariation, VoucherPayload } from "./job-types";
import { normalizeLabel } from "../../../core/fill/locate";
import { keyed } from "../../../core/fill/log";
import { writeValue } from "../../../core/fill/write";

export type { FillOutcome, Step } from "../../../core/fill/form";
import type { CurrentRow, FillOutcome, Step } from "../../../core/fill/form";

export const dong = (n: number) => `${n.toLocaleString("vi-VN")} ₫`;

/** A value safe inside a CSS attribute selector. jsdom tests have no CSS.escape. */
export function cssAttr(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return value.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
}

/** The variation row on the product edit page, by its id, else by its name when that name is unique. */
export function variationPriceRow(doc: Document, variationId: string, name?: string): HTMLElement | null {
  const byId = doc.querySelector<HTMLElement>(`[data-variation-id="${cssAttr(variationId)}"]`);
  if (byId) return byId;
  if (!name) return null;
  const wanted = normalizeLabel(name);
  const hits = Array.from(doc.querySelectorAll<HTMLElement>("div,tr,li")).filter((el) => {
    if (!textBoxesIn(el).length) return false;
    const own = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3 || n.nodeType === 1)
      .map((n) => normalizeLabel(n.textContent ?? ""))
      .join(" ");
    return own.includes(wanted) && !Array.from(el.querySelectorAll("[data-variation-id]")).some((inner) => inner !== el && textBoxesIn(inner).length > 0);
  });
  return hits.length === 1 ? (hits[0] as HTMLElement) : null;
}

/** The report key of one variation's price (`price_<id letters and digits>`). */
export const priceKey = (variationId: string) => `price_${variationId.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30)}`;

/** Writes each variation's price into its own box. One variation never receives another's price. */
export async function fillVariationPrices(env: Env, variations: readonly PriceVariation[]): Promise<FillOutcome> {
  const steps: Step[] = [];
  for (const v of variations) {
    const row = variationPriceRow(env.doc, v.variationId, v.name);
    const box = row ? textBoxesIn(row)[0] : undefined;
    // a key Juli's report accepts ([a-z0-9_]): the revert reads the before price under it
    const key = priceKey(v.variationId);
    const ok = !!box && writeBox(keyed(env, key), box, String(v.price));
    steps.push({
      label: `${v.name ?? v.variationId}: ${dong(v.price)}`,
      ok,
      keys: [key],
      ...(ok ? {} : { note: row ? "Shopee chưa nhận giá." : "Không thấy ô giá của phân loại này." }),
    });
  }
  return {
    steps,
    todo: ["Kiểm tra từng phân loại rồi bấm Cập nhật / Lưu của Shopee."],
    notes: [],
  };
}

export const VOUCHER_LABELS = {
  name: "Tên chương trình giảm giá",
  code: "Mã voucher",
  period: "Thời gian sử dụng mã",
  type: "Loại Voucher",
  /** Not on the live page any more (2026-11-17): set off only when Shopee still draws it. */
  smart: "Mã giảm giá thông minh",
  discount: "Loại giảm giá | Mức giảm",
  max: "Mức giảm tối đa",
  minSpend: "Giá trị đơn hàng tối thiểu",
  usageTotal: "Tổng lượt sử dụng tối đa",
  perBuyer: "Lượt sử dụng tối đa/Người mua",
  display: "Thiết lập hiển thị",
  products: "Sản phẩm được áp dụng",
} as const;

const DISPLAY_OPTION = { multi: "Hiển thị nhiều nơi", code: "Chia sẻ thông qua mã Voucher", private: "Không công khai" } as const;
/** Every spelling of a display option seen on Seller Centre (and on Juli's card: "Chia sẻ qua mã voucher"). */
const DISPLAY_ALIASES = {
  multi: ["Hiển thị nhiều nơi"],
  code: ["Chia sẻ thông qua mã Voucher", "Chia sẻ qua mã voucher"],
  private: ["Không công khai"],
} as const;
export const SMART_MISSING = "Trang không có ô «Mã giảm giá thông minh»; bật tay nếu cần";
/** The note of a step the person does (the control is highlighted on the page). */
export const GUIDE_NOTE = "Bạn bấm chọn trên trang (ô được tô viền)";

/** The field keys of a fill (the job report's `before_values` and `fields` use them). */
export const PERIOD_KEYS = ["starts_at", "ends_at"];
export const PERIOD_NOTE = "Chọn tay thời gian theo thẻ — Shopee đang để mặc định là bây giờ.";

export type Add = (label: string, ok: boolean, opts?: { note?: string; keys?: string[]; guide?: boolean }) => void;

export function stepper(steps: Step[]): Add {
  return (label, ok, opts = {}) =>
    steps.push({
      label,
      ok,
      ...(opts.note && !ok ? { note: opts.note } : {}),
      ...(opts.keys ? { keys: opts.keys } : {}),
      ...(opts.guide && !ok ? { guide: true } : {}),
    });
}

/**
 * A click-needing control's step: done → the card's label ✓; todo → the person's numbered step
 * (`todo` text, highlighted on the page); missing → the card's label ✗.
 */
export function choice(add: Add, g: Guide, label: string, todo: string, keys: string[], note?: string): void {
  if (g === "todo") add(todo, false, { keys, guide: true });
  else add(label, g === "done", { keys, ...(note ? { note } : {}) });
}

/** The period: two typed dates make one step; a picker the person sets makes one step per date. */
export function period(env: Env, add: Add, label: string, startsAt: string, endsAt: string): void {
  const start = setDate(keyed(env, "starts_at"), label, startsAt, 0);
  const end = setDate(keyed(env, "ends_at"), label, endsAt, 1);
  if (start !== "todo" && end !== "todo") {
    add(`Thời gian: ${startsAt} → ${endsAt}`, start === "done" && end === "done", { note: PERIOD_NOTE, keys: PERIOD_KEYS });
    return;
  }
  choice(add, start, `Bắt đầu: ${startsAt}`, `Chọn ngày bắt đầu ${dateText(startsAt)}`, ["starts_at"], PERIOD_NOTE);
  choice(add, end, `Kết thúc: ${endsAt}`, `Chọn ngày kết thúc ${dateText(endsAt)}`, ["ends_at"], PERIOD_NOTE);
}

export function picked(add: Add, p: PickResult, opener: string, ids: readonly string[], names: Readonly<Record<string, string>> = {}): void {
  if (p.done) add(`Sản phẩm: ${ids.length}/${ids.length} đã chọn`, true, { keys: ["product_ids"] });
  else if (p.reason) add(`Sản phẩm: 0/${ids.length}`, false, { keys: ["product_ids"], note: p.reason });
  else add(pickStep(opener, ids, names), false, { keys: ["product_ids"], guide: true });
}

/** A box written now when it is on the page, else once the person's click reveals it. */
export function writeOrLater(env: Env, key: string, find: () => HTMLInputElement | undefined | null, value: string): boolean {
  const box = find();
  if (box) return writeBox(keyed(env, key), box, value);
  env.log?.later({
    key,
    write: () => {
      const b = find();
      return !!b && (writeBox(keyed(env, key), b, value) || true);
    },
  });
  return false;
}

const rowBox = (env: Env, label: string, index = 0) => () => {
  const row = findRow(env.doc, label);
  return row ? textBoxesIn(row)[index] : undefined;
};

export async function fillVoucher(env: Env, v: VoucherPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const L = VOUCHER_LABELS;
  const k = (key: string) => keyed(env, key);
  add(`Tên chương trình: ${v.name}`, setRowText(k("name"), L.name, v.name), { keys: ["name"] });
  add(`Mã voucher: …${v.codeSuffix}`, setRowText(k("code_suffix"), L.code, v.codeSuffix), { keys: ["code_suffix"] });
  period(env, add, L.period, v.startsAt, v.endsAt);
  choice(add, chooseRadio(k("voucher_type"), L.type, "Khuyến Mãi"), "Loại voucher: Khuyến Mãi", "Chọn «Khuyến Mãi» ở «Loại Voucher»", ["voucher_type"]);
  // 0.3.27: set to the card's value when Shopee draws it; a card that wants it on and a page without it is ✗
  if (findRow(env.doc, L.smart)) {
    choice(add, setSwitch(k("smart"), L.smart, v.smart), `Mã giảm giá thông minh: ${v.smart ? "bật" : "tắt"}`, `${v.smart ? "Bật" : "Tắt"} «Mã giảm giá thông minh»`, ["smart"]);
  } else if (v.smart) add("Mã giảm giá thông minh: bật", false, { note: SMART_MISSING });
  const kindText = v.discount.type === "amount" ? "Theo số tiền" : "Theo phần trăm";
  const kind = chooseSelect(k("discount_type"), L.discount, kindText);
  const valueText = v.discount.type === "amount" ? `Giảm ${dong(v.discount.value)}` : `Giảm ${v.discount.value}%`;
  const typed = setRowText(k("discount"), L.discount, String(v.discount.value));
  if (kind === "todo") {
    add(`Chọn «${kindText}»`, false, { keys: ["discount_type"], guide: true });
    add(valueText, typed, { keys: ["discount"] });
  } else add(valueText, kind === "done" && typed, { keys: ["discount_type", "discount"] });
  if (v.discount.type === "percent") {
    if (v.discount.max.mode === "limited") {
      const radio = chooseRadio(k("max_mode"), L.max, "Giới hạn");
      const maxText = `Giảm tối đa ${dong(v.discount.max.value)}`;
      // the amount box may show only once "Giới hạn" is chosen
      const box = writeOrLater(env, "max_value", rowBox(env, L.max), String(v.discount.max.value));
      if (radio === "todo") {
        add("Chọn «Giới hạn» ở «Mức giảm tối đa»", false, { keys: ["max_mode"], guide: true });
        add(maxText, box, { keys: ["max_value"] });
      } else add(maxText, radio === "done" && box, { keys: ["max_mode", "max_value"] });
    } else {
      choice(add, chooseRadio(k("max_mode"), L.max, "Không giới hạn"), "Giảm tối đa: không giới hạn", "Chọn «Không giới hạn» ở «Mức giảm tối đa»", ["max_mode"]);
    }
  }
  add(`Đơn tối thiểu ${dong(v.minSpend)}`, setRowText(k("min_spend"), L.minSpend, String(v.minSpend)), { keys: ["min_spend"] });
  add(`Tổng lượt dùng ${v.usageTotal}`, setRowText(k("usage_total"), L.usageTotal, String(v.usageTotal)), { keys: ["usage_total"] });
  add(`Mỗi người mua ${v.perBuyer} lượt`, setRowText(k("per_buyer"), L.perBuyer, String(v.perBuyer)), { keys: ["per_buyer"] });
  const display = chooseRadio(k("display"), L.display, DISPLAY_ALIASES[v.display]);
  const offered = display === "missing" ? radioOptions(env.doc, L.display) : [];
  if (offered.length > 0) {
    // E146: the product-voucher page offers other words ("Hiển thị nhiều nơi" / "Không công khai"); the
    // captures do not say they mean the card's option, so Juli picks nothing: the person chooses
    for (const o of offered) highlight(o.holder);
    add(`Chọn ở «${L.display}»: ${offered.map((o) => `«${o.text}»`).join(" hoặc ")} (thẻ ghi «${DISPLAY_OPTION[v.display]}»)`, false, { keys: ["display"], guide: true });
  } else choice(add, display, `Hiển thị: ${DISPLAY_OPTION[v.display]}`, `Chọn «${DISPLAY_OPTION[v.display]}» ở «Thiết lập hiển thị»`, ["display"]);
  if (v.productIds.length > 0) picked(add, pickProducts(k("product_ids"), "Thêm sản phẩm", v.productIds, v.productNames), "Thêm sản phẩm", v.productIds, v.productNames);
  return {
    steps,
    todo: [GUIDED_TODO, "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo voucher."],
    notes: [NEVER_CLICKS],
    periodKeys: PERIOD_KEYS,
  };
}

/** 0.3.28: what the person does first (the numbered steps), and the reminder. */
export const GUIDED_TODO = "Làm các bước có số theo thứ tự (ô được tô viền trên trang); Juli điền các ô số khi chúng hiện ra.";
export const NEVER_CLICKS = "Juli không bấm gì trên trang Shopee — mọi cú bấm là của bạn.";

// -- combo khuyến mãi (bundle deal) ----------------------------------------------------------

export const COMBO_LABELS = {
  name: "Tên Combo Khuyến Mãi",
  period: "Thời gian chạy Combo",
  type: "Loại Combo",
  tiers: "Mức ưu đãi",
  addTier: "Thêm mức ưu đãi",
  limit: "Giới hạn đặt hàng",
  products: "Thêm sản phẩm",
} as const;

const COMBO_TYPE_OPTION = { pct: "Giảm giá theo %", amount: "Giảm giá theo số tiền", special_price: "Giảm giá đặc biệt" } as const;
const COMBO_TIER_TEXT = {
  pct: (q: number, v: number) => `Mua ${q} giảm ${v}%`,
  amount: (q: number, v: number) => `Mua ${q} giảm ${dong(v)}`,
  special_price: (q: number, v: number) => `Mua ${q} chỉ với giá ${dong(v)}`,
} as const;

/**
 * The tier rows, in order, each holding its two boxes ("Mua [N] sản phẩm để được giảm [X]"):
 * under the "Mức ưu đãi" row when Shopee labels it, else every innermost element whose text reads
 * "Mua … sản phẩm …" and holds exactly two boxes (the live page, 2026-11-17).
 */
export function tierRows(doc: Document): HTMLInputElement[][] {
  // a2 C-E116 (capture c2/01, 23/11): the boxes are named tiers.<i>.minAmount and tiers.<i>.<value>
  // (discountPercentage in % mode); the names win over the CSS-module classes
  const named: HTMLInputElement[][] = [];
  for (let i = 0; i < 20; i += 1) {
    const qty = doc.querySelector<HTMLInputElement>(`input[name="tiers.${i}.minAmount"]`);
    const own = new RegExp(`^tiers\\.${i}\\.[A-Za-z]+$`);
    const value = Array.from(doc.querySelectorAll<HTMLInputElement>(`input[name^="tiers.${i}."]`)).find((el) => el !== qty && own.test(el.name) && !el.disabled && !el.readOnly);
    if (!qty || !value) break;
    named.push([qty, value]);
  }
  if (named.length > 0) return named;
  // live 2026-11-18: one table row per tier, the text split around the boxes; the boxes carry the
  // CSS-module names minAmount (N) and discountValue / discountInput (X)
  const live = Array.from(doc.querySelectorAll<HTMLElement>("tr,[class*='table-row']"))
    .map((r) => [r.querySelector<HTMLInputElement>('[class*="minAmount"] input'), r.querySelector<HTMLInputElement>('[class*="discountValue"] input,[class*="discountInput"] input')] as const)
    .filter((pair): pair is readonly [HTMLInputElement, HTMLInputElement] => !!pair[0] && !!pair[1] && textBoxesIn(pair[0].parentElement!).length > 0 && textBoxesIn(pair[1].parentElement!).length > 0);
  const uniq = live.filter((pair, i) => live.findIndex((o) => o[0] === pair[0]) === i);
  if (uniq.length > 0) return uniq.map((pair) => [pair[0], pair[1]]);
  const labelled = findRow(doc, COMBO_LABELS.tiers);
  const scope: ParentNode = labelled ?? doc.body;
  const rows = Array.from(scope.querySelectorAll<HTMLElement>("div,li,tr")).filter(
    (el) => /^mua.*sản phẩm/.test(normalizeLabel((el.textContent ?? "").slice(0, 200))) && textBoxesIn(el).length === 2,
  );
  const inner = rows.filter((r) => !rows.some((o) => o !== r && r.contains(o)));
  if (inner.length > 0) return inner.map((r) => textBoxesIn(r));
  // one row element holding every tier's pair of boxes
  if (!labelled) return [];
  const boxes = textBoxesIn(labelled);
  const out: HTMLInputElement[][] = [];
  for (let i = 0; i + 1 < boxes.length; i += 2) out.push([boxes[i]!, boxes[i + 1]!]);
  return out;
}

export async function fillCombo(env: Env, c: ComboPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const L = COMBO_LABELS;
  const k = (key: string) => keyed(env, key);
  // the type first: it decides what the tier rows ask for
  choice(add, chooseRadio(k("discount_type"), L.type, COMBO_TYPE_OPTION[c.discountType]), `Loại combo: ${COMBO_TYPE_OPTION[c.discountType]}`, `Chọn «${COMBO_TYPE_OPTION[c.discountType]}» ở «Loại Combo»`, ["discount_type"]);
  add(`Tên combo: ${c.name}`, setRowText(k("name"), L.name, c.name), { keys: ["name"] });
  period(env, add, L.period, c.startsAt, c.endsAt);
  // 0.3.28: the rows on the page are written now; a further tier is the person's "Thêm mức ưu đãi"
  // (Shopee enables it once the tier above is valid), and Juli writes the row it adds (E48)
  let asked = false;
  for (const [i, t] of c.tiers.entries()) {
    const keys = [`tier${i + 1}_qty`, `tier${i + 1}_value`];
    const text = COMBO_TIER_TEXT[c.discountType](t.qty, t.value);
    const write = (row: HTMLInputElement[]) => writeBox(k(keys[0]!), row[0]!, String(t.qty)) && writeBox(k(keys[1]!), row[1]!, String(t.value));
    const row = tierRows(env.doc)[i];
    if (row) {
      add(text, write(row), { keys });
      continue;
    }
    if (i === 0) {
      add(text, false, { keys, note: TIER_MISSING });
      continue;
    }
    if (!asked) {
      // capture c2/01: div.eds-react-table-footer > button "Thêm mức ưu đãi" (class `disabled` until the tier above is valid)
      const more = findPressable(env, L.addTier) ?? addTierButton(env.doc);
      if (more) highlight((more.closest("button") as HTMLElement | null) ?? more);
      asked = true;
    }
    env.log?.later({
      key: keys[0]!,
      write: () => {
        const r = tierRows(env.doc)[i];
        return !!r && (write(r) || true);
      },
    });
    add(`Bấm «${L.addTier}» rồi Juli điền: ${text}`, false, { keys, guide: true });
  }
  if (c.purchaseLimit !== undefined) {
    // a2 C-E116 (capture c2/01): the box is input[name="usageLimit"] (type numeric); the label is the fallback
    const box = env.doc.querySelector<HTMLInputElement>('input[name="usageLimit"]');
    const ok = box ? writeBox(k("purchase_limit"), box, String(c.purchaseLimit)) : setRowText(k("purchase_limit"), L.limit, String(c.purchaseLimit));
    add(`Giới hạn đặt hàng: ${c.purchaseLimit}`, ok, { keys: ["purchase_limit"] });
  }
  picked(add, pickProducts(k("product_ids"), L.products, c.productIds, c.productNames), L.products, c.productIds, c.productNames);
  return {
    steps,
    todo: [GUIDED_TODO, "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo combo."],
    notes: [NEVER_CLICKS],
    periodKeys: PERIOD_KEYS,
  };
}

export const TIER_MISSING = "Không thấy dòng «Mua … sản phẩm» của mức này";

/** "Thêm mức ưu đãi" under the tier table (found to highlight, never pressed). */
function addTierButton(doc: Document): HTMLElement | null {
  const want = normalizeLabel(COMBO_LABELS.addTier);
  return Array.from(doc.querySelectorAll<HTMLElement>('[class*="table-footer"] button')).find((b) => normalizeLabel(b.textContent ?? "") === want) ?? null;
}

// -- ads edit ------------------------------------------------------------------------------

export const ADS_LABELS = {
  budgetCard: "Ngân sách",
  budgetDialog: "Chỉnh sửa ngân sách",
  roasCard: "Mục tiêu ROAS",
  roasDialog: "Mục tiêu ROAS",
  daily: "Ngân sách hàng ngày",
  unlimited: "Không giới hạn",
  custom: "Tùy chỉnh",
} as const;
export const ROAS_HINT_MAX = 3.5;

/**
 * 0.3.28: one ads popup, guided. The person opens it (the card's pencil is highlighted) and picks
 * the radio; the amount box is written as soon as it shows with that radio chosen. Each step reads
 * the popup as it is now (✓ once it shows the card's choice / value).
 */
function adsDialog(
  env: Env,
  add: Add,
  o: { card: string; heading: string; radio: string; radioKey: string; box?: { key: string; value: string; label: string } },
): void {
  const dialog = () => findDialog(env, o.heading);
  const radio = () => {
    const d = dialog();
    return d ? radioOf(env.doc, o.radio, o.radio, d) : null;
  };
  if (!dialog()) {
    const pencil = findEditPencil(env, o.card);
    if (!pencil) {
      add(`Mở cửa sổ ${o.heading}`, false, { note: `Không thấy nút bút chì của ${o.card.toLowerCase()}.` });
      return;
    }
    highlight(pencil);
    const key = `${o.radioKey}_open`;
    env.log?.wrote({ key, el: env.doc.body, want: "đã mở", seen: () => (dialog() ? "đã mở" : "đang đóng"), ok: () => !!dialog() });
    add(`Bấm bút chì ở «${o.card}» để mở «${o.heading}»`, false, { keys: [key], guide: true });
  }
  const chosen = () => radio()?.chosen() ?? "";
  if (env.log) {
    env.log.captureBefore(o.radioKey, chosen());
    env.log.wrote({ key: o.radioKey, el: env.doc.body, want: o.radio, seen: chosen, ok: () => !!radio()?.holds() });
  }
  const now = radio();
  if (now?.holds()) add(`${o.radio}`, true, { keys: [o.radioKey] });
  else {
    if (now) highlight(now.holder);
    // highlighted once the person opens the popup
    else env.log?.later({ key: `${o.radioKey}_mark`, write: () => { const r = radio(); if (r && !r.holds()) highlight(r.holder); return !!r; } });
    add(`Chọn «${o.radio}» trong «${o.heading}»`, false, { keys: [o.radioKey], guide: true });
  }
  if (!o.box) return;
  const box = o.box;
  const find = () => (radio()?.holds() ? textBoxesIn(dialog()!)[0] : undefined);
  add(box.label, writeOrLater(env, box.key, find, box.value), { keys: [box.key] });
}

export async function fillAds(env: Env, a: AdsPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const notes: string[] = [NEVER_CLICKS];
  const todo: string[] = [GUIDED_TODO];
  if (a.budget) {
    const unlimited = a.budget.mode === "unlimited";
    adsDialog(env, add, {
      card: ADS_LABELS.budgetCard,
      heading: ADS_LABELS.budgetDialog,
      radio: unlimited ? ADS_LABELS.unlimited : ADS_LABELS.daily,
      radioKey: "budget_mode",
      ...(a.budget.mode === "unlimited" ? {} : { box: { key: "daily_budget", value: String(a.budget.value), label: `Ngân sách hàng ngày: ${dong(a.budget.value)}` } }),
    });
    todo.push("Bấm Xác nhận trong cửa sổ ngân sách của Shopee.");
    if (a.roas) notes.push("Mục tiêu ROAS: làm ở lần mở trang kế tiếp (mỗi lần chỉ một cửa sổ).");
  } else if (a.roas) {
    adsDialog(env, add, {
      card: ADS_LABELS.roasCard,
      heading: ADS_LABELS.roasDialog,
      radio: ADS_LABELS.custom,
      radioKey: "roas_mode",
      box: { key: "roas_target", value: String(a.roas.value), label: `Mục tiêu ROAS: ${a.roas.value}` },
    });
    if (a.roas.value > ROAS_HINT_MAX) notes.push(`Shopee gợi ý ROAS ≤ ${ROAS_HINT_MAX}; giá trị này cao hơn.`);
    notes.push("Đổi ROAS từ 2 lần trong một tuần sẽ mất hỗ trợ hiệu quả của tuần đó.");
    todo.push("Bấm Xác nhận trong cửa sổ ROAS của Shopee.");
  }
  return { steps, todo, notes };
}

// -- affiliate: open campaign (Chiến dịch mở rộng) commission ----------------------------------
//
// 0.3.27 (E51): the page opens under Shopee's "new version" notice, lists 100+ products over several
// pages, and rendered in Vietnamese or English (2026-11-18). 0.3.28: nothing is pressed. The person
// closes the notice, finds the row (Juli writes the id into the page's search box, a value write),
// and opens the row's own rate control (or ticks the rows and uses the bulk edit); the rate box that
// opens is written on the next re-check. Shopee's Lưu / Lưu lại stays with the person. The rate the
// page showed is kept as the before value (the revert puts it back).

export const AFFILIATE_LABELS = {
  bulk: ["Chỉnh sửa hàng loạt", "Batch Edit"],
  commission: ["Chỉnh sửa tỉ lệ hoa hồng", "Edit Commission Rate", "Edit Commission"],
  search: ["Tìm kiếm", "Tìm", "Search"],
} as const;
export const AFFILIATE_NO_FILTER = "Không thấy ô tìm sản phẩm theo tên / ID trên trang Chiến dịch mở rộng";
export const AFFILIATE_NO_ROW = (ids: readonly string[]) => `Không thấy dòng của ID ${ids.join(", ")} trên trang đang hiện`;
/** 0.3.28: a read-back never changes page; a product not on the page shown is not read. */
export const AFFILIATE_NOT_SHOWN = "Juli không bấm chuyển trang / Tìm: mở trang có sản phẩm này để Juli đọc lại";
export const AFFILIATE_NO_EDITOR = "Không thấy ô sửa tỉ lệ của dòng này";

function pressableOf(env: Env, texts: readonly string[], within?: Element): HTMLElement | null {
  for (const t of texts) {
    const hit = findPressable(env, t, within);
    if (hit) return hit;
  }
  return null;
}

/** The list's product rows (not the table's measure row). */
function campaignRows(doc: Document): HTMLElement[] {
  return Array.from(doc.querySelectorAll<HTMLElement>("tbody tr,[role='row']")).filter(
    (r) => !/measure-row/.test(r.className.toString()) && !r.closest('[role="dialog"],[class*="modal"]') && !r.closest("[hidden]"),
  );
}

/** The row showing this product id, or null (none, or more than one). */
export function affiliateRowOf(doc: Document, id: string): HTMLElement | null {
  const rows = campaignRows(doc).filter((r) => holdsId(r, id));
  const inner = rows.filter((h) => !rows.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (inner[0] as HTMLElement) : null;
}

const RATE = /^(\d{1,2}(?:[.,]\d{1,2})?)\s*%$/;

/** The rate cell of a row ("13%") and its value, or null. */
export function rateOf(row: Element): { cell: HTMLElement; pct: number } | null {
  for (const el of Array.from(row.querySelectorAll<HTMLElement>("*"))) {
    const m = el.children.length === 0 ? RATE.exec((el.textContent ?? "").trim()) : null;
    if (m) return { cell: (el.closest("td") ?? el.parentElement ?? el) as HTMLElement, pct: Number(m[1]!.replace(",", ".")) };
  }
  return null;
}

const ROW_ID = /(?:product id|id sản phẩm|mã sản phẩm|\bid)\s*:?\s*(\d{3,20})/i;

/** Contract D (E50): the products the page shows with their commission (read only). */
export function affiliateRates(doc: Document): CurrentRow[] {
  const out: CurrentRow[] = [];
  for (const row of campaignRows(doc)) {
    const id = ROW_ID.exec((row.textContent ?? "").replace(/\s+/g, " "))?.[1];
    const rate = rateOf(row);
    if (id && rate && rate.pct >= 0 && rate.pct <= 100 && !out.some((o) => o.item_id === id)) out.push({ item_id: id, commission_pct: rate.pct });
  }
  return out;
}

function filterBox(env: Env): HTMLInputElement | null {
  const boxes = Array.from(env.doc.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"],input[type="search"]')).filter(
    (i) => !i.closest('[role="dialog"],[class*="modal"]') && !i.readOnly && /(tìm|tên sản phẩm|id|search|product)/i.test(i.placeholder),
  );
  return boxes.length === 1 ? (boxes[0] as HTMLInputElement) : null;
}

const PAGER_NEXT = [
  '[class*="pagination"] [class*="next"]',
  '[class*="pager"] [class*="next"]',
  '[aria-label*="next" i]',
  '[aria-label*="trang sau" i]',
];

function nextPage(env: Env): HTMLElement | null {
  for (const sel of PAGER_NEXT) {
    const hit = Array.from(env.doc.querySelectorAll<HTMLElement>(sel)).find(
      (el) => !/\bdisabled\b/.test(el.className.toString()) && !(el as HTMLButtonElement).disabled && el.getAttribute("aria-disabled") !== "true" && !el.closest("[hidden]"),
    );
    if (hit) return hit;
  }
  return null;
}

/**
 * The product's row on the page shown; else its id is written into the page's search box (a value
 * write: a page that filters as it is typed shows the row) and the search / pager are highlighted
 * for the person. Never presses them.
 */
async function findCampaignRow(env: Env, id: string, guide: boolean): Promise<{ row: HTMLElement | null; searchable: boolean }> {
  const here = await waitFor(env, () => affiliateRowOf(env.doc, id), 3_000);
  if (here) return { row: here, searchable: true };
  const box = filterBox(env);
  if (box && writeValue(box, id)) {
    const found = await waitFor(env, () => affiliateRowOf(env.doc, id), 4_000);
    if (found) return { row: found, searchable: true };
    if (guide) {
      highlight(box);
      const go = pressableOf(env, AFFILIATE_LABELS.search);
      if (go) highlight(go);
    }
  }
  const next = guide ? nextPage(env) : null;
  if (next) highlight(next);
  return { row: null, searchable: !!box };
}

/** The row's own rate control: marked edit, else the one icon next to the rate. */
function rateEditor(cell: HTMLElement): HTMLElement | null {
  const marked = Array.from(cell.querySelectorAll<HTMLElement>('[aria-label*="edit" i],[aria-label*="chỉnh sửa" i],[title*="chỉnh sửa" i],[title*="edit" i],[class*="edit"]'));
  if (marked.length === 1) return marked[0] as HTMLElement;
  const icons = Array.from(cell.querySelectorAll("svg")).map((svg) => svg.parentElement).filter((el): el is HTMLElement => !!el && el !== cell);
  return icons.length === 1 ? (icons[0] as HTMLElement) : null;
}

/** The dialog / popover with a text box that opened for the rate. */
function rateBox(env: Env): HTMLInputElement | null {
  const holders = Array.from(env.doc.querySelectorAll<HTMLElement>('[role="dialog"],[class*="modal"],[class*="popover"],[class*="popper"]')).filter(
    (d) => !d.hidden && !d.closest("[hidden]") && textBoxesIn(d).length > 0,
  );
  const inner = holders.filter((h) => !holders.some((o) => o !== h && h.contains(o)));
  return inner.length === 1 ? (textBoxesIn(inner[0]!)[0] ?? null) : null;
}

export async function fillAffiliate(env: Env, a: AffiliatePayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  // Shopee's notice over the page: the person closes it (its close is highlighted by the runner)
  const notices = noticeDialogs(env);
  if (notices.length > 0) {
    const gone = () => noticeDialogs(env).length === 0;
    env.log?.wrote({ key: "notice", el: env.doc.body, want: "đã đóng", seen: () => (gone() ? "đã đóng" : "thông báo vẫn mở"), ok: gone });
    add(noticeStep(noticeTitle(notices[0]!)), false, { keys: ["notice"], guide: true });
  }
  const current = affiliateRates(env.doc);
  const rows: HTMLElement[] = [];
  const missing: string[] = [];
  let searchable = false;
  for (const id of a.productIds) {
    const found = await findCampaignRow(env, id, true);
    searchable = searchable || found.searchable;
    if (found.row) rows.push(found.row);
    else missing.push(id);
  }
  for (const r of affiliateRates(env.doc)) if (!current.some((c) => c.item_id === r.item_id)) current.push(r);
  // ✓ once the page shows a row for every product (after the person's search / page change too)
  const shown = () => a.productIds.filter((id) => !!affiliateRowOf(env.doc, id)).length;
  env.log?.wrote({ key: "product_rows", el: env.doc.body, want: `${a.productIds.length} dòng`, seen: () => `${shown()}/${a.productIds.length} dòng`, ok: () => shown() === a.productIds.length });
  if (missing.length === 0) add(`Tìm sản phẩm: ${rows.length}/${a.productIds.length}`, true, { keys: ["product_rows"] });
  else
    add(`Tìm ID ${missing.join(", ")} (ô tìm kiếm rồi bấm «Tìm», hoặc chuyển trang)`, false, {
      keys: ["product_rows"],
      guide: true,
      ...(searchable ? {} : { note: AFFILIATE_NO_FILTER }),
    });
  const before = rows.length === 1 ? rateOf(rows[0]!) : null;
  if (before) env.log?.captureBefore("commission_pct", String(before.pct));
  const pct = String(a.commissionPct);
  const label = `Tỉ lệ hoa hồng: ${a.commissionPct}%`;
  const open = rateBox(env);
  if (open) {
    add(label, writeBox(keyed(env, "commission_pct"), open, pct), { keys: ["commission_pct"] });
  } else {
    let todo: string;
    const editor = a.productIds.length === 1 && before ? rateEditor(before.cell) : null;
    if (editor) {
      highlight(editor);
      todo = `Bấm «Chỉnh sửa» ở tỉ lệ của dòng ID ${a.productIds[0]}; Juli điền ${a.commissionPct}%`;
    } else {
      for (const r of rows) {
        const check = r.querySelector<HTMLElement>('input[type="checkbox"],[role="checkbox"]');
        if (check) highlight(check);
      }
      const bulk = pressableOf(env, AFFILIATE_LABELS.bulk);
      if (bulk) highlight(bulk);
      todo = `Tick dòng ID ${a.productIds.join(", ")}, bấm «Chỉnh sửa hàng loạt» › «Chỉnh sửa tỉ lệ hoa hồng»; Juli điền ${a.commissionPct}%`;
    }
    env.log?.later({
      key: "commission_pct",
      write: () => {
        const box = rateBox(env);
        if (!box) return false;
        // the rate the page shows is the before value (a row drawn only after the notice closed)
        const row = a.productIds.length === 1 ? affiliateRowOf(env.doc, a.productIds[0]!) : null;
        const shown = row ? rateOf(row) : null;
        if (shown) env.log?.captureBefore("commission_pct", String(shown.pct));
        return writeBox(keyed(env, "commission_pct"), box, pct) || true;
      },
    });
    add(todo, false, { keys: ["commission_pct"], guide: true });
  }
  return {
    steps,
    todo: [GUIDED_TODO, "Kiểm tra tỉ lệ trong hộp thoại, rồi bấm Lưu / Lưu lại của Shopee."],
    notes: [NEVER_CLICKS],
    ...(current.length > 0 ? { current } : {}),
  };
}

/**
 * F3.2 (contract C) on the open campaign: read the rates the page shows for each product (its id
 * written into the page's search box when the row is not shown, a value write) and report captured.
 * 0.3.28: never presses the search or the pager; a product on another page is not read (✗, note).
 */
export async function readAffiliate(env: Env, job: FillJob): Promise<FillOutcome> {
  const ids = job.payload.kind === "readback" ? (job.payload.readback.target.productIds ?? []) : [];
  const current = affiliateRates(env.doc);
  const missing: string[] = [];
  for (const id of ids) {
    const found = await findCampaignRow(env, id, false);
    if (!found.row) missing.push(id);
    for (const r of affiliateRates(env.doc)) if (!current.some((c) => c.item_id === r.item_id)) current.push(r);
  }
  const read = ids.length > 0 && missing.length === 0;
  return {
    steps: [{ label: `Đọc lại hoa hồng: ${ids.length - missing.length}/${ids.length}`, ok: read, ...(read ? {} : { note: `${AFFILIATE_NO_ROW(missing)} — ${AFFILIATE_NOT_SHOWN}` }) }],
    todo: [],
    notes: ["Juli chỉ đọc trang này."],
    ...(current.length > 0 ? { current } : {}),
    report: read ? ("captured" as const) : ("not_found" as const),
  };
}
