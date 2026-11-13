import type { KolCandidate } from "../../components/shopee-decisions/kol-builder";
import type { KolApi } from "../shopee-kol/types";

/** Cashback / coupon affiliates (ADR-122 d.9): classified by handle; the backend holds the authoritative list. */
const CASHBACK = /accesstrade|shopback|cashback|hoantien|hoan_tien|coupon|voucher|magiamgia|giamgia/i;
const COUPON = /coupon|voucher|magiamgia|giamgia/i;

export function kolKind(handle: string | null): NonNullable<KolCandidate["kind"]> {
  if (!handle || !CASHBACK.test(handle)) return "kol";
  return COUPON.test(handle) ? "coupon" : "cashback";
}

/** The shop's KOL rows (distinct keys from the KOL report) as the KOL builder expects them. */
export function kolCandidatesOf(api: KolApi): () => Promise<readonly KolCandidate[]> {
  return async () => {
    const report = await api.report({ window: { period: "90d" } });
    return report.filters.kols.map((k) => ({ kol_key: k.kol_key, handle: k.handle, kind: kolKind(k.handle) }));
  };
}
