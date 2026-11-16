// The two TikTok forms the Connector fills: the regular coupon (voucher) and the bundle Deal.
// Each types / chooses what the approved card holds, one labelled field at a time, and returns a
// checklist. None presses "Agree and publish" / "Đồng ý và đăng": the seller does. Field labels are
// the EN wording recorded on the sandbox Seller Center (p101-w5-seller-center-recon.md) plus the
// VI wording; the VI strings are UNVERIFIED guesses until the first VI-language recon (the match
// is by label OR ARIA name, so a missing VI string costs a "not found" step, never a wrong fill).

import type { Env, FillOutcome, Step } from "../../core/fill/form";
import { mark, nameBox, type Labels, setDateTime, setOption, setRowText, setSelect, waitFor } from "./controls";
import { writeValue } from "../../core/fill/write";
import type { BundlePayload, FillJob, VoucherPayload } from "./job-types";
import { shopOnPage, sameShop } from "./page";

const dong = (n: number) => `${n.toLocaleString("vi-VN")} ₫`;

const L = {
  name: ["Coupon name", "Promotion name", "Tên phiếu giảm giá", "Tên mã giảm giá", "Tên chương trình khuyến mãi", "Tên khuyến mãi"],
  start: ["Start time", "Thời gian bắt đầu", "Bắt đầu"],
  end: ["End time", "Thời gian kết thúc", "Kết thúc"],
  channel: ["Display channel", "Kênh hiển thị"],
  channelAll: ["All channels", "Tất cả các kênh", "Tất cả kênh"],
  channelShopping: ["Shopping Center", "Trung tâm mua sắm"],
  validity: ["Validity", "Validity period", "Thời hạn hiệu lực", "Thời hạn sử dụng"],
  validityDays: ["Number of days after claim", "Số ngày sau khi nhận"],
  validityRange: ["Specific date range", "Khoảng thời gian cụ thể"],
  type: ["Coupon type", "Loại phiếu giảm giá", "Loại mã giảm giá"],
  typeAmount: ["Amount off", "Giảm số tiền", "Giảm theo số tiền"],
  typePercent: ["Percentage off", "Giảm phần trăm", "Giảm theo phần trăm"],
  discount: ["Discount amount", "Discount percentage", "Discount", "Số tiền giảm", "Phần trăm giảm", "Mức giảm"],
  minSpend: ["Minimum spend", "Chi tiêu tối thiểu", "Giá trị đơn hàng tối thiểu"],
  minSet: ["Set a value", "Đặt giá trị", "Thiết lập giá trị"],
  minNone: ["No minimum spend", "Không có chi tiêu tối thiểu", "Không yêu cầu chi tiêu tối thiểu"],
  usage: ["Usage quantity", "Số lượng sử dụng", "Số lượng"],
  perCustomer: ["Number of claims per customer", "Số lượt nhận mỗi khách hàng", "Số lượt nhận trên mỗi khách hàng"],
  applies: ["Applies to", "Áp dụng cho"],
  allProducts: ["All products", "Tất cả sản phẩm"],
  someProducts: ["Specific products", "Sản phẩm cụ thể"],
  display: ["Display", "Hiển thị"],
  placePdp: ["Product detail page", "Trang chi tiết sản phẩm"],
  placeCart: ["Shopping cart", "Giỏ hàng"],
  discountType: ["Discount type", "Loại giảm giá"],
  discPercent: ["Percentage off", "Giảm phần trăm", "Giảm theo phần trăm"],
  discFixed: ["Fixed price", "Giá cố định"],
  discValue: ["Discount", "Discount value", "Mức giảm", "Giá trị giảm"],
  limit: ["Customer purchase limit", "Giới hạn mua của khách hàng", "Giới hạn mua mỗi khách hàng"],
} as const satisfies Record<string, Labels>;

type Add = (label: string, ok: boolean, note?: string) => void;

function collector(): { steps: Step[]; add: Add } {
  const steps: Step[] = [];
  return { steps, add: (label, ok, note) => steps.push({ label, ok, ...(note ? { note } : {}) }) };
}

/** The name box: by label, else the page's one maxlength=50 box (language-free). */
function setName(env: Env, value: string): boolean {
  if (setRowText(env, L.name, value)) return true;
  const box = nameBox(env.doc);
  return !!box && writeValue(box, value) && box.value === value && mark(box);
}

/** Waits for the form to draw (the name box), then returns. */
async function waitForm(env: Env): Promise<boolean> {
  return !!(await waitFor(env, () => (nameBox(env.doc) ?? undefined) || (env.doc.querySelector("form,[role='form'],main input") ? true : undefined), 25_000));
}

export async function fillVoucher(env: Env, v: VoucherPayload): Promise<FillOutcome> {
  const { steps, add } = collector();
  await waitForm(env);
  add(`Tên phiếu: ${v.name}`, setName(env, v.name));
  add(`Bắt đầu: ${v.startsAt} (GMT+7)`, setDateTime(env, L.start, v.startsAt));
  add(`Kết thúc: ${v.endsAt} (GMT+7)`, setDateTime(env, L.end, v.endsAt));
  const channel = v.display === "all" ? L.channelAll : L.channelShopping;
  add(`Kênh hiển thị: ${v.display === "all" ? "Tất cả kênh" : "Shopping Center"}`, await setOption(env, L.channel, channel));
  if (v.validity.mode === "days") {
    const radio = await setOption(env, L.validity, L.validityDays);
    add(`Hiệu lực: ${v.validity.days} ngày sau khi nhận`, radio && setRowText(env, L.validity, String(v.validity.days)));
  } else add("Hiệu lực: khoảng thời gian cụ thể", await setOption(env, L.validity, L.validityRange));
  const kind = await setOption(env, L.type, v.discount.type === "amount" ? L.typeAmount : L.typePercent);
  add(v.discount.type === "amount" ? `Giảm ${dong(v.discount.value)}` : `Giảm ${v.discount.value}%`, kind && setRowText(env, L.discount, String(v.discount.value)));
  if (v.minSpend > 0) add(`Chi tiêu tối thiểu ${dong(v.minSpend)}`, (await setOption(env, L.minSpend, L.minSet)) && setRowText(env, L.minSpend, String(v.minSpend)));
  else add("Không có chi tiêu tối thiểu", await setOption(env, L.minSpend, L.minNone));
  add(`Số lượng sử dụng ${v.usageTotal}`, setRowText(env, L.usage, String(v.usageTotal)));
  add(`Mỗi khách nhận tối đa ${v.perCustomer} lần`, setRowText(env, L.perCustomer, String(v.perCustomer)));
  const todo: string[] = [];
  if (v.productIds.length === 0) add("Áp dụng cho: tất cả sản phẩm", await setOption(env, L.applies, L.allProducts));
  else {
    add("Áp dụng cho: sản phẩm cụ thể", await setOption(env, L.applies, L.someProducts));
    // TODO(recon): the voucher's product picker modal is not mapped; the seller adds the products.
    todo.push(`Chọn ${v.productIds.length} sản phẩm bằng tay (Juli chưa điền được hộp chọn sản phẩm): ${v.productIds.join(", ")}.`);
  }
  todo.push("Kiểm tra lại các ô được tô hồng, rồi bấm “Đồng ý và đăng” (Agree and publish) của TikTok.");
  return { steps, todo, notes: ["Juli không bấm “Đồng ý và đăng” thay bạn."] };
}

export async function fillBundle(env: Env, b: BundlePayload): Promise<FillOutcome> {
  const { steps, add } = collector();
  await waitForm(env);
  add(`Tên chương trình: ${b.name}`, setName(env, b.name));
  add(`Bắt đầu: ${b.startsAt} (GMT+7)`, setDateTime(env, L.start, b.startsAt));
  add(`Kết thúc: ${b.endsAt} (GMT+7)`, setDateTime(env, L.end, b.endsAt));
  const pdp = await setOption(env, L.display, L.placePdp, b.display.includes("product_page"));
  const cart = await setOption(env, L.display, L.placeCart, b.display.includes("cart"));
  add(`Hiển thị: ${b.display.map((d) => (d === "cart" ? "Giỏ hàng" : "Trang chi tiết sản phẩm")).join(" + ")}`, pdp && cart);
  const type = await setOption(env, L.discountType, b.discount.type === "percent" ? L.discPercent : L.discFixed);
  add(b.discount.type === "percent" ? `Giảm ${b.discount.value}%` : `Giá cố định ${dong(b.discount.value)}`, type && setRowText(env, L.discValue, String(b.discount.value)));
  if (b.purchaseLimit !== undefined) {
    const ok = setSelect(env, L.limit, [String(b.purchaseLimit)]);
    add(`Giới hạn mua: ${b.purchaseLimit}`, ok, ok ? undefined : "Chọn giới hạn mua bằng tay.");
  }
  // TODO(recon): the bundle's product picker modal (2-3 products: Create new / Select existing) is not mapped.
  const todo = [
    b.productIds.length > 0 ? `Chọn 2–3 sản phẩm của combo bằng tay (Juli chưa điền được hộp chọn sản phẩm): ${b.productIds.join(", ")}.` : "Chọn 2–3 sản phẩm của combo bằng tay.",
    "Kiểm tra lại các ô được tô hồng, rồi bấm “Đồng ý và đăng” (Agree and publish) của TikTok.",
  ];
  return { steps, todo, notes: ["Juli không bấm “Đồng ý và đăng” thay bạn."] };
}

/**
 * The shop check before anything is typed: when Juli names the shop (`job.shopName`), the page's
 * header must show the same shop. A header that does not show one within 10 s stops the job too.
 */
export async function shopCheck(env: Env, job: FillJob): Promise<FillOutcome | null> {
  if (!job.shopName) return null;
  const seen = await waitFor(env, () => shopOnPage(env.doc), 10_000);
  const ok = !!seen && sameShop(seen, job.shopName);
  if (ok) return null;
  return {
    steps: [{ label: "Đúng shop TikTok", ok: false, note: seen ? `Trang đang đăng nhập shop “${seen}”, không phải shop đã kết nối.` : "Không thấy tên shop trên trang." }],
    todo: ["Đăng nhập đúng shop TikTok đã kết nối với Juli rồi mở lại từ Juli."],
    notes: ["Juli không điền gì vào trang này."],
  };
}
