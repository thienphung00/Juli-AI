import { describe, expect, it } from "vitest";
import { AFFILIATE_READER_IDS, READER_FAIL_ATTEMPTS_PER_DAY } from "../src/platforms/shopee/config";
import { planJobs, readerFailureOutcome } from "../src/platforms/shopee/background/scheduler";
import { loadState, saveState } from "../src/platforms/shopee/background/state";
import type { ReaderId } from "../src/platforms/shopee/config";

const SHOP = "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15";
const T0 = Date.UTC(2026, 10, 19, 3, 0, 0); // 2026-11-19 10:00 GMT+7 (same anchor as f4-sched)
const TOKEN = {
  token: "jci_x",
  token_id: "t1",
  shop_id: SHOP,
  platform: "shopee",
  expires_at: "2027-01-10T00:00:00Z",
  rotate_after: "2026-12-01T00:00:00Z",
};

class MemoryStorage {
  data: Record<string, unknown> = {};
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, items);
  }
}

describe("0.3.31 W1: reader fail twice waits until tomorrow", () => {
  it("READER_FAIL_ATTEMPTS_PER_DAY is 2 and failure outcomes exclude done and reread blocks", () => {
    expect(READER_FAIL_ATTEMPTS_PER_DAY).toBe(2);
    expect(readerFailureOutcome("timeout")).toBe(true);
    expect(readerFailureOutcome("done:item_snapshot=posted")).toBe(false);
    expect(readerFailureOutcome("blocked:login")).toBe(false);
    expect(readerFailureOutcome("no_orders")).toBe(false);
  });

  it("after two failures the reader is not planned again the same day", async () => {
    const storage = new MemoryStorage();
    storage.data.token = TOKEN;
    await saveState(storage, {
      readers: {
        adsDone: [],
        trafficDone: [],
        lastRunDay: "2026-11-19",
        readerFails: { day: "2026-11-19", counts: { traffic: 2 } },
      },
    });
    const sched = (await loadState(storage)).readers!;
    const jobs = planJobs({
      shopId: SHOP,
      nowMs: T0,
      stopped: new Set(),
      adsDone: [],
      readers: ["traffic", "products"] as const,
      holes: { traffic_overview: ["2026-10-25"] },
      holeRoom: 100,
    }).filter((job) => ((sched.readerFails?.counts ?? {})[job.id] ?? 0) < READER_FAIL_ATTEMPTS_PER_DAY);
    expect(jobs.some((j) => j.id === "traffic")).toBe(false);
    expect(jobs.some((j) => j.id === "products")).toBe(true);
  });
});

describe("0.3.31 W1: today's readers before hole / history backfill days", () => {
  const base = {
    shopId: SHOP,
    nowMs: T0,
    stopped: new Set<never>(),
    adsDone: [] as string[],
    holes: { traffic_overview: ["2026-10-25", "2026-10-26"], ads_campaign_daily: ["2026-10-20"] },
    holeRoom: 100,
  };

  it("plans catch-up traffic before hole traffic, and affiliate pages before backfill jobs", () => {
    const readers = ["traffic", "product_period", ...AFFILIATE_READER_IDS, "ads"] as readonly ReaderId[];
    const jobs = planJobs({ ...base, readers });
    const traffic = jobs.filter((j) => j.id === "traffic");
    expect(traffic[0]?.days).toEqual(["2026-11-18", "2026-11-17", "2026-11-16", "2026-11-15"]); // yesterday + TRAFFIC_OVERVIEW_CATCHUP_DAYS
    expect(traffic[1]?.days).toEqual(["2026-10-25", "2026-10-26"]);
    const affIdx = jobs.findIndex((j) => j.id === "affiliate_kols");
    const holeIdx = jobs.findIndex((j) => j.id === "traffic" && j.days?.includes("2026-10-25"));
    expect(affIdx).toBeGreaterThan(-1);
    expect(holeIdx).toBeGreaterThan(affIdx);
    const adsBackfill = jobs.find((j) => j.id === "ads" && j.days?.includes("2026-10-20"));
    const adsToday = jobs.find((j) => j.id === "ads" && j.days && !j.days.includes("2026-10-20"));
    expect(adsToday?.days?.slice(-1)).not.toEqual(["2026-10-20"]);
    expect(adsBackfill?.days).toContain("2026-10-20");
  });
});