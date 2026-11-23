// @vitest-environment jsdom
// batch-1123-a2 C-K1 (E115): end and read-back jobs carry Shopee's numeric id, else the voucher's
// code (`code_suffix` / `code` / readback `voucher_code`) or the combo's name (`name` / readback
// `combo_name`). A typed code stored as the id (before a2) is read as the code. A served job of a
// known kind that does not parse is reported `failed` / job_malformed once, never silently dropped.
import { describe, expect, it } from "vitest";
import { JOB_MALFORMED } from "../src/core/jobs/fill-jobs";
import { FillJobs } from "../src/platforms/shopee/background/fill-jobs";
import { loadState } from "../src/platforms/shopee/background/state";
import { malformedJobId, parseFillJob } from "../src/platforms/shopee/fill/job-types";
import { listRowOf } from "../src/platforms/shopee/fill/revert";
import { JOB_ID, rawJob, voucherJob } from "./fill-job-helpers";

const VOUCHER_LIST = "/portal/marketing/vouchers/list";
const BUNDLE_LIST = "/portal/marketing/bundle/list";
const voucherEnd = (p: Record<string, unknown>) => rawJob("voucher_end", { mode: "revert", open_path: VOUCHER_LIST, ...p });
const comboEnd = (p: Record<string, unknown>) => rawJob("combo_end", { mode: "revert", open_path: BUNDLE_LIST, ...p });
const readback = (target: Record<string, unknown>, datasets = ["voucher_list"], open_path = VOUCHER_LIST) =>
  rawJob("readback", { mode: "readback", open_path, target, datasets });

describe("C-K1: end targets", () => {
  it("a numeric voucher_id is the id; code_suffix / code / name are the fallbacks", () => {
    expect(parseFillJob(voucherEnd({ voucher_id: "123456789" }))?.payload).toEqual({ kind: "voucher_end", end: { id: "123456789" } });
    expect(parseFillJob(voucherEnd({ voucher_id: 123456789 }))?.payload).toEqual({ kind: "voucher_end", end: { id: "123456789" } });
    expect(parseFillJob(voucherEnd({ code_suffix: "ABC12" }))?.payload).toEqual({ kind: "voucher_end", end: { code: "ABC12" } });
    expect(parseFillJob(voucherEnd({ code: "SHOPABC12" }))?.payload).toEqual({ kind: "voucher_end", end: { code: "SHOPABC12" } });
    expect(parseFillJob(comboEnd({ name: "Combo mẫu 1" }))?.payload).toEqual({ kind: "combo_end", end: { name: "Combo mẫu 1" } });
  });

  it("E115: a typed code stored as voucher_id is read as the code, not dropped", () => {
    expect(parseFillJob(voucherEnd({ voucher_id: "SHOPXYZ9Q" }))?.payload).toEqual({ kind: "voucher_end", end: { code: "SHOPXYZ9Q" } });
    // the payload's own code wins over the one in voucher_id
    expect(parseFillJob(voucherEnd({ voucher_id: "SHOPXYZ9Q", code_suffix: "XYZ9Q" }))?.payload).toEqual({ kind: "voucher_end", end: { code: "XYZ9Q" } });
  });

  it("an id that is neither digits nor a code is malformed (null), and so is a combo_id that is not digits", () => {
    expect(parseFillJob(voucherEnd({ voucher_id: "mã sai!" }))).toBeNull();
    expect(parseFillJob(comboEnd({ combo_id: "COMBO1", name: "Combo mẫu 1" }))).toBeNull();
    expect(parseFillJob(voucherEnd({}))).toBeNull();
  });

  it("the end row is found by the code when there is no id", () => {
    document.body.innerHTML = `<table><tbody>
      <tr id="a"><td><span>Voucher mẫu A</span></td><td><span>SHOPAAA11</span></td><td><button>Kết thúc</button></td></tr>
      <tr id="b"><td><span>Voucher mẫu B</span></td><td><span>SHOPXYZ9Q</span></td><td><button>Kết thúc</button></td></tr>
    </tbody></table>`;
    const job = parseFillJob(voucherEnd({ voucher_id: "SHOPXYZ9Q" }))!;
    expect(job.payload.kind === "voucher_end" && listRowOf(document, job.payload.end)?.id).toBe("b");
  });
});

describe("C-K1: read-back targets", () => {
  it("accepts voucher_code and combo_name, and reads a code stored as voucher_id as voucher_code", () => {
    expect(parseFillJob(readback({ voucher_code: "shopxyz9q" }))?.payload).toEqual({ kind: "readback", readback: { target: { voucherCode: "SHOPXYZ9Q" }, datasets: ["voucher_list"] } });
    expect(parseFillJob(readback({ voucher_id: "SHOPXYZ9Q" }))?.payload).toMatchObject({ readback: { target: { voucherCode: "SHOPXYZ9Q" } } });
    expect(parseFillJob(readback({ voucher_id: "987654321" }))?.payload).toMatchObject({ readback: { target: { voucherId: "987654321" } } });
    expect(parseFillJob(readback({ combo_name: "Combo mẫu 1" }, ["combo_list"], BUNDLE_LIST))?.payload).toMatchObject({ readback: { target: { comboName: "Combo mẫu 1" } } });
  });

  it("rejects a bad code or an item_id that is not digits", () => {
    expect(parseFillJob(readback({ voucher_code: "mã sai!" }))).toBeNull();
    expect(parseFillJob(readback({ item_id: "abc" }, ["item_catalog"], "/portal/product/list/all"))).toBeNull();
  });
});

describe("C-K1: a job that does not parse is reported, not dropped", () => {
  const TOKEN = { token: "jci_x", token_id: "t1", shop_id: "s1", platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };
  function setup(jobs: unknown[]) {
    const data: Record<string, unknown> = { token: TOKEN };
    const storage = {
      async get(keys?: string | string[] | null) {
        const list = keys == null ? Object.keys(data) : Array.isArray(keys) ? keys : [keys];
        return Object.fromEntries(list.filter((k) => data[k] != null).map((k) => [k, data[k]]));
      },
      async set(items: Record<string, unknown>) {
        Object.assign(data, items);
      },
    };
    const reports: { id: string; body: Record<string, unknown> }[] = [];
    const runner = new FillJobs({
      storage,
      client: {
        fillJobs: async () => ({ enabled: true, jobs }),
        fillJobReport: async (_t: string, id: string, body: Record<string, unknown>) => {
          reports.push({ id, body });
          return {};
        },
      },
      now: () => Date.UTC(2026, 10, 23, 3),
      tabs: { openPage: async () => 41, inspect: async () => ({ open: true }) },
      busy: async () => false,
      halt: async () => undefined,
    });
    return { runner, reports, storage };
  }
  const bad = voucherEnd({ voucher_id: "mã sai!" });

  it("malformedJobId: known kind, open status, valid id, refused by the parser", () => {
    expect(malformedJobId(bad)).toBe(JOB_ID);
    expect(malformedJobId(voucherJob())).toBeNull(); // parses
    expect(malformedJobId({ ...bad, kind: "tiktok_future" })).toBeNull(); // a newer Juli's kind
    expect(malformedJobId({ ...bad, status: "filled" })).toBeNull(); // not open any more
    expect(malformedJobId({ ...bad, id: "not-a-uuid" })).toBeNull();
  });

  it("the poll reports it failed / job_malformed once", async () => {
    const s = setup([bad]);
    expect(await s.runner.poll()).toBe("nothing_queued");
    expect(await s.runner.poll()).toBe("nothing_queued");
    expect(s.reports).toEqual([{ id: JOB_ID, body: { status: "failed", error: JOB_MALFORMED } }]);
    expect((await loadState(s.storage)).fill?.malformed).toEqual([JOB_ID]);
  });

  it("the page asking for it is told it is malformed (not 'Juli không còn thấy việc này')", async () => {
    const s = setup([bad]);
    expect(await s.runner.jobFor(`https://banhang.shopee.vn${VOUCHER_LIST}#juli-fill=${JOB_ID}`, JOB_ID)).toEqual({ ok: false, reason: "malformed_job" });
    expect(s.reports).toEqual([{ id: JOB_ID, body: { status: "failed", error: JOB_MALFORMED } }]);
  });
});
