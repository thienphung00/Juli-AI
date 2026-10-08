import sampleEnvelope from "../../lib/shop-analysis/sample-report.json";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { ShopAnalysisView } from "./shop-analysis-view";

/**
 * The anonymous Phân tích branch (AC-7.7): a synthetic sample report —
 * invented shop ("Cửa hàng Mẫu Hoa Mai"), invented products and numbers,
 * generated from a synthetic snapshot through the real report builder, never
 * from any real shop's data. Bundled statically: viewing it issues no request
 * (this module is an entry of `replay-module-graph.test.ts`).
 */
export const SAMPLE_SHOP_ANALYSIS = sampleEnvelope as unknown as ShopAnalysisEnvelope;

export function SampleShopAnalysis() {
  return <ShopAnalysisView envelope={SAMPLE_SHOP_ANALYSIS} sample />;
}
