// Shared by the fill-job tests: raw jobs as Juli serves them, and run dependencies.
import type { JobDeps } from "../src/fill/job-run";
import { type JobReply, parseFillJob } from "../src/fill/job-types";

export const JOB_ID = "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f";

export const voucherPayload = (over: Record<string, unknown> = {}) => ({
  usecase: 1,
  name: "JC-2611-0007 V1 — voucher đơn tối thiểu",
  code_suffix: "GBB48",
  starts_at: "12:00 09-11-2026",
  ends_at: "11:59 23-11-2026",
  voucher_type: "promotion",
  discount: { type: "amount", value: 3000 },
  min_spend: 90000,
  usage_total: 50,
  per_buyer: 1,
  display: "multi",
  product_ids: [],
  open_path: "/portal/marketing/vouchers/new?usecase=1",
  ...over,
});

export function rawJob(kind: string, payload: Record<string, unknown>, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: JOB_ID,
    card_id: "00000000-0000-0000-0000-000000000001",
    code: "JC-2611-0007",
    title: "Voucher mẫu",
    version: 1,
    group_code: null,
    kind,
    status: "queued",
    target: {},
    seq: 0,
    open_path: payload.open_path,
    payload,
    ...over,
  };
}

export const voucherJob = (over: Record<string, unknown> = {}) => rawJob("voucher", voucherPayload(over));
export const adsJob = (ads: Record<string, unknown>, variant = "manual") =>
  rawJob("ads_edit", { campaign_id: "160675212", variant, open_path: `/portal/marketing/pas/product/${variant}/160675212`, ...ads });
export const affiliateJob = (over: Record<string, unknown> = {}) =>
  rawJob("affiliate_commission", {
    product_ids: ["1001", "1003"],
    commission_pct: 12.5,
    open_path: "/portal/web-seller-affiliate/open_campaign",
    ...over,
  });

export const comboJob = (over: Record<string, unknown> = {}) =>
  rawJob("combo", {
    name: "JC-2611-0009 V1",
    starts_at: "12:00 09-11-2026",
    ends_at: "23:59 23-11-2026",
    discount_type: "pct",
    tiers: [
      { qty: 2, value: 5 },
      { qty: 3, value: 8 },
    ],
    purchase_limit: 5,
    product_ids: ["1001", "1003"],
    open_path: "/portal/marketing/bundle/new",
    ...over,
  });

export interface JobHarness {
  deps: JobDeps;
  reports: [string, string, string | undefined][];
  halted: string[];
  clock: { t: number };
}

export function jobHarness(raw: Record<string, unknown> | JobReply, over: { prompt?: () => boolean; hash?: string; path?: string } = {}): JobHarness {
  const reports: JobHarness["reports"] = [];
  const halted: string[] = [];
  const clock = { t: 0 };
  const reply: JobReply = "ok" in raw ? (raw as JobReply) : (() => {
    const job = parseFillJob(raw);
    return job ? { ok: true as const, value: job } : { ok: false as const, reason: "error" as const };
  })();
  const path = over.path ?? String((raw as { open_path?: string }).open_path ?? "/portal/marketing/vouchers/new").split("?")[0]!;
  const deps: JobDeps = {
    doc: document,
    loc: { pathname: path, hash: over.hash ?? `#juli-fill=${JOB_ID}` },
    ask: async () => reply,
    report: async (id, status, error) => {
      reports.push([id, status, error]);
    },
    halt: async (id) => {
      halted.push(id);
    },
    passwordPrompt: over.prompt ?? (() => false),
    sleep: async (ms) => {
      clock.t += ms;
    },
    now: () => clock.t,
  };
  return { deps, reports, halted, clock };
}
