// Connector 0.3.26: an orders / order_income run that maps 0 rows always says why, and the list
// page's order links win over a card answer the hook kept but that holds no order (15-17/11 the
// real shop reported "orders:0_rows:ignored" three days running). The income page of an account
// without the Tài chính right is "blocked:no_permission". Every id, sn and value here is fake.
import { describe, expect, it } from "vitest";
import { jobOutcome } from "../src/platforms/shopee/background/scheduler";
import { todaysPagesAllRead } from "../src/platforms/shopee/background/connector";
import { NO_PERMISSION_LINE, outcomeStatus } from "../src/platforms/shopee/popup/guide";
import { mapOrderLines, zeroRowsStep } from "../src/platforms/shopee/orders-map";
import {
  cardsHoldOrders,
  type FetchedReaderResponse,
  isPermissionRefusal,
  type OrderLink,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  type ReaderResponse,
  runReaderJob,
  type Template,
  trimCaptured,
} from "../src/platforms/shopee/reader";
import type { ReaderEndpoint } from "../src/platforms/shopee/endpoints";
import { Pacer } from "../src/platforms/shopee/runner";
import { gmt7DateStart } from "../src/core/time";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 18, 3, 0, 0);
const ts = (day: string) => gmt7DateStart(day) + 12 * 3600;

/** A get_one_order answer (captured field names, fake values). */
function detail(id: number, sn: string) {
  const day = `20${sn.slice(0, 2)}-${sn.slice(2, 4)}-${sn.slice(4, 6)}`;
  return {
    code: 0,
    data: {
      order_id: id,
      order_sn: sn,
      status_info: { status: "Đã giao cho ĐVVC" },
      create_time: ts(day),
      complete_time: 0,
      price_before_discount: "120000",
      order_items: [{ item_id: 9001, model_id: 9101, amount: 1, order_price: "100000", item_model: { sku: "SKU-FAKE" } }],
    },
  };
}

/**
 * The card answer the hook kept on the DRM list page, scrubbed: an envelope with code 0 whose
 * orders are not plain JSON order records (an opaque payload). The hook keeps it trimmed, as here.
 */
const DRM_CARDS_RAW = { code: 0, data: { card_list_v2: "QUJDREVGR0hJSktMTU5PUA==", encrypted: true, page_info: { total: 3 } } };
const DRM_CARDS = trimCaptured("order_cards", DRM_CARDS_RAW);

const link = (id: number, day: string): OrderLink => ({ id: String(id), sn: `${day.slice(2, 4)}${day.slice(5, 7)}${day.slice(8, 10)}FAKE${id}` });

function env(
  options: {
    links?: OrderLink[];
    empty?: boolean;
    templates?: Partial<Record<ReaderEndpoint, Template>>;
    answer?: (request: ReaderRequest, sn: string) => { status?: number; body: unknown };
    permissionPage?: boolean;
  } = {},
) {
  let clock = NOW;
  const sent: ReaderRequest[] = [];
  const sleep = async (ms: number) => {
    clock += ms;
  };
  const now = () => clock;
  const links = options.links ?? [];
  const e: ReaderEnv = {
    origin: SC,
    pacer: new Pacer({ sleep, now, random: () => 0 }),
    now,
    session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
    hasSession: () => true,
    template: (endpoint) => options.templates?.[endpoint],
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      const id = new URL(request.url).searchParams.get("order_id") ?? "";
      const sn = links.find((l) => l.id === id)?.sn ?? "";
      const answer = options.answer ? options.answer(request, sn) : { body: detail(Number(id), sn) };
      return { status: answer.status ?? 200, text: async () => JSON.stringify(answer.body) };
    },
    pathname: () => "/portal/sale/order",
    pause: async () => undefined,
    random: () => 0,
    orderLinks: () => links,
    orderListEmpty: () => options.empty === true,
    nextOrderPage: () => false,
    ...(options.permissionPage !== undefined ? { permissionDeniedVisible: () => options.permissionPage === true } : {}),
  };
  return { env: e, sent };
}

const LINKS = [link(7001, "2026-11-17"), link(7002, "2026-11-17"), link(7003, "2026-11-16")];
const IDS = /700[123]|FAKE700/;

describe("O1/O3: a kept card answer without orders no longer hides the order links", () => {
  it("the scrubbed DRM card answer holds no order", () => {
    expect(cardsHoldOrders(DRM_CARDS)).toBe(false);
    expect(cardsHoldOrders(undefined)).toBe(false);
    expect(cardsHoldOrders({ code: 0, data: { list: [{ order_id: 1, order_sn: "261117X1" }] } })).toBe(true);
  });

  it("links shown + a kept card answer without orders: each order is read with get_one_order and mapped", async () => {
    const h = env({ links: LINKS, templates: { order_cards: { query: {}, body: {}, lastResponse: DRM_CARDS } } });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent.map((r) => new URL(r.url).pathname)).toEqual(Array(3).fill("/api/v3/order/get_one_order"));
    expect(mapOrderLines(outcome.responses, NOW).rows).toHaveLength(3);
  });

  it("no order link and a card answer without orders: done, 'no_ids_from_page', reported as the step", async () => {
    const h = env({ templates: { order_cards: { query: {}, body: {}, lastResponse: DRM_CARDS } } });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, h.env);
    expect(outcome).toMatchObject({ status: "done", detail: "no_ids_from_page" });
    expect(h.sent).toHaveLength(0);
    expect(jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", "no_ids_from_page", outcome.responses)).toBe(
      "error:orders:0_rows:no_ids_from_page",
    );
  });

  it("detail reads reuse the page's own order-detail headers, else the list page's order-service headers, never invented ones", async () => {
    const cards: Template = { query: { x: "1" }, body: {}, headers: { "SC-FE-VER": "v-fake", "Content-Type": "application/json", Cookie: "c" }, lastResponse: DRM_CARDS };
    const fromList = env({ links: LINKS.slice(0, 1), templates: { order_cards: cards } });
    await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, fromList.env);
    expect(fromList.sent[0]!.headers).toEqual({ "SC-FE-VER": "v-fake" });
    expect(new URL(fromList.sent[0]!.url).searchParams.get("x")).toBeNull();

    const own = env({ links: LINKS.slice(0, 1), templates: { order_cards: cards, order_detail: { query: {}, headers: { "X-Own": "1" } } } });
    await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, own.env);
    expect(own.sent[0]!.headers).toEqual({ "X-Own": "1" });

    const none = env({ links: LINKS.slice(0, 1) });
    await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, none.env);
    expect(none.sent[0]!.headers).toEqual({});
  });
});

describe("O2: a 0-row orders run says which step, metadata only", () => {
  it("every get_one_order refused (http 200 + a Shopee code): detail_failed:<http|code>x<N>", async () => {
    const h = env({ links: LINKS, answer: () => ({ body: { code: 10002, message: "Tran Thi Fake 0911111111", data: null } }) });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, h.env);
    expect(outcome.status).toBe("done");
    expect(mapOrderLines(outcome.responses, NOW).rows).toEqual([]);
    const result = jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", outcome.detail ?? "", outcome.responses);
    expect(result).toBe("error:orders:0_rows:detail_failed:http_200_code_10002x3");
    expect(result).not.toMatch(IDS);
    expect(result).not.toMatch(/Tran|0911/);
  });

  it("http errors are named by status; the commonest refusal wins and N counts every refused answer", () => {
    const r = (status: number, body: unknown): ReaderResponse => ({ endpoint: "order_detail", url: "u", status, body, capturedAt: NOW, source: "replay" });
    expect(zeroRowsStep("orders", [r(500, null), r(500, null), r(502, null)])).toBe("detail_failed:http_500x3");
  });

  it("answers that came back but hold no order: no_mappable_order", async () => {
    const h = env({ links: LINKS, answer: () => ({ body: { code: 0, data: { something_else: true } } }) });
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, h.env);
    expect(jobOutcome("orders", { order_lines: "ignored" }, "", outcome.detail ?? "", outcome.responses)).toBe("error:orders:0_rows:no_mappable_order");
  });

  it("nothing read: no_list_answer; nothing read because of a partial stop: that note; drift stays drift", () => {
    expect(jobOutcome("orders", { order_lines: "ignored" }, "", "", [])).toBe("error:orders:0_rows:no_list_answer");
    expect(jobOutcome("orders", { order_lines: "ignored" }, "", "partial:budget", [])).toBe("error:orders:0_rows:partial:budget");
    expect(jobOutcome("orders", { order_lines: "drift" }, "", "", [])).toBe("error:orders:0_rows:drift");
  });

  it("a partial note is kept beside the step", () => {
    const refused: ReaderResponse = { endpoint: "order_detail", url: "u", status: 200, body: { code: 7, data: null }, capturedAt: NOW, source: "replay" };
    expect(jobOutcome("orders", { order_lines: "ignored" }, "", "partial:pager", [refused])).toBe("error:orders:0_rows:detail_failed:http_200_code_7x1|partial:pager");
  });

  it("order_income that posted nothing says why too; a posted one is unchanged", () => {
    expect(jobOutcome("order_income", { order_income: "ignored" }, "order_income=ignored", "", [])).toBe("error:order_income:0_rows:no_income_answer");
    expect(jobOutcome("order_income", { order_income: "drift" }, "order_income=drift", "", [])).toBe("error:order_income:0_rows:drift");
    expect(jobOutcome("order_income", { order_income: "posted" }, "order_income=posted", "", [])).toBe("done:order_income=posted");
  });

  it("the popup shows the step", () => {
    expect(outcomeStatus("error:orders:0_rows:detail_failed:http_200_code_10002x3")).toEqual({
      status: "Chưa đọc được đơn nào (detail_failed:http_200_code_10002x3): sẽ thử lại lần sau",
      tone: "warn",
    });
    expect(outcomeStatus("error:order_search:http_500").status).toBe("Lỗi khi đọc: sẽ thử lại lần sau");
  });
});

describe("O5: a day with truly no order is read and empty, not an error", () => {
  it("no order since the job's day, or the list's empty state: done:order_lines=empty, counted as read", async () => {
    const old = env({ links: [link(1, "2026-10-01")] });
    const none = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, old.env);
    expect(none.detail).toBe("no_new_orders");
    expect(jobOutcome("orders", { order_lines: "ignored" }, "order_lines=ignored", "no_new_orders", none.responses)).toBe("done:order_lines=empty");
    const empty = await runReaderJob({ id: "orders", sinceDay: "2026-11-15" }, env({ empty: true }).env);
    expect(jobOutcome("orders", { order_lines: "ignored" }, "", empty.detail ?? "", empty.responses)).toBe("done:order_lines=empty");
    expect(todaysPagesAllRead({ lastRun: { day: "2026-11-18", at: "", outcomes: { orders: "done:order_lines=empty", order_income: "no_orders" } } } as never, "2026-11-18")).toBe(true);
    expect(outcomeStatus("done:order_lines=empty")).toEqual({ status: "Đã đọc: không có số liệu mới", tone: "muted" });
  });
});

describe("O4: an account without the Tài chính right is blocked:no_permission, never silent", () => {
  const INCOME = { code: 0, data: { sections: [{ items: [{ name: "Số tiền cuối cùng", amount: 90_000 }] }] } };
  const income = (over: Partial<Template> = {}): Template => ({ query: { order_id: "8001" }, lastResponse: INCOME, ...over });

  it("Seller Centre's permission page: blocked_no_permission (page), nothing sent", async () => {
    const h = env({ templates: {}, permissionPage: true });
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["8001", "8002"] }, h.env);
    expect(outcome).toMatchObject({ status: "blocked_no_permission", detail: "page" });
    expect(h.sent).toHaveLength(0);
  });

  it("the page's own income call refused with 403: blocked_no_permission (http_403)", async () => {
    const h = env({ templates: { order_income_components: { query: { order_id: "8001" }, lastStatus: 403, lastCode: "10013" } } });
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["8001", "8002"] }, h.env);
    expect(outcome).toMatchObject({ status: "blocked_no_permission", detail: "http_403_code_10013" });
    expect(h.sent).toHaveLength(0);
  });

  it("a replayed income read refused with a JSON 403 stops the job as no_permission; the anti-fraud 403 stays a CAPTCHA", async () => {
    const denied = env({ templates: { order_income_components: income() }, answer: () => ({ status: 403, body: { error: 10013, message: "no permission" } }) });
    expect(await runReaderJob({ id: "order_income", orderIds: ["8001", "8002", "8003"] }, denied.env)).toMatchObject({
      status: "blocked_no_permission",
      detail: "http_403_code_10013",
    });
    expect(denied.sent).toHaveLength(1);
    const fraud = env({ templates: { order_income_components: income() }, answer: () => ({ status: 403, body: { error: 90309999 } }) });
    expect((await runReaderJob({ id: "order_income", orderIds: ["8001", "8002"] }, fraud.env)).status).toBe("blocked_captcha");
  });

  it("a Shopee 'no permission' code on the page's own answer: blocked_no_permission", async () => {
    const h = env({ templates: { order_income_components: income({ lastResponse: { code: 403001, message: "Bạn không có quyền truy cập" } }) } });
    expect(await runReaderJob({ id: "order_income", orderIds: ["8001"] }, h.env)).toMatchObject({ status: "blocked_no_permission", detail: "http_200_code_403001" });
  });

  it("only a refusal with permission wording counts; a bare 403 to a replay stays the rate stop", () => {
    expect(isPermissionRefusal(403, { error: 1, message: "No permission" })).toBe(true);
    expect(isPermissionRefusal(403, { error: 1 })).toBe(false);
    expect(isPermissionRefusal(403, { error: 90309999, message: "permission" })).toBe(false);
    expect(isPermissionRefusal(403, null)).toBe(false);
    expect(isPermissionRefusal(200, { code: 5, message: "session expired" })).toBe(false);
    expect(isPermissionRefusal(200, { code: 0, message: "permission" })).toBe(false);
  });

  it("no order key in the page's own income call: nothing replayed, said as no_order_key / partial:no_order_key", async () => {
    const keyless = env({ templates: { order_income_components: { query: { x: "1" }, lastStatus: 500 } } });
    const none = await runReaderJob({ id: "order_income", orderIds: ["8001", "8002"] }, keyless.env);
    expect(none).toMatchObject({ status: "done", detail: "no_order_key" });
    expect(keyless.sent).toHaveLength(0);
    expect(jobOutcome("order_income", { order_income: "ignored" }, "", none.detail ?? "", none.responses)).toBe("error:order_income:0_rows:no_order_key");
    const opened = env({ templates: { order_income_components: { query: { x: "1" }, lastResponse: INCOME } } });
    const some = await runReaderJob({ id: "order_income", orderIds: ["8001", "8002"] }, opened.env);
    expect(some).toMatchObject({ status: "done", detail: "partial:no_order_key" });
    expect(opened.sent).toHaveLength(0);
  });

  it("the popup line", () => {
    expect(outcomeStatus("blocked:no_permission|http_403")).toEqual({ status: NO_PERMISSION_LINE, tone: "warn" });
    expect(NO_PERMISSION_LINE).toBe("Cần quyền Tài chính Seller Centre");
  });
});
