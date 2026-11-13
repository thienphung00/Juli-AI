// The page fillers of a fill job: voucher form, ads edit popups, affiliate bulk commission edit.
// Each types / chooses / ticks what the approved card holds, one labelled field at a time, and
// returns a checklist. None presses Shopee's Lưu / Lưu lại / Xác nhận / Gửi / Cập nhật: the person
// does (controls.press refuses those texts). Labels are the visible Vietnamese ones recorded on
// ORY's Seller Centre (fasttrack/contracts/p97-recon-2026-11-09.md).

import {
  chooseRadio,
  chooseSelect,
  ensureCount,
  type Env,
  findDialog,
  findEditPencil,
  findPressable,
  findRow,
  pickProducts,
  press,
  setDate,
  setRowText,
  setSwitch,
  textBoxesIn,
} from "./controls";
import type { AdsPayload, AffiliatePayload, ComboPayload, VoucherPayload } from "./job-types";
import { normalizeLabel } from "./locate";
import { writeValue } from "./write";

export interface Step {
  /** What the person sees in the checklist (Vietnamese). */
  label: string;
  ok: boolean;
  /** Said when it is not ok, or when the person has something to do. */
  note?: string;
}

export interface FillOutcome {
  steps: Step[];
  /** What the person still does, in order (Vietnamese). */
  todo: string[];
  notes: string[];
}

const dong = (n: number) => `${n.toLocaleString("vi-VN")} ₫`;

export const VOUCHER_LABELS = {
  name: "Tên chương trình giảm giá",
  code: "Mã voucher",
  period: "Thời gian sử dụng mã",
  type: "Loại Voucher",
  smart: "Mã giảm giá thông minh",
  discount: "Loại giảm giá | Mức giảm",
  max: "Mức giảm tối đa",
  minSpend: "Giá trị đơn hàng tối thiểu",
  usageTotal: "Tổng lượt sử dụng tối đa",
  perBuyer: "Lượt sử dụng tối đa/Người mua",
  display: "Thiết lập hiển thị",
  products: "Sản phẩm được áp dụng",
} as const;

const DISPLAY_OPTION = { multi: "Hiển thị nhiều nơi", code: "Chia sẻ thông qua mã", private: "Không công khai" } as const;

export async function fillVoucher(env: Env, v: VoucherPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = (label: string, ok: boolean, note?: string) => steps.push({ label, ok, ...(note ? { note } : {}) });
  const L = VOUCHER_LABELS;
  add(`Tên chương trình: ${v.name}`, setRowText(env, L.name, v.name));
  add(`Mã voucher: …${v.codeSuffix}`, setRowText(env, L.code, v.codeSuffix));
  const start = setDate(env, L.period, v.startsAt, 0);
  const end = setDate(env, L.period, v.endsAt, 1);
  add(`Thời gian: ${v.startsAt} → ${v.endsAt}`, start && end);
  add("Loại voucher: Khuyến Mãi", await chooseRadio(env, L.type, "Khuyến Mãi"));
  add("Mã giảm giá thông minh: tắt", await setSwitch(env, L.smart, false));
  if (v.discount.type === "amount") {
    const kind = await chooseSelect(env, L.discount, "Theo số tiền");
    add(`Giảm ${dong(v.discount.value)}`, kind && setRowText(env, L.discount, String(v.discount.value)));
  } else {
    const kind = await chooseSelect(env, L.discount, "Theo phần trăm");
    add(`Giảm ${v.discount.value}%`, kind && setRowText(env, L.discount, String(v.discount.value)));
    if (v.discount.max.mode === "limited") {
      const radio = await chooseRadio(env, L.max, "Giới hạn");
      add(`Giảm tối đa ${dong(v.discount.max.value)}`, radio && setRowText(env, L.max, String(v.discount.max.value)));
    } else {
      add("Giảm tối đa: không giới hạn", await chooseRadio(env, L.max, "Không giới hạn"));
    }
  }
  add(`Đơn tối thiểu ${dong(v.minSpend)}`, setRowText(env, L.minSpend, String(v.minSpend)));
  add(`Tổng lượt dùng ${v.usageTotal}`, setRowText(env, L.usageTotal, String(v.usageTotal)));
  add(`Mỗi người mua ${v.perBuyer} lượt`, setRowText(env, L.perBuyer, String(v.perBuyer)));
  add(`Hiển thị: ${DISPLAY_OPTION[v.display]}`, await chooseRadio(env, L.display, DISPLAY_OPTION[v.display]));
  const todo: string[] = [];
  if (v.productIds.length > 0) {
    const picked = await pickProducts(env, "Thêm sản phẩm", v.productIds);
    add(
      `Sản phẩm: ${picked.ticked.length}/${v.productIds.length} đã tick`,
      picked.missing.length === 0,
      picked.missing.length ? `Không thấy ID: ${picked.missing.join(", ")}` : undefined,
    );
    todo.push("Bấm Xác nhận trong hộp chọn sản phẩm.");
  }
  todo.push("Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo voucher.");
  return { steps, todo, notes: ["Juli không bấm Xác nhận thay bạn."] };
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

export async function fillCombo(env: Env, c: ComboPayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const add = (label: string, ok: boolean, note?: string) => steps.push({ label, ok, ...(note ? { note } : {}) });
  const L = COMBO_LABELS;
  // the type first: it decides what the tier rows ask for
  add(`Loại combo: ${COMBO_TYPE_OPTION[c.discountType]}`, await chooseRadio(env, L.type, COMBO_TYPE_OPTION[c.discountType]));
  add(`Tên combo: ${c.name}`, setRowText(env, L.name, c.name));
  const start = setDate(env, L.period, c.startsAt, 0);
  const end = setDate(env, L.period, c.endsAt, 1);
  add(`Thời gian: ${c.startsAt} → ${c.endsAt}`, start && end);
  // each tier row holds two boxes: "Mua [N] sản phẩm" and the percent / amount / price
  const boxes = () => {
    const row = findRow(env.doc, L.tiers);
    return row ? textBoxesIn(row).length : 0;
  };
  const enough = await ensureCount(env, L.addTier, () => Math.floor(boxes() / 2), c.tiers.length);
  for (const [i, t] of c.tiers.entries()) {
    const ok = enough && setRowText(env, L.tiers, String(t.qty), i * 2) && setRowText(env, L.tiers, String(t.value), i * 2 + 1);
    add(COMBO_TIER_TEXT[c.discountType](t.qty, t.value), ok);
  }
  if (c.purchaseLimit !== undefined) add(`Giới hạn đặt hàng: ${c.purchaseLimit}`, setRowText(env, L.limit, String(c.purchaseLimit)));
  const picked = await pickProducts(env, L.products, c.productIds);
  add(
    `Sản phẩm: ${picked.ticked.length}/${c.productIds.length} đã tick`,
    picked.missing.length === 0,
    picked.missing.length ? `Không thấy ID: ${picked.missing.join(", ")}` : undefined,
  );
  return {
    steps,
    todo: ["Bấm Xác nhận trong hộp chọn sản phẩm.", "Kiểm tra lại các ô được tô hồng, rồi bấm Xác nhận của Shopee để tạo combo."],
    notes: ["Juli không bấm Xác nhận thay bạn."],
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
      steps.push({ label: "Ngân sách: Không giới hạn", ok: await chooseRadio(env, ADS_LABELS.unlimited, ADS_LABELS.unlimited, dialog) });
    } else {
      const radio = await chooseRadio(env, ADS_LABELS.daily, ADS_LABELS.daily, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeValue(typed, String(a.budget.value)) && typed.value === String(a.budget.value);
      steps.push({ label: `Ngân sách hàng ngày: ${dong(a.budget.value)}`, ok });
    }
    todo.push("Bấm Xác nhận trong cửa sổ ngân sách của Shopee.");
    if (a.roas) notes.push("Mục tiêu ROAS: làm ở lần mở trang kế tiếp (mỗi lần chỉ một cửa sổ).");
  } else if (a.roas) {
    const dialog = await openDialog(env, ADS_LABELS.roasCard, ADS_LABELS.roasDialog);
    if (!dialog) {
      steps.push({ label: "Mở cửa sổ Mục tiêu ROAS", ok: false, note: "Không thấy nút bút chì của ROAS." });
    } else {
      const radio = await chooseRadio(env, ADS_LABELS.custom, ADS_LABELS.custom, dialog);
      const typed = textBoxesIn(dialog)[0];
      const ok = radio && !!typed && writeValue(typed, String(a.roas.value)) && typed.value === String(a.roas.value);
      steps.push({ label: `Mục tiêu ROAS: ${a.roas.value}`, ok });
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

export async function fillAffiliate(env: Env, a: AffiliatePayload): Promise<FillOutcome> {
  const steps: Step[] = [];
  const ticked: string[] = [];
  const box = filterBox(env);
  for (const id of a.productIds) {
    if (!box || !writeValue(box, id)) continue;
    const go = findPressable(env, "Tìm kiếm") ?? findPressable(env, "Tìm");
    if (go) press(go);
    const until = env.now() + 4_000;
    let done = false;
    while (!done && env.now() < until) {
      const rows = Array.from(env.doc.querySelectorAll<HTMLElement>("tr,[role='row'],li")).filter(
        (r) => normalizeLabel(r.textContent ?? "").includes(id) && r.querySelector('input[type="checkbox"],[role="checkbox"]'),
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
  steps.push({
    label: `Chọn sản phẩm: ${ticked.length}/${a.productIds.length}`,
    ok: ticked.length === a.productIds.length,
    ...(ticked.length < a.productIds.length ? { note: `Không tick được: ${a.productIds.filter((i) => !ticked.includes(i)).join(", ")}` } : {}),
  });
  let dialogOk = false;
  if (ticked.length === a.productIds.length) {
    const bulk = findPressable(env, AFFILIATE_LABELS.bulk);
    if (bulk && press(bulk)) {
      const item = await waitPressable(env, AFFILIATE_LABELS.commission);
      if (item && press(item)) {
        const dialog = await waitDialog(env, AFFILIATE_LABELS.commission);
        const field = dialog ? textBoxesIn(dialog)[0] : undefined;
        const value = String(a.commissionPct);
        dialogOk = !!field && writeValue(field, value) && field.value === value;
      }
    }
  }
  steps.push({ label: `Tỉ lệ hoa hồng: ${a.commissionPct}%`, ok: dialogOk });
  return {
    steps,
    todo: ["Kiểm tra tỉ lệ trong hộp thoại, rồi bấm Lưu lại của Shopee."],
    notes: ["Juli không bấm Lưu lại thay bạn."],
  };
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
