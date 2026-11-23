// Seeing that the PERSON saved a created voucher (P97 D85.6): on a fill-job page the hook watches
// the page's own POST answers (the one produced by the person's click on Shopee's Xác nhận) and
// keeps only the new voucher_id. The create endpoint was not recorded (nothing is saved during
// recon), so the path test is a pattern, not a fact; Juli also resolves the id from the voucher
// list reader's next read (service side), so a missed answer costs nothing.

import type { PageAnswer, SaveResult } from "../../../platform";

/** A POST to a marketing voucher create / add / save endpoint. */
export function savedVoucherPath(pathname: string): boolean {
  return /^\/api\/marketing\/.*voucher.*\/(create|add|save)[a-z_]*\/?$/i.test(pathname);
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The new voucher id in a create answer (`{data: {voucher_id}}` or flat), digits only; else null. */
export function voucherIdFrom(body: unknown, depth = 0): string | null {
  if (!isRecord(body) || depth > 3) return null;
  const id = body.voucher_id;
  if ((typeof id === "number" && Number.isSafeInteger(id) && id > 0) || (typeof id === "string" && /^\d{1,20}$/.test(id))) return String(id);
  for (const value of Object.values(body)) {
    const found = voucherIdFrom(value, depth + 1);
    if (found) return found;
  }
  return null;
}

/** A POST to a marketing bundle-deal (Combo Khuyến Mãi) create / add / save endpoint. Like the
 * voucher one, a pattern and not a recorded fact; a missed answer leaves the combo without an id
 * (its read-back stays "executed_no_readback"). */
export function savedBundlePath(pathname: string): boolean {
  return /^\/api\/marketing\/.*bundle.*\/(create|add|save)[a-z_]*\/?$/i.test(pathname);
}

/** The new combo id in a create answer (`bundle_deal_id` or `bundle_id`), digits only; else null. */
export function bundleIdFrom(body: unknown, depth = 0): string | null {
  if (!isRecord(body) || depth > 3) return null;
  for (const id of [body.bundle_deal_id, body.bundle_id]) {
    if ((typeof id === "number" && Number.isSafeInteger(id) && id > 0) || (typeof id === "string" && /^\d{1,20}$/.test(id))) return String(id);
  }
  for (const value of Object.values(body)) {
    const found = bundleIdFrom(value, depth + 1);
    if (found) return found;
  }
  return null;
}

/** a2 K2: a POST to a Chương Trình Của Shop / Deal Sốc create / add / save endpoint (a pattern, not recorded: capture 3 pending). */
export function savedProgrammePath(pathname: string): boolean {
  return /^\/api\/marketing\/.*(discount|add_on_deal|add-on-deal|addon).*\/(create|add|save)[a-z_]*\/?$/i.test(pathname);
}

/** The new programme id in a create answer (`discount_id`, `promotion_id`, `add_on_deal_id`), digits only; else null. */
export function programmeIdFrom(body: unknown, depth = 0): string | null {
  if (!isRecord(body) || depth > 3) return null;
  for (const id of [body.discount_id, body.promotion_id, body.add_on_deal_id]) {
    if ((typeof id === "number" && Number.isSafeInteger(id) && id > 0) || (typeof id === "string" && /^\d{1,20}$/.test(id))) return String(id);
  }
  for (const value of Object.values(body)) {
    const found = programmeIdFrom(value, depth + 1);
    if (found) return found;
  }
  return null;
}

/** The pack's saved signal: the new voucher / combo / programme id in the page's own POST answer to the person's save. */
export function savedSignal(page: PageAnswer): SaveResult | null {
  if (page.method !== "POST") return null;
  const ref = savedVoucherPath(page.pathname)
    ? voucherIdFrom(page.body)
    : savedBundlePath(page.pathname)
      ? bundleIdFrom(page.body)
      : savedProgrammePath(page.pathname)
        ? programmeIdFrom(page.body)
        : null;
  return ref ? { ref } : null;
}
