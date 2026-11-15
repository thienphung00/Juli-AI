// Connector 0.3.20: the item-list (Phân Tích Bán Hàng › Sản phẩm › Truy cập) answers were reported
// as drift with missing ["code","result"]: the new envelope was not captured. The mappers now take
// the answer with or without `code` / `result` and find the rows by their keys; drift only when
// no row list exists. Fake values only.
import { describe, expect, it } from "vitest";
import { itemRowsIn, mapCaptured } from "../src/shopee/map";
import { classify, trimTrafficBody, type ReaderResponse } from "../src/shopee/reader";
import { mapItemTraffic } from "../src/shopee/reader-map";
import { isDataAnswer } from "../src/shopee/runner";
import itemList from "./fixtures/item_list.json";
import trafficDetails from "./fixtures/readers/traffic_details.json";

const NOW = Date.UTC(2026, 9, 12, 3, 0, 0);
const Y_START = Date.UTC(2026, 9, 10, 17, 0, 0) / 1000;
const URL_ITEMS = `https://banhang.shopee.vn/api/mydata/v1/product/traffic/item-list/?start_time=${Y_START}&end_time=${
  Y_START + 86399
}&period=yesterday&l1_source=psd_label_product_card&page_num=1&page_size=10&order_type=confirmed`;
const rows = (itemList as { result: { item: unknown[] } }).result.item;
const items = (body: unknown) => mapCaptured({ url: URL_ITEMS, body, capturedAt: NOW });

describe("item-list envelopes (0.3.20)", () => {
  it.each([
    ["{code, result} as recorded", itemList],
    ["{error: 0, data}", { error: 0, message: "", data: { item: rows, total: 2 } }],
    ["{data} without a code", { data: { list: rows } }],
    ["{result} without a code", { result: { page: { item_list: rows } } }],
    ["{code: 0, data}", { code: 0, data: { item: rows } }],
    ["rows nested deeper, no wrapper at all", { page_info: { total: 2 }, payload: { rows } }],
  ])("maps the rows of %s", (_name, body) => {
    const mapped = items(body);
    expect(mapped?.drift).toBeNull();
    expect(mapped?.rows.map((r) => r.item_id)).toEqual(["111222333", "444555666"]);
    expect(mapped?.rows[0]).toMatchObject({ source: "psd_label_product_card", sales: 300000 });
  });

  it("an empty list is a real zero, not drift", () => {
    expect(items({ error: 0, data: { item: [], total: 0 } })).toMatchObject({ rows: [], drift: null });
  });

  it("an error code (as code or error) is not data and not drift", () => {
    expect(items({ error: 1001, message: "err" })).toBeNull();
    expect(items({ code: 1001, msg: "err", result: null })).toBeNull();
  });

  it("drift only when no row list is found anywhere", () => {
    expect(items({ data: { summary: { sales: 1 } } })?.drift?.missing).toEqual(["result.item"]);
    expect(items({ something: { else: 1 } })?.drift?.missing).toEqual(["code", "result"]);
    expect(itemRowsIn({ a: { b: [{ name: "no id" }] } })).toBeUndefined();
  });

  it("the backfill reads {error: 0, data} as a data answer, an error code as not", () => {
    expect(isDataAnswer(200, { error: 0, data: { item: [] } })).toBe(true);
    expect(isDataAnswer(200, { data: { item: [] } })).toBe(true);
    expect(isDataAnswer(200, { code: 0, result: {} })).toBe(true);
    expect(isDataAnswer(200, { error: 5, data: {} })).toBe(false);
    expect(isDataAnswer(200, { code: 3 })).toBe(false);
    expect(isDataAnswer(200, { error: 0 })).toBe(false);
    expect(isDataAnswer(500, { code: 0 })).toBe(false);
  });
});

describe("item traffic (traffic/details) envelopes (0.3.20)", () => {
  const day = "2026-11-02";
  const result = (trafficDetails as { result: Record<string, unknown> }).result;
  const reply = (body: unknown): ReaderResponse => ({
    endpoint: "traffic_details",
    url: "https://banhang.shopee.vn/api/mydata/v1/product/traffic/details/",
    status: 200,
    body: trimTrafficBody(body),
    capturedAt: NOW,
    source: "replay",
    day,
    itemId: "1001",
  });

  it.each([
    ["{code, result}", trafficDetails],
    ["{error: 0, data}", { error: 0, data: result }],
    ["{data}", { data: result }],
    ["{result} without code", { result }],
  ])("maps %s to the same rows", (_name, body) => {
    const [expected] = mapItemTraffic([reply(trafficDetails)]);
    const [post] = mapItemTraffic([reply(body)]);
    expect(post?.drift).toBeNull();
    expect(post?.rows.length).toBeGreaterThan(0);
    expect(post?.rows).toEqual(expected?.rows);
  });

  it("the trimmed answer keeps the error code, so a refusal is still an error", () => {
    expect(classify(200, trimTrafficBody({ error: 0, data: result }))).toBe("ok");
    expect(classify(200, trimTrafficBody({ error: 7, data: result }))).toBe("error");
  });

  it("drift only when no source blocks exist", () => {
    const [post] = mapItemTraffic([reply({ data: { funnel: {} } })]);
    expect(post?.drift?.missing).toEqual(["result.product_card.total"]);
  });
});
