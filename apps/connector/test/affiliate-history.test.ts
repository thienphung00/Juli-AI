// Connector 0.3.17: the conversion report's real channel label and the once-per-shop 6-month
// history (30-day windows, one post each). Synthetic orders and handles only.
import { describe, expect, it } from "vitest";
import { AFFILIATE_HISTORY_WINDOWS, AFFILIATE_WINDOW_DAYS } from "../src/config";
import { affiliateHistoryWindows, planJobs } from "../src/background/scheduler";
import { mapAffiliateConversions, mapConversionWindows } from "../src/shopee/affiliate-map";
import {
  conversionWindows,
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  trimCaptured,
} from "../src/shopee/reader";
import { Pacer } from "../src/shopee/runner";
import { gmt7DateStart } from "../src/shopee/time";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 13, 2, 0, 0); // 2026-11-13 09:00 GMT+7
const SHOP = "00000000-0000-4000-8000-000000000001";

function order(id: string, extra: Record<string, unknown>) {
  return {
    order_id: id,
    purchase_time: gmt7DateStart("2026-11-10") + 3600,
    order_status: "Completed",
    fraud_status: 1,
    shopee_username: "kol_test",
    traffic_type: 0,
    items: [{ item_id: "111", model_id: "222", item_price: 100_000, actual_amount: 100_000, refunded_amount: 0, qty: 1, expense: "1080", campaign_type: 5 }],
    ...extra,
  };
}

function page(list: unknown[]) {
  return { code: 0, data: { page_num: 1, page_size: 20, total_count: list.length, list } };
}

function response(body: unknown, period: { start: string; end: string }): ReaderResponse {
  return {
    endpoint: "affiliate_conversion",
    url: `${SC}/x`,
    status: 200,
    body: trimCaptured("affiliate_conversion", body),
    capturedAt: NOW,
    source: "replay",
    period,
  };
}

describe("conversion report channel (0.3.17)", () => {
  it("posts the channel Seller Centre shows: a Shopee surface, else the outside source, else the code", () => {
    const body = page([
      order("A1", { traffic_type: 1, internal_source: "Shopeevideo", last_external_source: "" }),
      order("A2", { traffic_type: 0, internal_source: "", last_external_source: "Facebook" }),
      order("A3", { traffic_type: 0 }),
    ]);
    const mapped = mapAffiliateConversions([response(body, { start: "2026-10-14", end: "2026-11-12" })], NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows.map((r) => r.channel)).toEqual(["Shopeevideo", "Facebook", "0"]);
    expect(mapped.rows.map((r) => r.campaign_type)).toEqual(["5", "5", "5"]);
  });
});

describe("6-month affiliate history (0.3.17)", () => {
  it("windows are 30 days, contiguous, newest first, right before the regular 30-day window", () => {
    const windows = affiliateHistoryWindows(NOW);
    expect(windows).toHaveLength(AFFILIATE_HISTORY_WINDOWS);
    const regular = conversionWindows(NOW)[0]!;
    expect(regular).toEqual({ start: "2026-10-14", end: "2026-11-12" });
    expect(windows[0]).toEqual({ start: "2026-09-14", end: "2026-10-13" });
    for (let i = 0; i < windows.length; i += 1) {
      const w = windows[i]!;
      const days = (gmt7DateStart(w.end) - gmt7DateStart(w.start)) / 86_400 + 1;
      expect(days).toBe(AFFILIATE_WINDOW_DAYS);
      expect(days).toBeLessThanOrEqual(31); // Juli's period cap
      if (i > 0) expect(gmt7DateStart(windows[i - 1]!.start) - gmt7DateStart(w.end)).toBe(86_400);
    }
  });

  it("the affiliate page carries the history until the shop's history posted", () => {
    const base = { shopId: SHOP, nowMs: NOW, stopped: new Set<never>(), adsDone: [], readers: ["affiliate"] as const };
    const first = planJobs(base);
    expect(first).toEqual([{ id: "affiliate", history: affiliateHistoryWindows(NOW) }]);
    const after = planJobs({ ...base, affiliateHistoryShop: SHOP });
    expect(after).toEqual([{ id: "affiliate" }]);
  });

  it("the reader reads the regular window then each history window, each answer dated by its window", async () => {
    let clock = NOW;
    const sent: ReaderRequest[] = [];
    const sleep = async (ms: number) => {
      clock += ms;
    };
    const now = () => clock;
    const env: ReaderEnv = {
      origin: SC,
      pacer: new Pacer({ sleep, now, random: () => 0 }),
      now,
      session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
      hasSession: () => true,
      template: (endpoint) =>
        endpoint === "affiliate_conversion" ? { query: { page_num: "1", page_size: "20", purchase_time_s: "1", purchase_time_e: "2" } } : undefined,
      waitFor: pollingWaitFor(sleep, now),
      fetch: async (request): Promise<FetchedReaderResponse> => {
        sent.push(request);
        return { status: 200, text: async () => JSON.stringify(page([order(`O${sent.length}`, {})])) };
      },
      pathname: () => "/portal/web-seller-affiliate/conversion_report",
    };
    const history = affiliateHistoryWindows(NOW).slice(0, 2);
    const outcome = await runReaderJob({ id: "affiliate", history }, env);
    expect(outcome.status).toBe("done");
    expect(sent).toHaveLength(3);
    const starts = sent.map((r) => Number(new URL(r.url).searchParams.get("purchase_time_s")));
    expect(starts).toEqual([gmt7DateStart("2026-10-14"), gmt7DateStart(history[0]!.start), gmt7DateStart(history[1]!.start)]);
    expect(outcome.responses.map((r) => r.period)).toEqual([conversionWindows(NOW)[0], ...history]);

    // One post per window, never merged past Juli's 31-day cap.
    const posts = mapConversionWindows(outcome.responses, NOW);
    expect(posts).toHaveLength(3);
    expect(posts.map((p) => p.rows.length)).toEqual([1, 1, 1]);
    expect(new Set(posts.map((p) => p.date)).size).toBe(3);
  });

  it("a single window maps exactly as before", () => {
    const one = [response(page([order("B1", {})]), { start: "2026-10-14", end: "2026-11-12" })];
    expect(mapConversionWindows(one, NOW)).toEqual([mapAffiliateConversions(one, NOW)]);
  });
});
