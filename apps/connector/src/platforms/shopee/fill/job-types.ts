// A fill job as Juli serves it (GET /v1/ingest/fill-jobs), validated field by field: the page
// only ever sees plain, bounded values, and a job whose address is not one of the allowed Seller
// Centre pages for its kind is dropped (nothing is opened, nothing is typed).

import { FILL_JOB_ID_PATTERN, FILL_JOB_PAGES } from "../config";
import { DATE_FORMAT } from "./controls";
import { type FillField, type FillKey } from "./types";

export type JobKind = "title" | "description_first_line" | "voucher" | "ads_edit" | "affiliate_commission" | "combo";
export type JobStatus = "queued" | "opened" | "filled" | "saved" | "captured" | "failed" | "cancelled";

export interface VoucherPayload {
  usecase: 1 | 2;
  name: string;
  codeSuffix: string;
  startsAt: string;
  endsAt: string;
  discount: { type: "amount"; value: number } | { type: "percent"; value: number; max: { mode: "limited"; value: number } | { mode: "unlimited" } };
  minSpend: number;
  usageTotal: number;
  perBuyer: number;
  display: "multi" | "code" | "private";
  productIds: string[];
}

export interface AdsPayload {
  campaignId: string;
  variant: "manual" | "manual-mpd";
  budget?: { mode: "daily"; value: number } | { mode: "unlimited" };
  roas?: { mode: "custom"; value: number } | { mode: "preset"; value: number };
}

export interface AffiliatePayload {
  productIds: string[];
  commissionPct: number;
}

export type ComboType = "pct" | "amount" | "special_price";

export interface ComboPayload {
  name: string;
  startsAt: string;
  endsAt: string;
  discountType: ComboType;
  /** Ascending quantity N; value is a percent, an amount off, or the special price for N. */
  tiers: { qty: number; value: number }[];
  purchaseLimit?: number;
  productIds: string[];
}

export type JobPayload =
  | { kind: "title" | "description_first_line"; fields: FillField[]; itemId: string }
  | { kind: "voucher"; voucher: VoucherPayload }
  | { kind: "ads_edit"; ads: AdsPayload }
  | { kind: "affiliate_commission"; affiliate: AffiliatePayload }
  | { kind: "combo"; combo: ComboPayload };

export interface FillJob {
  id: string;
  cardId: string;
  code: string;
  title: string;
  version: number;
  groupCode: string | null;
  kind: JobKind;
  status: JobStatus;
  /** Path (and query) to open, relative to Seller Centre. */
  openPath: string;
  payload: JobPayload;
}

/** The smallest daily budget Shopee accepts for a product ad (recon 2026-11-09). */
export const MIN_DAILY_BUDGET = 100_000;
export const MAX_PRODUCTS = 100;

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, max: number): string | undefined => (typeof v === "string" && v.length > 0 && v.length <= max ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const int = (v: unknown, min: number, max: number): number | undefined => {
  const n = num(v);
  return n !== undefined && Number.isInteger(n) && n >= min && n <= max ? n : undefined;
};
const ids = (v: unknown): string[] | undefined => {
  if (!Array.isArray(v) || v.length > MAX_PRODUCTS) return undefined;
  const out = v.filter((x): x is string => typeof x === "string" && /^\d{1,20}$/.test(x));
  return out.length === v.length ? out : undefined;
};

function voucher(raw: Record<string, unknown>): VoucherPayload | null {
  const usecase = raw.usecase === 1 ? 1 : raw.usecase === 2 ? 2 : undefined;
  const name = str(raw.name, 100);
  const codeSuffix = str(raw.code_suffix, 5);
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  const minSpend = int(raw.min_spend, 0, 1_000_000_000);
  const usageTotal = int(raw.usage_total, 1, 10_000_000);
  const perBuyer = int(raw.per_buyer, 1, 1_000);
  const productIds = ids(raw.product_ids);
  const display = raw.display === "multi" || raw.display === "code" || raw.display === "private" ? raw.display : undefined;
  const d = raw.discount;
  if (!usecase || !name || !codeSuffix || !startsAt || !endsAt || minSpend === undefined || !usageTotal || !perBuyer || !productIds || !display || !isRecord(d)) return null;
  if (!/^[A-Z0-9]{1,5}$/.test(codeSuffix) || !DATE_FORMAT.test(startsAt) || !DATE_FORMAT.test(endsAt)) return null;
  if (usecase === 2 && productIds.length === 0) return null;
  if (usecase === 1 && productIds.length > 0) return null;
  let discount: VoucherPayload["discount"];
  if (d.type === "amount") {
    const value = int(d.value, 1, 1_000_000_000);
    if (!value) return null;
    discount = { type: "amount", value };
  } else if (d.type === "percent") {
    const value = num(d.value);
    if (value === undefined || value <= 1 || value > 100) return null; // Shopee: "lớn hơn 1%"
    const m = d.max;
    if (!isRecord(m)) return null;
    if (m.mode === "unlimited") discount = { type: "percent", value, max: { mode: "unlimited" } };
    else {
      const cap = int(m.value, 1, 1_000_000_000);
      if (m.mode !== "limited" || !cap) return null;
      discount = { type: "percent", value, max: { mode: "limited", value: cap } };
    }
  } else return null;
  return { usecase, name, codeSuffix, startsAt, endsAt, discount, minSpend, usageTotal, perBuyer, display, productIds };
}

function ads(raw: Record<string, unknown>): AdsPayload | null {
  const campaignId = str(raw.campaign_id, 20);
  const variant = raw.variant === "manual" || raw.variant === "manual-mpd" ? raw.variant : undefined;
  if (!campaignId || !/^\d+$/.test(campaignId) || !variant) return null;
  const out: AdsPayload = { campaignId, variant };
  if (raw.budget !== undefined) {
    const b = raw.budget;
    if (!isRecord(b)) return null;
    if (b.mode === "unlimited") out.budget = { mode: "unlimited" };
    else {
      const value = int(b.value, MIN_DAILY_BUDGET, 100_000_000_000);
      if (b.mode !== "daily" || !value) return null; // under Shopee's minimum: refused here too
      out.budget = { mode: "daily", value };
    }
  }
  if (raw.roas !== undefined) {
    const r = raw.roas;
    const value = isRecord(r) ? num(r.value) : undefined;
    if (!isRecord(r) || (r.mode !== "custom" && r.mode !== "preset") || value === undefined || value <= 0 || value > 100) return null;
    out.roas = { mode: r.mode, value };
  }
  return out.budget || out.roas ? out : null;
}

export const MAX_COMBO_TIERS = 5;
export const MAX_COMBO_NAME = 25;
export const MAX_PURCHASE_LIMIT = 999_999_999;

function combo(raw: Record<string, unknown>): ComboPayload | null {
  const name = str(raw.name, MAX_COMBO_NAME);
  const startsAt = str(raw.starts_at, 16);
  const endsAt = str(raw.ends_at, 16);
  const discountType = raw.discount_type === "pct" || raw.discount_type === "amount" || raw.discount_type === "special_price" ? raw.discount_type : undefined;
  const productIds = ids(raw.product_ids);
  if (!name || !startsAt || !endsAt || !discountType || !productIds || productIds.length === 0) return null;
  if (!DATE_FORMAT.test(startsAt) || !DATE_FORMAT.test(endsAt)) return null;
  const rows = raw.tiers;
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > MAX_COMBO_TIERS) return null;
  const tiers: ComboPayload["tiers"] = [];
  for (const row of rows) {
    if (!isRecord(row)) return null;
    const qty = int(row.qty, 2, 9999);
    const value = int(row.value, 1, discountType === "pct" ? 99 : 1_000_000_000);
    if (!qty || !value || (tiers.length > 0 && qty <= (tiers[tiers.length - 1] as { qty: number }).qty)) return null;
    tiers.push({ qty, value });
  }
  const out: ComboPayload = { name, startsAt, endsAt, discountType, tiers, productIds };
  if (raw.purchase_limit !== undefined) {
    const limit = int(raw.purchase_limit, 1, MAX_PURCHASE_LIMIT);
    if (!limit) return null;
    out.purchaseLimit = limit;
  }
  return out;
}

function addressOk(kind: JobKind, openPath: string, payload: JobPayload): boolean {
  let url: URL;
  try {
    url = new URL(openPath, "https://banhang.shopee.vn");
  } catch {
    return false;
  }
  const path = url.pathname;
  if (kind === "title" || kind === "description_first_line") {
    const m = FILL_JOB_PAGES.product_edit.exec(path);
    return !!m && payload.kind === kind && m[1] === payload.itemId;
  }
  if (kind === "voucher" && payload.kind === "voucher") {
    return FILL_JOB_PAGES.voucher_new.test(path) && url.search === `?usecase=${payload.voucher.usecase}`;
  }
  if (kind === "ads_edit" && payload.kind === "ads_edit") {
    const m = FILL_JOB_PAGES.ads_edit.exec(path);
    return !!m && m[1] === payload.ads.variant && m[2] === payload.ads.campaignId;
  }
  if (kind === "combo") return payload.kind === "combo" && FILL_JOB_PAGES.bundle_new.test(path) && url.search === "";
  if (kind === "affiliate_commission") return FILL_JOB_PAGES.affiliate_open.test(path);
  return false;
}

const TEXT_KEYS: readonly FillKey[] = ["title", "description_first_line"];

/** One job of the server's answer, or null when anything is off. */
export function parseFillJob(raw: unknown): FillJob | null {
  if (!isRecord(raw)) return null;
  const id = str(raw.id, 36);
  const kind = raw.kind as JobKind;
  const status = str(raw.status, 12) as JobStatus | undefined;
  const openPath = str(raw.open_path, 200);
  const p = raw.payload;
  if (!id || !FILL_JOB_ID_PATTERN.test(id) || !status || !openPath || !isRecord(p)) return null;
  if (!openPath.startsWith("/") || openPath.startsWith("//")) return null;
  let payload: JobPayload | null = null;
  if (kind === "title" || kind === "description_first_line") {
    const itemId = /\/portal\/product\/(\d{1,20})$/.exec(openPath.split("?")[0] ?? "")?.[1];
    const fields: FillField[] = [];
    for (const f of Array.isArray(p.fields) ? p.fields : []) {
      if (!isRecord(f)) return null;
      const key = f.key as FillKey;
      const value = str(f.value, 600);
      const label = str(f.label, 80);
      const mode = f.mode === "replace" || f.mode === "first_line" ? f.mode : undefined;
      const maxChars = num(f.max_chars) ?? 0;
      if (!TEXT_KEYS.includes(key) || key !== kind || !value || !label || !mode || maxChars < 1 || value.length > maxChars || /[\r\n]/.test(value)) return null;
      fields.push({ key, label, value, mode, maxChars });
    }
    if (!itemId || fields.length !== 1) return null;
    payload = { kind, fields, itemId };
  } else if (kind === "voucher") {
    const v = voucher(p);
    payload = v ? { kind, voucher: v } : null;
  } else if (kind === "ads_edit") {
    const a = ads(p);
    payload = a ? { kind, ads: a } : null;
  } else if (kind === "affiliate_commission") {
    const productIds = ids(p.product_ids);
    const pct = num(p.commission_pct);
    payload = productIds && productIds.length > 0 && pct !== undefined && pct > 0 && pct <= 50 ? { kind, affiliate: { productIds, commissionPct: pct } } : null;
  } else if (kind === "combo") {
    const c = combo(p);
    payload = c ? { kind, combo: c } : null;
  }
  if (!payload || !addressOk(kind, openPath, payload)) return null;
  const version = int(raw.version, 1, 9) ?? 1;
  return {
    id,
    cardId: str(raw.card_id, 36) ?? "",
    code: str(raw.code, 40) ?? "",
    title: str(raw.title, 300) ?? str(raw.code, 40) ?? "",
    version,
    groupCode: str(raw.group_code, 16) ?? null,
    kind,
    status,
    openPath,
    payload,
  };
}

/** The reply of the service worker to the content script's job request. */
export type JobReply = { ok: true; value: FillJob } | { ok: false; reason: "inactive" | "unpaired" | "unknown_job" | "wrong_page" | "budget" | "error" };
