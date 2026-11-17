// A TikTok fill job as Juli serves it, validated field by field (the same rules as the Shopee
// pack's): the page only ever sees plain, bounded values, and a job whose address is not the
// action's create page is dropped. Times are GMT+7 `YYYY-MM-DD HH:mm`.

import type { CoreJob, JobReply as CoreJobReply } from "../../core/fill/form";
import { FILL_JOB_ID_PATTERN } from "../../core/config";
import { FILL_JOB_PAGES, SELLER_CENTER_ORIGIN } from "./config";

export type JobKind = "voucher" | "bundle";
export type JobStatus = "queued" | "opened" | "filled" | "saved" | "captured" | "failed" | "cancelled";

export const TIME_FORMAT = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):[0-5]\d$/;
export const MAX_NAME = 50;

export interface VoucherPayload {
  name: string;
  startsAt: string;
  endsAt: string;
  display: "all" | "shopping_center";
  validity: { mode: "days"; days: number } | { mode: "range" };
  discount: { type: "amount" | "percent"; value: number };
  /** 0 = "No minimum spend". */
  minSpend: number;
  usageTotal: number;
  perCustomer: number;
  /** Empty = "All products"; else "Specific products" (the picker is not mapped: the seller adds them). */
  productIds: string[];
}

export interface BundlePayload {
  name: string;
  startsAt: string;
  endsAt: string;
  display: ("product_page" | "cart")[];
  discount: { type: "percent" | "fixed"; value: number };
  purchaseLimit?: number;
  /** The product picker is not mapped yet: the seller picks the products by hand. */
  productIds: string[];
}

export type JobPayload = { kind: "voucher"; voucher: VoucherPayload } | { kind: "bundle"; bundle: BundlePayload };

export interface FillJob extends CoreJob {
  cardId: string;
  version: number;
  kind: JobKind;
  status: JobStatus;
  /** The shop name Juli expects the Seller Center header to show (when it knows one). */
  shopName: string | null;
  payload: JobPayload;
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, max: number): string | undefined => (typeof v === "string" && v.length > 0 && v.length <= max ? v : undefined);
const int = (v: unknown, min: number, max: number): number | undefined =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max ? v : undefined;
const ids = (v: unknown): string[] | undefined => {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.length > 100) return undefined;
  const out = v.filter((x): x is string => typeof x === "string" && /^\d{1,20}$/.test(x));
  return out.length === v.length ? out : undefined;
};

function window2(raw: Record<string, unknown>): { startsAt: string; endsAt: string } | null {
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  if (!startsAt || !endsAt || !TIME_FORMAT.test(startsAt) || !TIME_FORMAT.test(endsAt) || endsAt <= startsAt) return null;
  return { startsAt, endsAt };
}

function voucher(raw: Record<string, unknown>): VoucherPayload | null {
  const name = str(raw.name, MAX_NAME);
  const w = window2(raw);
  const display = raw.display === "all" || raw.display === "shopping_center" ? raw.display : undefined;
  const minSpend = int(raw.min_spend, 0, 1_000_000_000);
  const usageTotal = int(raw.usage_total, 1, 9_999_999);
  const perCustomer = int(raw.per_customer, 1, 1_000);
  const productIds = ids(raw.product_ids);
  const d = raw.discount;
  const v = raw.validity;
  if (!name || !w || !display || minSpend === undefined || !usageTotal || !perCustomer || !productIds || !isRecord(d) || !isRecord(v)) return null;
  let validity: VoucherPayload["validity"];
  if (v.mode === "days") {
    const days = int(v.days, 1, 365);
    if (!days) return null;
    validity = { mode: "days", days };
  } else if (v.mode === "range") validity = { mode: "range" };
  else return null;
  let discount: VoucherPayload["discount"];
  if (d.type === "amount") {
    const value = int(d.value, 1, 1_000_000_000);
    if (!value) return null;
    discount = { type: "amount", value };
  } else if (d.type === "percent") {
    const value = int(d.value, 1, 99);
    if (!value) return null;
    discount = { type: "percent", value };
  } else return null;
  return { name, ...w, display, validity, discount, minSpend, usageTotal, perCustomer, productIds };
}

function bundle(raw: Record<string, unknown>): BundlePayload | null {
  const name = str(raw.name, MAX_NAME);
  const w = window2(raw);
  const productIds = ids(raw.product_ids);
  const d = raw.discount;
  const places = raw.display;
  if (!name || !w || !productIds || !isRecord(d) || !Array.isArray(places) || places.length < 1 || places.length > 2) return null;
  const display = places.filter((p): p is "product_page" | "cart" => p === "product_page" || p === "cart");
  if (display.length !== places.length || new Set(display).size !== display.length) return null;
  let discount: BundlePayload["discount"];
  if (d.type === "percent") {
    const value = int(d.value, 1, 99);
    if (!value) return null;
    discount = { type: "percent", value };
  } else if (d.type === "fixed") {
    const value = int(d.value, 1, 1_000_000_000);
    if (!value) return null;
    discount = { type: "fixed", value };
  } else return null;
  const out: BundlePayload = { name, ...w, display, discount, productIds };
  if (raw.purchase_limit !== undefined) {
    const limit = int(raw.purchase_limit, 1, 999_999);
    if (!limit) return null;
    out.purchaseLimit = limit;
  }
  return out;
}

/** One job of the server's answer, or null when anything is off (including a page that is not the action's form). */
export function parseFillJob(raw: unknown): FillJob | null {
  if (!isRecord(raw)) return null;
  const id = str(raw.id, 36);
  const kind = raw.kind;
  const status = str(raw.status, 12) as JobStatus | undefined;
  const openPath = str(raw.open_path, 200);
  const p = raw.payload;
  if (!id || !FILL_JOB_ID_PATTERN.test(id) || !status || !openPath || !isRecord(p)) return null;
  if (kind !== "voucher" && kind !== "bundle") return null;
  if (!openPath.startsWith("/") || openPath.startsWith("//")) return null;
  let path: string;
  let search: string;
  try {
    const url = new URL(openPath, SELLER_CENTER_ORIGIN);
    path = url.pathname;
    search = url.search;
  } catch {
    return null;
  }
  if (search !== "" || !FILL_JOB_PAGES[kind].test(path)) return null;
  let payload: JobPayload | null = null;
  if (kind === "voucher") {
    const v = voucher(p);
    payload = v ? { kind, voucher: v } : null;
  } else {
    const b = bundle(p);
    payload = b ? { kind, bundle: b } : null;
  }
  if (!payload) return null;
  return {
    id,
    cardId: str(raw.card_id, 36) ?? "",
    code: str(raw.code, 40) ?? "",
    title: str(raw.title, 300) ?? str(raw.code, 40) ?? "",
    version: int(raw.version, 1, 9) ?? 1,
    groupCode: str(raw.group_code, 16) ?? null,
    kind,
    status,
    openPath,
    shopName: str(raw.shop_name, 80) ?? null,
    payload,
  };
}

export type JobReply = CoreJobReply<FillJob>;
