// Connector 0.3.35 (batch-1124-a C4): the Combo Khuyến Mãi list reader and its mapper. Shapes from
// the P-C2 capture (24/11); every id, name and number here is synthetic.
import { describe, expect, it } from "vitest";
import { READER_DATASETS, READERS_ACTIVE, READER_IDS } from "../src/platforms/shopee/config";
import { readerEndpointOf, readerPageUrl } from "../src/platforms/shopee/endpoints";
import { mapComboList, mapReaderJob } from "../src/platforms/shopee/reader-map";
import { type FetchedReaderResponse, pollingWaitFor, type ReaderEnv, type ReaderRequest, type ReaderResponse, runReaderJob, type Template } from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const AT = Date.parse("2026-11-24T03:00:00Z");

const listEntry = (id: number, name: string, timeStatus: number, itemCount = 2) => ({
  discount_type: 3,
  seller_discount: null,
  add_on_deal: null,
  bundle_deal: { discount_id: id, name, time_status: timeStatus, start_time: 1795000000, end_time: 1795600000, item_preview: { item_count: itemCount, images: [] }, source: 2 },
});
const listBody = (entries: unknown[]) => ({ code: 0, data: { discounts: entries } });
const detailBody = (id: number, rule: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  code: 0,
  data: {
    bundle_deal_id: id,
    usage_limit: 5,
    status: 1,
    start_time: 1795000000,
    end_time: 1795600000,
    extinfo: { labels: [], name: "x", itemid_list: [111, 222, 333] },
    bundle_deal_rule: rule,
    time_status: 3,
    ...extra,
  },
});
const pctRule = {
  rule_type: 2,
  min_amount: 2,
  discount_percentage: "5.00",
  discount_value: "0.00",
  fix_price: "0.00",
  additional_tiers: [{ min_amount: 3, fix_price: "0.00", discount_percentage: "10.00", discount_value: "0.00" }],
};

const reply = (endpoint: "combo_list" | "combo_detail", body: unknown): ReaderResponse => ({ endpoint, url: `${SC}/x`, status: 200, body, capturedAt: AT, source: "replay" });

function harness(template: Template, handler: (request: ReaderRequest, index: number) => unknown) {
  let clock = 1_000_000;
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
    template: (endpoint) => (endpoint === "combo_list" ? template : undefined),
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      const index = sent.length;
      sent.push(request);
      return { status: 200, text: async () => JSON.stringify(handler(request, index)) };
    },
    pathname: () => "/portal/marketing/list/discount",
  };
  return { env, sent };
}

describe("the combos reader (0.3.35)", () => {
  it("is a read-back-only reader on the discount list's Combo tab", () => {
    expect(READERS_ACTIVE.combos).toBe(true);
    expect(READER_DATASETS.combos).toEqual(["combo_settings"]);
    expect(READER_IDS).not.toContain("combos"); // not opened by the daily run
    expect(readerPageUrl({ id: "combos" })).toBe("/portal/marketing/list/discount?discountType=bundle&status=all&page=1");
    expect(readerEndpointOf("POST", "/api/marketing/v3/public/discount/list/")).toBe("combo_list");
    expect(readerEndpointOf("GET", "/api/marketing/v3/bundle_deal/")).toBe("combo_detail");
    expect(readerEndpointOf("POST", "/api/marketing/v3/bundle_deal/")).toBeNull();
  });

  it("pages the list with discount_type 3, then GETs the detail of upcoming / running combos only, newest first", async () => {
    const page1 = listBody([listEntry(9001, "A", 2), listEntry(9003, "B", 3)]);
    const page2 = listBody([listEntry(9002, "C", 1)]);
    const h = harness({ query: { SPC_CDS: "s" }, body: { discount_type: 1, time_status: 0, offset: 0, limit: 2 }, headers: { "x-sample": "1" } }, (request, i) => {
      if (request.endpoint === "combo_list") return i === 0 ? page1 : page2;
      return detailBody(Number(new URL(request.url).searchParams.get("bundle_deal_id")), pctRule);
    });
    const outcome = await runReaderJob({ id: "combos" }, h.env);
    expect(outcome.status).toBe("done");
    const lists = h.sent.filter((r) => r.endpoint === "combo_list");
    expect(lists.map((r) => r.method)).toEqual(["POST", "POST"]);
    expect(lists.map((r) => JSON.parse(r.body ?? "{}"))).toEqual([
      { discount_type: 3, time_status: 0, offset: 0, limit: 2 },
      { discount_type: 3, time_status: 0, offset: 2, limit: 2 },
    ]);
    const details = h.sent.filter((r) => r.endpoint === "combo_detail");
    expect(details.map((r) => r.method)).toEqual(["GET", "GET"]);
    expect(details.map((r) => new URL(r.url).searchParams.get("bundle_deal_id"))).toEqual(["9002", "9001"]); // the ended 9003 is not read
    expect(details[0]?.headers["x-sample"]).toBe("1");
  });
});

describe("mapComboList", () => {
  it("maps the list row and its detail's tiers, buyer limit and product count", () => {
    const mapped = mapComboList([reply("combo_list", listBody([listEntry(9001, "Combo thử", 2, 1)])), reply("combo_detail", detailBody(9001, pctRule))], AT);
    expect(mapped.dataset).toBe("combo_settings");
    expect(mapped.drift).toBeNull();
    expect(mapped.rows).toEqual([
      {
        combo_id: "9001",
        program_name: "Combo thử",
        starts_at: "2026-11-18T18:06:40",
        ends_at: "2026-11-25T16:46:40",
        status: "2",
        product_count: 3,
        usage_limit: 5,
        discount_type: "pct",
        tiers: [
          { qty: 2, value: 5 },
          { qty: 3, value: 10 },
        ],
      },
    ]);
  });

  it("reads the kind from the value field that is set (amount off, special price)", () => {
    const amount = { rule_type: 3, min_amount: 2, discount_percentage: "0.00", discount_value: "20000.00", fix_price: "0.00", additional_tiers: [] };
    const fixed = { rule_type: 1, min_amount: 2, discount_percentage: "0.00", discount_value: "0.00", fix_price: "150000.00", additional_tiers: [] };
    const rows = mapComboList(
      [
        reply("combo_list", listBody([listEntry(1, "a", 2), listEntry(2, "b", 2)])),
        reply("combo_detail", detailBody(1, amount)),
        reply("combo_detail", detailBody(2, fixed)),
      ],
      AT,
    ).rows;
    expect(rows.map((r) => [r.discount_type, r.tiers])).toEqual([
      ["amount", [{ qty: 2, value: 20000 }]],
      ["special_price", [{ qty: 2, value: 150000 }]],
    ]);
  });

  it("keeps a combo whose detail was not read (list product count) or whose rule it cannot read (no tiers), without drift", () => {
    const odd = { ...pctRule, discount_value: "1000.00" }; // two value fields set
    const mapped = mapComboList([reply("combo_list", listBody([listEntry(1, "a", 3, 4), listEntry(2, "b", 2)])), reply("combo_detail", detailBody(2, odd))], AT);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows.map((r) => [r.combo_id, r.product_count, r.tiers])).toEqual([
      ["1", 4, undefined],
      ["2", 3, undefined],
    ]);
  });

  it("a list row without its id is drift (nothing posted)", () => {
    const broken = { ...listEntry(1, "a", 2), bundle_deal: { name: "a", start_time: 1795000000 } };
    const mapped = mapComboList([reply("combo_list", listBody([broken]))], AT);
    expect(mapped.drift).toEqual({ unexpected: [], missing: ["combos[].discount_id"] });
    expect(mapped.rows).toEqual([]);
  });

  it("is what the combos job maps to", () => {
    const out = mapReaderJob({ id: "combos" }, [reply("combo_list", listBody([listEntry(7, "x", 2)]))], AT);
    expect(out.map((m) => m.dataset)).toEqual(["combo_settings"]);
  });
});
