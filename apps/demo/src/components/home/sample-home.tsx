import sampleEnvelope from "../../lib/shop-analysis/sample-report.json";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { HomeOverview } from "./home-overview";

/**
 * Trang chủ for an ANONYMOUS visitor (after "Dùng thử Demo"): the same
 * synthetic sample report Phân tích shows (invented shop, invented numbers),
 * bundled statically — viewing it issues no request. An entry of
 * `replay-module-graph.test.ts`, which keeps every authenticated backend client out of
 * this module's import graph.
 */
const SAMPLE = sampleEnvelope as unknown as ShopAnalysisEnvelope;

export function SampleHome() {
  return <HomeOverview envelope={SAMPLE} sample />;
}
