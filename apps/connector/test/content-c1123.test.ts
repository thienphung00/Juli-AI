// Connector 0.3.32 (batch-1123-a C3): Phân tích Nội dung is ready at 13:30 GMT+7 for yesterday; its
// empty state ("0 Nội dung") is read as an empty day. Made-up data only.
import { describe, expect, it } from "vitest";
import { gmt7Minute, planJobs } from "../src/platforms/shopee/background/scheduler";
import { CONTENT_READY_MINUTE_GMT7 } from "../src/platforms/shopee/config";
import { pollingWaitFor, type ReaderEnv, runReaderJob } from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";

const SHOP = "5b0c1d2e-3f40-4a51-8b62-7c83d94e0a15";
const at = (hh: number, mm: number) => Date.UTC(2026, 10, 23, hh - 7, mm, 0); // GMT+7 wall clock on 23/11

describe("KOL content timing", () => {
  it("is planned from 13:35 GMT+7 only", () => {
    expect(gmt7Minute(at(13, 35))).toBe(CONTENT_READY_MINUTE_GMT7);
    const plan = (nowMs: number) => planJobs({ shopId: SHOP, nowMs, stopped: new Set<never>(), adsDone: [], readers: ["affiliate_content"] }).map((j) => j.id);
    expect(plan(at(9, 0))).toEqual([]);
    expect(plan(at(13, 34))).toEqual([]);
    expect(plan(at(13, 35))).toEqual(["affiliate_content"]);
    expect(plan(at(22, 0))).toEqual(["affiliate_content"]);
  });

  it("its page's empty state is an empty day for yesterday (no query captured)", async () => {
    let clock = at(14, 0);
    const sleep = async (ms: number) => {
      clock += ms;
    };
    const env: ReaderEnv = {
      origin: "https://banhang.shopee.vn",
      pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
      now: () => clock,
      session: () => ({}),
      hasSession: () => true,
      template: () => undefined,
      waitFor: pollingWaitFor(sleep, () => clock),
      fetch: async () => {
        throw new Error("nothing is requested");
      },
      contentEmptyVisible: () => true,
    };
    const outcome = await runReaderJob({ id: "affiliate_content" }, env);
    expect(outcome.status).toBe("done");
    expect(outcome.responses.map((r) => [r.endpoint, r.period])).toEqual([["affiliate_content_summary", { start: "2026-11-22", end: "2026-11-22" }]]);
    const missing = await runReaderJob({ id: "affiliate_content" }, { ...env, contentEmptyVisible: () => false });
    expect(missing.status).toBe("needs_template");
  });
});
