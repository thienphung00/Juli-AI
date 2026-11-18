// The page fillers of a fill job: voucher form, ads edit popups, affiliate bulk commission edit.
// Each types / chooses / ticks what the approved card holds, one labelled field at a time, and
// returns a checklist. None presses Shopee's Lưu / Lưu lại / Xác nhận / Gửi / Cập nhật: the person
// does (controls.press refuses those texts). Labels are the visible Vietnamese ones recorded on
// ORY's Seller Centre (fasttrack/contracts/p97-recon-2026-11-09.md).

import {
  chooseRadio,
  type PickResult,
  writeBox,
  chooseSelect,
  ensureCount,
  type Env,
  findDialog,
  findEditPencil,
  findPressable,
  findRow,
  holdsId,
  pickProducts,
  press,
  setDate,
  setRowText,
  setSwitch,
  textBoxesIn,
} from "./controls";
import type { AdsPayload, AffiliatePayload, ComboPayload, VoucherPayload } from "./job-types";
import { normalizeLabel } from "../../../core/fill/locate";
import { keyed } from "../../../core/fill/log";
import { writeValue } from "../../../core/fill/write";

export type { FillOutcome, Step } from "../../../core/fill/form";
import type { FillOutcome, Step } from "../../../core/fill/form";

const dong = (n: number) => `${n.toLocaleString("vi-VN")} ₫`;

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

/** The field keys of a fill (the job report's `before_values` and `fields` use them). */
export const PERIOD_KEYS = ["starts_at", "ends_at"];
export const PERIOD_NOTE = "Chọn tay thời gian theo thẻ — Shopee đang để mặc định là bây giờ.";

type Add = (label: string, ok: boolean, opts?: { note?: string; keys?: string[] }) => void;

function stepper(steps: Step[]): Add {
  return (label, ok, opts = {}) =>
    steps.push({ label, ok, ...(opts.note && !ok ? { note: opts.note } : {}), ...(opts.keys ? { keys: opts.keys } : {}) });
}

function period(env: Env, add: Add, label: string, startsAt: string, endsAt: string): void {
  const start = setDate(keyed(env, "starts_at"), label, startsAt, 0);
  const end = setDate(keyed(env, "ends_at"), label, endsAt, 1);
  add(`Thời gian: ${startsAt} → ${endsAt}`, start && end, { note: PERIOD_NOTE, keys: PERIOD_KEYS });
}

function picked(add: Add, p: PickResult, total: number): void {
  add(`Sản phẩm: ${p.ticked.length}/${total} đã tick`, p.missing.length === 0, { keys: ["product_ids"], ...(p.reason ? { note: p.reason } : {}) });
}

export async function fillVoucher(env: Env, v: VoucherPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = stepper(steps);
  const L = VOUCHER_LABELS;
  const k = (key: string) => keyed(env, key);
  add(`Tên chương trình: ${v.name}`, setRowText(k("name"), L.name, v.name), { keys: ["name"] });
  add(`Mã voucher: …${v.codeSuffix}`, setRowText(k("code_suffix"), L.code, v.codeSuffix), { keys: ["code_suffix"] });
  period(env, add, L.period, v.startsAt, v.endsAt);
  add("Loại voucher: Khuyến Mãi", await chooseRadio(k("voucher_type"), L.type, "Khuyến Mãi"), { keys: ["voucher_type"] });
  // gone from the live page: off when drawn, otherwise not a step at all
  if (findRow(env.doc, L.smart)) add("Mã giảm giá thông minh: tắt", await setSwitch(k("smart"), L.smart, false), { keys: ["smart"] });
  if (v.discount.type === "amount") {
    const kind = await chooseSelect(k("discount_type"), L.discount, "Theo số tiền");
    add(`Giảm ${dong(v.discount.value)}`, kind && setRowText(k("discount"), L.discount, String(v.discount.value)), {
      keys: ["discount_type", "discount"],
    });
  } else {
    const kind = await chooseSelect(k("discount_type"), L.discount, "Theo phần trăm");
    add(`Giảm ${v.discount.value}%`, kind && setRowText(k("discount"), L.discount, String(v.discount.value)), {
      keys: ["discount_type", "discount"],
    });
    if (v.discount.max.mode === "limited") {
      const radio = await chooseRadio(k("max_mode"), L.max, "Giới hạn");
      add(`Giảm tối đa ${dong(v.discount.max.value)}`, radio && setRowText(k("max_value"), L.max, String(v.discount.max.value)), {
        keys: ["max_mode", "max_value"],
      });
    } else {
      add("Giảm tối đa: không giới hạn", await chooseRadio(k("max_mode"), L.max, "Không giới hạn"), { keys: ["max_mode"] });
    }
  }
  add(`Đơn tối thiểu ${dong(v.minSpend)}`, setRowText(k("min_spend"), L.minSpend, String(v.minSpend)), { keys: ["min_spend"] });
  add(`Tổng lượt dùng ${v.usageTotal}`, setRowText(k("usage_total"), L.usageTotal, String(v.usageTotal)), { keys: ["usage_total"] });
  add(`Mỗi người mua ${v.perBuyer} lượt`, setRowText(k("per_buyer"), L.perBuyer, String(v.perBuyer)), { keys: ["per_buyer"] });
  add(`Hiển thị: ${DISPLAY_OPTION[v.display]}`, await chooseRadio(k("display"), L.display, DISPLAY_OPTION[v.display]), { keys: ["display"] });
  const todo: string[] = [];
  if (v.productIds.length > 0) {
    picked(add, await pickProducts(k("product_ids"), "Thêm sản phẩm", v.productIds), v.productIds.length);
    todo.push("Bấm Xác nhận trong hộp chọn sản phẩm.");
  }
  todo.push("Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo voucher.");
  return { steps, todo, notes: ["Juli không bấm Xác nhận thay bạn."], periodKeys: PERIOD_KEYS };
}

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
  add(`Loại combo: ${COMBO_TYPE_OPTION[c.discountType]}`, await chooseRadio(k("discount_type"), L.type, COMBO_TYPE_OPTION[c.discountType]), {
    keys: ["discount_type"],
  });
  add(`Tên combo: ${c.name}`, setRowText(k("name"), L.name, c.name), { keys: ["name"] });
  period(env, add, L.period, c.startsAt, c.endsAt);
  const enough = await ensureCount(env, L.addTier, () => tierRows(env.doc).length, c.tiers.length);
  const rows = tierRows(env.doc);
  for (const [i, t] of c.tiers.entries()) {
    const row = rows[i];
    const keys = [`tier${i + 1}_qty`, `tier${i + 1}_value`];
    const ok = (enough || rows.length >= c.tiers.length) && !!row && writeBox(k(keys[0]!), row[0]!, String(t.qty)) && writeBox(k(keys[1]!), row[1]!, String(t.value));
    add(COMBO_TIER_TEXT[c.discountType](t.qty, t.value), ok, { keys, note: row ? undefined : "Không thấy dòng «Mua … sản phẩm» của mức này" });
  }
  if (c.purchaseLimit !== undefined) {
    add(`Giới hạn đặt hàng: ${c.purchaseLimit}`, setRowText(k("purchase_limit"), L.limit, String(c.purchaseLimit)), { keys: ["purchase_limit"] });
  }
  picked(add, await pickProducts(k("product_ids"), L.products, c.productIds), c.productIds.length);
  return {
    steps,
    todo: ["Bấm Xác nhận trong hộp chọn sản phẩm.", "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo combo."],
    notes: ["Juli không bấm Xác nhận thay bạn."],
    periodKeys: PERIOD_KEYS,
  };
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

async function openDialog(env: Env, card: string, heading: string): Promise<HTMLElement | null> {
  const existing = findDialog(env, heading);
  if (existing) return existing;
  const pencil = findEditPencil(env, card);
  if (!pencil || !press(pencil)) return null;
  const until = env.now() + 4_000;
  for (;;) {
    const d = findDialog(env, heading);
    if (d) return d;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

export async function fillAds(env: Env, a: AdsPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const notes: string[] = [];
  const todo: string[] = [];
  if (a.budget) {
    const dialog = await openDialog(env, ADS_LABELS.budgetCard, ADS_LABELS.budgetDialog);
    if (!dialog) {
      steps.push({ label: "Mở cửa sổ Chỉnh sửa ngân sách", ok: false, note: "Không thấy nút bút chì của ngân sách." });
    } else if (a.budget.mode === "unlimited") {
      steps.push({
        label: "Ngân sách: Không giới hạn",
        ok: await chooseRadio(keyed(env, "budget_mode"), ADS_LABELS.unlimited, ADS_LABELS.unlimited, dialog),
        keys: ["budget_mode"],
      });
    } else {
      const radio = await chooseRadio(keyed(env, "budget_mode"), ADS_LABELS.daily, ADS_LABELS.daily, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeBox(keyed(env, "daily_budget"), typed, String(a.budget.value));
      steps.push({ label: `Ngân sách hàng ngày: ${dong(a.budget.value)}`, ok, keys: ["budget_mode", "daily_budget"] });
    }
    todo.push("Bấm Xác nhận trong cửa sổ ngân sách của Shopee.");
    if (a.roas) notes.push("Mục tiêu ROAS: làm ở lần mở trang kế tiếp (mỗi lần chỉ một cửa sổ).");
  } else if (a.roas) {
    const dialog = await openDialog(env, ADS_LABELS.roasCard, ADS_LABELS.roasDialog);
    if (!dialog) {
      steps.push({ label: "Mở cửa sổ Mục tiêu ROAS", ok: false, note: "Không thấy nút bút chì của ROAS." });
    } else {
      const radio = await chooseRadio(keyed(env, "roas_mode"), ADS_LABELS.custom, ADS_LABELS.custom, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeBox(keyed(env, "roas_target"), typed, String(a.roas.value));
      steps.push({ label: `Mục tiêu ROAS: ${a.roas.value}`, ok, keys: ["roas_mode", "roas_target"] });
    }
    if (a.roas.value > ROAS_HINT_MAX) notes.push(`Shopee gợi ý ROAS ≤ ${ROAS_HINT_MAX}; giá trị này cao hơn.`);
    notes.push("Đổi ROAS từ 2 lần trong một tuần sẽ mất hỗ trợ hiệu quả của tuần đó.");
    todo.push("Bấm Xác nhận trong cửa sổ ROAS của Shopee.");
  }
  return { steps, todo, notes };
}

// -- affiliate: open campaign, bulk commission ------------------------------------------

export const AFFILIATE_LABELS = {
  bulk: "Chỉnh sửa hàng loạt",
  commission: "Chỉnh sửa tỉ lệ hoa hồng",
} as const;

function filterBox(env: Env): HTMLInputElement | null {
  const boxes = Array.from(env.doc.querySelectorAll<HTMLInputElement>('input:not([type]),input[type="text"],input[type="search"]')).filter(
    (i) => !i.closest('[role="dialog"]') && /(tìm|tên sản phẩm|id)/i.test(i.placeholder),
  );
  return boxes.length === 1 ? (boxes[0] as HTMLInputElement) : null;
}

export const AFFILIATE_NO_FILTER = "Không thấy ô tìm sản phẩm theo tên / ID trên trang Chiến dịch mở rộng";

export async function fillAffiliate(env: Env, a: AffiliatePayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const ticked: string[] = [];
  const box = await waitFor(env, () => filterBox(env));
  for (const id of a.productIds) {
    // a search box, not a field of the card: typed but not recorded
    if (!box || !writeValue(box, id)) continue;
    const go = findPressable(env, "Tìm kiếm") ?? findPressable(env, "Tìm");
    if (go) press(go);
    const until = env.now() + 4_000;
    let done = false;
    while (!done && env.now() < until) {
      const rows = Array.from(env.doc.querySelectorAll<HTMLElement>("tr,[role='row'],li")).filter(
        (r) => holdsId(r, id) && r.querySelector('input[type="checkbox"],[role="checkbox"]'),
      );
      const inner = rows.filter((h) => !rows.some((o) => o !== h && h.contains(o)));
      if (inner.length === 1) {
        const check = (inner[0] as HTMLElement).querySelector<HTMLElement>('input[type="checkbox"],[role="checkbox"]')!;
        const on = () => (check.matches("input") ? (check as HTMLInputElement).checked : check.getAttribute("aria-checked") === "true");
        if (on() || press(check)) {
          ticked.push(id);
          done = true;
        } else break;
      } else await env.sleep(150);
    }
  }
  const notTicked = a.productIds.filter((i) => !ticked.includes(i));
  steps.push({
    label: `Chọn sản phẩm: ${ticked.length}/${a.productIds.length}`,
    ok: notTicked.length === 0,
    ...(notTicked.length > 0 ? { note: box ? `Không thấy dòng của ID: ${notTicked.join(", ")}` : AFFILIATE_NO_FILTER } : {}),
  });
  let dialogOk = false;
  let why = "";
  if (ticked.length === a.productIds.length) {
    const bulk = findPressable(env, AFFILIATE_LABELS.bulk);
    if (bulk && press(bulk)) {
      const item = await waitPressable(env, AFFILIATE_LABELS.commission);
      if (item && press(item)) {
        const dialog = await waitDialog(env, AFFILIATE_LABELS.commission);
        const field = dialog ? textBoxesIn(dialog)[0] : undefined;
        dialogOk = !!field && writeBox(keyed(env, "commission_pct"), field, String(a.commissionPct));
        if (!dialogOk) why = "Không thấy ô tỉ lệ trong hộp thoại";
      } else why = "Không thấy mục «Chỉnh sửa tỉ lệ hoa hồng»";
    } else why = "Không thấy nút «Chỉnh sửa hàng loạt»";
  } else why = "Chưa chọn được sản phẩm nên Juli không mở hộp sửa hoa hồng";
  steps.push({ label: `Tỉ lệ hoa hồng: ${a.commissionPct}%`, ok: dialogOk, keys: ["commission_pct"], ...(dialogOk ? {} : { note: why }) });
  return {
    steps,
    todo: ["Kiểm tra tỉ lệ trong hộp thoại, rồi bấm Lưu lại của Shopee."],
    notes: ["Juli không bấm Lưu lại thay bạn."],
  };
}

async function waitFor<T>(env: Env, find: () => T | null | undefined, ms = 4_000): Promise<T | null> {
  const until = env.now() + ms;
  for (;;) {
    const found = find();
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

async function waitPressable(env: Env, text: string): Promise<HTMLElement | null> {
  const until = env.now() + 3_000;
  for (;;) {
    const found = findPressable(env, text);
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}

async function waitDialog(env: Env, heading: string): Promise<HTMLElement | null> {
  const until = env.now() + 3_000;
  for (;;) {
    const found = findDialog(env, heading);
    if (found) return found;
    if (env.now() >= until) return null;
    await env.sleep(150);
  }
}
