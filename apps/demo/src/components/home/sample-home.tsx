import { sampleEnvelope } from "../../lib/phan-tich/sample-data";
import { HomeOverview } from "./home-overview";

/**
 * Trang chủ's sample ("Bản minh họa"): signed out after "Dùng thử Demo", and
 * signed in with no TikTok Shop connected (P13, under the connect strip).
 * The same invented cosmetics shop and numbers as the Phân tích and Quyết
 * định samples (`lib/phan-tich/sample-data.ts`), built in memory — viewing it
 * issues no request. An entry of `replay-module-graph.test.ts`, which keeps
 * every authenticated backend client out of this module's import graph.
 */
const SAMPLE = sampleEnvelope();

export function SampleHome() {
  return <HomeOverview envelope={SAMPLE} sample />;
}
