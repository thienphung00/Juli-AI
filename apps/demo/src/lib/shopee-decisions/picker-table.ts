import type { PickerProduct, ProductSort } from "./builder-api";

/**
 * P97 D85.12 · the table picker's logic: search, the filters of the Shopee-style table, "chọn tất cả
 * theo bộ lọc" and pasted lists of ids. Pure; the component keeps only the form state.
 */

export type MarginBand = "all" | "unknown" | "low" | "mid" | "high";

export const MARGIN_BANDS: readonly (readonly [MarginBand, string])[] = [
  ["all", "Mọi mức biên"],
  ["low", "Biên dưới 10%"],
  ["mid", "Biên 10% – 25%"],
  ["high", "Biên trên 25%"],
  ["unknown", "Biên chưa tính"],
];

export interface PickerFilters {
  readonly q: string;
  readonly category: string;
  readonly margin: MarginBand;
  readonly ctorDown: boolean;
  readonly hasProposal: boolean;
  readonly inAds: boolean;
  readonly inKol: boolean;
  /** The two P92 chips: "Thiếu giá vốn" and "Không bán 30 ngày qua". */
  readonly chip: "all" | "missing" | "idle";
}

export const NO_FILTERS: PickerFilters = { q: "", category: "", margin: "all", ctorDown: false, hasProposal: false, inAds: false, inKol: false, chip: "all" };

export const isIdle = (p: PickerProduct): boolean => p.orders_30d === 0;
export const isMissingCost = (p: PickerProduct): boolean => p.missing_cost_chip !== null || !p.has_cost;

export function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/gi, "d")
    .toLowerCase()
    .trim();
}

export function marginBandOf(p: PickerProduct): Exclude<MarginBand, "all"> {
  const m = p.margin_pct;
  if (m === null || m === undefined || !p.has_cost) return "unknown";
  return m < 10 ? "low" : m <= 25 ? "mid" : "high";
}

export function filtersActive(f: PickerFilters): boolean {
  return f.q.trim() !== "" || f.category !== "" || f.margin !== "all" || f.ctorDown || f.hasProposal || f.inAds || f.inKol || f.chip !== "all";
}

export function matches(p: PickerProduct, f: PickerFilters): boolean {
  const needle = fold(f.q);
  if (needle && !fold(p.name).includes(needle) && !p.item_id.toLowerCase().includes(needle)) return false;
  if (f.category && p.category !== f.category) return false;
  if (f.margin !== "all" && marginBandOf(p) !== f.margin) return false;
  if (f.ctorDown && p.ctor_down !== true) return false;
  if (f.hasProposal && p.has_proposal !== true) return false;
  if (f.inAds && p.in_ads !== true) return false;
  if (f.inKol && p.in_kol !== true) return false;
  if (f.chip === "missing" && !isMissingCost(p)) return false;
  if (f.chip === "idle" && !isIdle(p)) return false;
  return true;
}

export function sortProducts(list: readonly PickerProduct[], sort: ProductSort): PickerProduct[] {
  const key = (p: PickerProduct): number => (sort === "gmv_90d" ? (p.gmv_90d ?? -1) : sort === "orders_90d" ? p.orders_90d : p.orders_30d);
  return [...list].sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name, "vi") : key(b) - key(a)));
}

export function filterProducts(products: readonly PickerProduct[], f: PickerFilters, sort: ProductSort = "gmv_90d"): PickerProduct[] {
  return sortProducts(products.filter((p) => matches(p, f)), sort);
}

export function categoriesOf(products: readonly PickerProduct[]): string[] {
  return [...new Set(products.map((p) => p.category).filter((c): c is string => !!c))].sort((a, b) => a.localeCompare(b, "vi"));
}

/** Ids pasted as a list (spaces, commas, semicolons, new lines, tabs); duplicates dropped, order kept. */
export function parseIds(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean))];
}

export interface PasteResult {
  readonly found: readonly string[];
  readonly missing: readonly string[];
}

export function matchPasted(products: readonly PickerProduct[], text: string): PasteResult {
  const known = new Set(products.map((p) => p.item_id));
  const ids = parseIds(text);
  return { found: ids.filter((i) => known.has(i)), missing: ids.filter((i) => !known.has(i)) };
}

/** `current` plus `add` (no duplicates), capped at `max` when given; order kept. */
export function addIds(current: readonly string[], add: readonly string[], max?: number): string[] {
  const out = [...new Set([...current, ...add])];
  return max !== undefined ? out.slice(0, max) : out;
}

export const removeId = (current: readonly string[], id: string): string[] => current.filter((x) => x !== id);
