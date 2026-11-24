// @vitest-environment jsdom
// Connector 0.3.34 (batch-1124-hotfix, Track C). Tick 23/11 17:50Z said only
// `orders: error:orders:0_rows:rejected`; the order page said `income_final_not_shown` and
// `page_lines_unmatched` with no detail. This file pins:
//   C-H1 a refused post says why (`rejected:<gateway code>` / `rejected:order_ref_key` / `rejected:raw_order_id`);
//   C-H2 no post spans more than 31 days, and the orders job drops lines placed before its window;
//   C-H3 a card keyed by order_id and its detail keyed by order_sn are one set of lines, under one key;
//   C-H4 an income label is its own text (the tooltip's svg <style> and popper text are not);
//   C-H5 the order page waits for its product lines too, and a miss says page vs answer counts.
// The order page DOM follows the read-only capture of 24/11 (structure and labels only). Every
// amount, id and SKU here is synthetic.
import { describe, expect, it } from "vitest";
import { Connector, rejectedFor, type Tabs } from "../src/platforms/shopee/background/connector";
import { jobOutcome, outcomeRank } from "../src/platforms/shopee/background/scheduler";
import { GatewayClient, GatewayError, type IngestBody, type TokenInfo } from "../src/platforms/shopee/ingest/client";
import type { Mapped } from "../src/platforms/shopee/map";
import { incomeItemsIn, ownLabelText, pageItemsIn } from "../src/platforms/shopee/order-page-dom";
import { RAW_ORDER_ID } from "../src/platforms/shopee/affiliate-map";
import { mapOrderIncome, mapOrderLines, trimOrderCards, trimOrderDetail } from "../src/platforms/shopee/orders-map";
import { periodDays, splitByPeriod, withinReadWindow } from "../src/platforms/shopee/post-period";
import { INCOME_NOT_SHOWN, pollingWaitFor, type ReaderEnv, type ReaderResponse, runReaderJob } from "../src/platforms/shopee/reader";
import { mapReaderJob } from "../src/platforms/shopee/reader-map";
import { Pacer } from "../src/platforms/shopee/runner";
import { outcomeStatus } from "../src/platforms/shopee/popup/guide";
import { dayMinus } from "../src/platforms/shopee/background/scheduler";
import { gmt7DateStart } from "../src/core/time";

const SC = "https://banhang.shopee.vn";
// 2026-11-24 10:00 GMT+7
const NOW = Date.UTC(2026, 10, 24, 3, 0, 0);
const TODAY = "2026-11-24";
const KEY = "cd".repeat(32); // synthetic, low entropy on purpose
const TOKEN: TokenInfo = { token: "jci_x", token_id: "t1", shop_id: "s1", platform: "shopee", expires_at: "2027-01-10T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };

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

class FakeClient extends GatewayClient {
  posts: { dataset: string; body: IngestBody }[] = [];
  failWith: GatewayError | undefined;
  keyAnswer: () => Promise<unknown> = async () => ({ order_ref_key: KEY, algorithm: "HMAC-SHA256", key_version: 1 });
  async orderRefKey() {
    return this.keyAnswer();
  }
  async post(_token: string, dataset: string, body: IngestBody) {
    if (this.failWith) throw this.failWith;
    this.posts.push({ dataset, body });
    return { rows: body.rows.length, duplicate: false };
  }
}
const tabs: Tabs = { sellerCentreTabs: async () => [], send: async () => undefined };

function connectorWith(client: GatewayClient) {
  const storage = new MemoryStorage();
  storage.data.token = TOKEN;
  return { storage, connector: new Connector({ storage, client, tabs, version: "0.3.34", now: () => NOW }) };
}

/** Synthetic order lines, one per day from `first` to `last` (already hashed: no raw order id). */
function linesOver(first: string, days: number): Mapped {
  const rows = Array.from({ length: days }, (_, i) => {
    const day = dayMinus(first, -i);
    return { order_ref: `ref${i}`, line_no: 0, ordered_at: `${day}T09:00:00`, status: "completed", qty: 1, original_price: 1000, deal_price: 1000, seller_subsidy: 0 };
  });
  const last = dayMinus(first, -(days - 1));
  return { dataset: "order_lines", endpoint: "order/get_one_order", orderType: null, granularity: "period", date: last, periodStart: first, rows, drift: null };
}

// -- C-H1 ----------------------------------------------------------------------------------------

describe("C-H1: a refused post says why", () => {
  it("a 4xx names the gateway's code; one without a code names its status", () => {
    expect(rejectedFor(new GatewayError(422, "period_too_long"))).toBe("rejected:period_too_long");
    expect(rejectedFor(new GatewayError(422, "http_error"))).toBe("rejected:http_422");
  });

  it("the gateway's 422 body {detail:{code}} reaches the outcome through the real client", async () => {
    const client = new GatewayClient(async () => new Response(JSON.stringify({ detail: { code: "invalid_rows", errors: [{ loc: ["rows", 0], msg: "x" }] } }), { status: 422 }));
    const { connector, storage } = connectorWith(client);
    expect(await connector.submit(linesOver("2026-11-20", 2), NOW)).toBe("rejected:invalid_rows");
    expect((storage.data.lastError as { code: string }).code).toBe("invalid_rows");
    // a pydantic 422 (detail is a list, no code): the status
    const bare = connectorWith(new GatewayClient(async () => new Response(JSON.stringify({ detail: [{ msg: "x" }] }), { status: 422 })));
    expect(await bare.connector.submit(linesOver("2026-11-20", 2), NOW)).toBe("rejected:http_422");
  });

  it("each gateway code of the ingest gateway is carried as is", async () => {
    for (const code of ["invalid_rows", "period_too_long", "granularity_mismatch"]) {
      const client = new FakeClient(async () => new Response("{}"));
      client.failWith = new GatewayError(422, code);
      const { connector } = connectorWith(client);
      expect(await connector.submit(linesOver("2026-11-20", 2), NOW)).toBe(`rejected:${code}`);
    }
  });

  it("no order_ref key: rejected:order_ref_key; a raw order id: rejected:raw_order_id", async () => {
    const client = new FakeClient(async () => new Response("{}"));
    client.keyAnswer = async () => {
      throw new GatewayError(503, "order_ref_key_not_configured");
    };
    const { connector } = connectorWith(client);
    const detail = orderDetail({ id: 7001, sn: "261120KEYLESS1", day: "2026-11-20" });
    expect(await connector.postReader({ id: "orders", sinceDay: "2026-11-10" }, [detail])).toEqual({ order_lines: "rejected:order_ref_key" });
    const raw = { ...linesOver("2026-11-20", 1), rows: [{ [RAW_ORDER_ID]: "X1", line_no: 0 }] };
    expect(await connector.submit(raw, NOW)).toBe("rejected:raw_order_id");
    expect(client.posts).toEqual([]);
  });

  it("the scheduler's outcome shows the reason, and still ranks it as a failure", () => {
    expect(jobOutcome("orders", { order_lines: "rejected:period_too_long" }, "order_lines=rejected:period_too_long", "")).toMatch(/^error:orders:0_rows:rejected:period_too_long/);
    expect(outcomeRank("done:order_lines=rejected:period_too_long")).toBe(3);
    expect(outcomeRank("done:order_lines=rejected")).toBe(3);
    expect(outcomeRank("done:order_lines=posted")).toBe(0);    // a read page's summary keeps the plain head Juli's reader_status reads ("=rejected"), the reason follows it
    const ads = jobOutcome("ads", { "ads_campaign_daily:2026-11-23": "rejected:invalid_rows", "ads_campaign_daily:2026-11-22": "posted" }, "ads_campaign_daily:2026-11-23=rejected,ads_campaign_daily:2026-11-22=posted", "");
    expect(ads).toBe("done:ads_campaign_daily:2026-11-23=rejected,ads_campaign_daily:2026-11-22=posted|rejected:invalid_rows");
    expect(outcomeRank(ads)).toBe(3);
    // the popup still shows a reasoned refusal as "not sent"
    expect(outcomeStatus("done:order_lines=rejected:period_too_long").tone).toBe("warn");
  });
});

// -- C-H2 ----------------------------------------------------------------------------------------

describe("C-H2: a post never spans more than 31 days", () => {
  it("a 40-day set posts as periods of at most 31 days, every row inside its own period, none lost", async () => {
    const client = new FakeClient(async () => new Response("{}"));
    const { connector } = connectorWith(client);
    const forty = linesOver("2026-10-15", 40);
    expect(periodDays(forty.periodStart!, forty.date)).toBe(40);
    expect(await connector.submit(forty, NOW)).toBe("posted");
    expect(client.posts.length).toBe(2);
    for (const { body } of client.posts) {
      expect(periodDays(body.period.start, body.period.end)).toBeLessThanOrEqual(31);
      for (const row of body.rows) {
        const day = String(row.ordered_at).slice(0, 10);
        expect(day >= body.period.start && day <= body.period.end).toBe(true);
      }
    }
    expect(client.posts.map((p) => p.body.period)).toEqual([
      { start: "2026-10-15", end: "2026-11-14", granularity: "period" },
      { start: "2026-11-15", end: "2026-11-23", granularity: "period" },
    ]);
    expect(client.posts.reduce((n, p) => n + p.body.rows.length, 0)).toBe(40);
  });

  it("a set within 31 days, a day post and rows without a day of their own are not split", () => {
    expect(splitByPeriod(linesOver("2026-10-24", 31))).toHaveLength(1);
    const day: Mapped = { ...linesOver("2026-11-20", 1), granularity: "day" };
    expect(splitByPeriod(day)).toEqual([day]);
    const totals: Mapped = { ...linesOver("2026-08-20", 40), rows: [{ campaign_id: "1", spend: 1 }] };
    expect(splitByPeriod(totals)).toEqual([totals]);
  });

  it("withinReadWindow drops the lines placed before sinceDay and starts the period at the first kept day", () => {
    const kept = withinReadWindow(linesOver("2026-10-15", 40), "2026-10-25");
    expect(kept.rows.every((r) => String(r.ordered_at) >= "2026-10-25")).toBe(true);
    expect(kept.rows).toHaveLength(30);
    expect(kept.periodStart).toBe("2026-10-25");
  });

  it("the orders job: card-list lines older than its window are not posted; the rest fits one post", async () => {
    const client = new FakeClient(async () => new Response("{}"));
    const { connector } = connectorWith(client);
    const sinceDay = dayMinus(TODAY, 30);
    const old = orderDetail({ id: 7101, sn: "261015OLDORDER1", day: dayMinus(TODAY, 40) });
    const fresh = orderDetail({ id: 7102, sn: "261120NEWORDER1", day: dayMinus(TODAY, 2) });
    const edge = orderDetail({ id: 7103, sn: "261025EDGEORDR", day: sinceDay });
    expect(await connector.postReader({ id: "orders", sinceDay }, [old, fresh, edge])).toEqual({ order_lines: "posted" });
    expect(client.posts).toHaveLength(1);
    const body = client.posts[0]!.body;
    expect(body.rows).toHaveLength(2);
    expect(body.period.start).toBe(sinceDay);
    expect(periodDays(body.period.start, body.period.end)).toBeLessThanOrEqual(31);
  });

  it("every line before the window: nothing sent, and the job is read with nothing new (not an error)", async () => {
    const client = new FakeClient(async () => new Response("{}"));
    const { connector } = connectorWith(client);
    const old = orderDetail({ id: 7201, sn: "261001OLDORDER2", day: dayMinus(TODAY, 45) });
    const posted = await connector.postReader({ id: "orders", sinceDay: dayMinus(TODAY, 30) }, [old]);
    expect(posted).toEqual({ order_lines: "empty" });
    expect(client.posts).toEqual([]);
    expect(jobOutcome("orders", posted, "order_lines=empty", "")).toBe("done:order_lines=empty");
  });
});

// -- C-H3 ----------------------------------------------------------------------------------------

function orderDetail(o: { id: number; sn?: string; day: string; items?: unknown[] }): ReaderResponse {
  const body = trimOrderDetail({
    code: 0,
    data: {
      order_id: o.id,
      ...(o.sn ? { order_sn: o.sn } : {}),
      status_info: { status: "Chờ lấy hàng" },
      create_time: gmt7DateStart(o.day) + 9 * 3600,
      complete_time: 0,
      order_items: o.items ?? [{ item_id: 9001, model_id: 9101, amount: 1, order_price: "100000", item_model: { sku: "SKU-T1", model_id: 9101 } }],
    },
  });
  return { endpoint: "order_detail", url: "u", status: 200, body, capturedAt: NOW, source: "replay", orderId: String(o.id) };
}

describe("C-H3: a card (order_id) and its detail (order_sn) are one order", () => {
  const CREATED = gmt7DateStart("2026-11-23") + 9 * 3600;
  // the card names the order by order_id only, its line a combo parent with no SKU
  const cards: ReaderResponse = {
    endpoint: "order_cards",
    url: "u",
    status: 200,
    capturedAt: NOW,
    source: "page",
    body: trimOrderCards({ code: 0, data: { list: [{ order_id: 6001, create_time: CREATED, status: "Chờ lấy hàng", items: [{ amount: 1, order_price: 19_000_000_000, item_price: 19_000_000_000, bundle_deal_id: 77 }] }] } }),
  };
  const detail = orderDetail({
    id: 6001,
    sn: "261123ONEKEY01",
    day: "2026-11-23",
    items: [
      {
        amount: 1,
        order_price: "190000",
        bundle_deal_id: 77,
        bundle_deal_model: [
          { item_id: 9001, model_id: 9101, amount: 1, order_price: "100000", item_model: { sku: "SKU-A1", model_id: 9101 } },
          { item_id: 9003, model_id: 9301, amount: 1, order_price: "90000", item_model: { sku: "SKU-C1", model_id: 9301 } },
        ],
      },
    ],
  });

  it("the detail's lines replace the card's under the card's key: one set of lines, one order_ref", () => {
    for (const responses of [[cards, detail], [detail, cards]]) {
      const rows = mapOrderLines(responses, NOW).rows;
      expect(rows.map((r) => [r[RAW_ORDER_ID], r.variation_sku])).toEqual([
        ["6001", "SKU-A1"],
        ["6001", "SKU-C1"],
      ]);
    }
  });

  it("hashed, both lines carry the same order_ref as the card's line would", async () => {
    const client = new FakeClient(async () => new Response("{}"));
    const { connector } = connectorWith(client);
    await connector.postReader({ id: "orders", sinceDay: "2026-11-20" }, [cards]);
    await connector.postReader({ id: "orders", sinceDay: "2026-11-20" }, [cards, detail]);
    const [cardPost, detailPost] = client.posts.map((p) => p.body.rows);
    expect(new Set(detailPost!.map((r) => r.order_ref))).toEqual(new Set([cardPost![0]!.order_ref]));
    expect(detailPost).toHaveLength(2);
  });
});

// -- C-H4 ----------------------------------------------------------------------------------------

const TOOLTIP = (text: string) =>
  `<div class="eds-popover eds-popover--light payment-tooltip"><div class="eds-popover__ref"><svg viewBox="0 0 16 16"><style>.cls-1{fill-rule:evenodd;}</style><title>question</title><path class="cls-1" d="M0 0"/></svg></div>` +
  `<div class="payment-detail-tooltip-popper">${text}</div></div>`;
const item = (label: string, value: string, opts: { cls?: string; tip?: string } = {}) =>
  `<div class="income-item${opts.cls ? ` ${opts.cls}` : ""}"><div class="income-label"><div class="income-label-text">${label} ${opts.tip !== undefined ? TOOLTIP(opts.tip) : ""}</div></div><div class="income-value">${value}</div><div></div></div>`;
const SUB = "income-subtotal strong";
/** The 14 rows of a completed order's "Doanh thu" block, in page order (capture 24/11; amounts made up). */
const ROWS: [string, string, { cls?: string; tip?: string }?][] = [
  ["Tổng tiền sản phẩm", "₫200.000", { cls: SUB }],
  ["Giá sản phẩm", "₫200.000"],
  ["Tổng phí vận chuyển", "₫0", { cls: SUB }],
  ["Phí vận chuyển Người mua trả", "₫10.000"],
  ["Phí vận chuyển thực tế", "-₫30.000"],
  ["Phí vận chuyển được trợ giá từ Shopee", "₫20.000"],
  ["Phụ phí", "-₫40.000", { cls: SUB }],
  ["Phí cố định", "-₫20.000", { tip: "Phí cố định áp dụng theo ngành hàng" }],
  ["Phí dịch vụ PiShip", "-₫1.000"],
  ["Phí Dịch Vụ", "-₫12.000", { tip: `Phí hạ tầng<span class="income-value">-₫3.000</span> Voucher Xtra<span>-₫9.000</span>` }],
  ["Phí xử lý giao dịch", "-₫5.000", { tip: "Phí thanh toán" }],
  ["Phí hoa hồng Tiếp thị liên kết", "-₫2.000", { tip: "Hoa hồng cho người tiếp thị" }],
  ["Tổng phụ dịch vụ giá trị gia tăng cho người mua", "₫0", { cls: SUB }],
  ["Doanh Thu Đơn Hàng", "₫160.000", { cls: `${SUB} highlighted`, tip: "Số tiền người bán nhận được" }],
];
const incomeHtml = (rows = ROWS) => `<div class="income-container">${rows.map(([l, v, o]) => item(l, v, o)).join("")}</div>`;

function pageEnv(onSleep?: (elapsed: number) => void): ReaderEnv {
  let clock = NOW;
  const sleep = async (ms: number) => {
    clock += ms;
    onSleep?.(clock - NOW);
  };
  return {
    origin: SC,
    pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
    now: () => clock,
    session: () => ({}),
    hasSession: () => true,
    template: () => undefined,
    waitFor: pollingWaitFor(sleep, () => clock),
    fetch: async () => {
      throw new Error("nothing is requested");
    },
    orderPageIncome: () => incomeItemsIn(document),
    orderPageItems: () => pageItemsIn(document),
  };
}

describe("C-H4: an income label is the label's own text", () => {
  it("textContent leaks the tooltip (the old cause); ownLabelText does not", () => {
    document.body.innerHTML = incomeHtml();
    const label = document.querySelectorAll(".income-label-text")[13]!;
    expect(label.textContent).toContain(".cls-1{fill-rule:evenodd;}");
    expect(ownLabelText(label)).toBe("Doanh Thu Đơn Hàng");
  });

  it("all 14 labels parse, tooltip rows included; each value is its row's own, the final amount is found", () => {
    document.body.innerHTML = incomeHtml();
    const items = incomeItemsIn(document);
    expect(items.map((i) => i.name)).toEqual(ROWS.map(([l]) => l));
    expect(items.find((i) => i.name === "Phí Dịch Vụ")!.amount).toBe(-12_000);
    const answer: ReaderResponse = { endpoint: "order_income_components", url: "u", status: 200, body: { code: 0, data: { items } }, capturedAt: NOW, source: "page", orderId: "8001", orderSn: "261124INCOME01" };
    const mapped = mapOrderIncome([answer], NOW);
    expect(mapped.drift).toBeNull();
    expect(mapped.rows[0]).toMatchObject({ payout: 160_000, fee_fixed: 20_000, fee_service: 12_000, fee_payment: 5_000, affiliate_commission: 2_000, fee_piship: 1_000, product_price: 200_000 });
  });

  it("the order page job posts the income of a page whose labels carry tooltips", async () => {
    document.body.innerHTML = incomeHtml();
    const job = { id: "order_income" as const, orderIds: ["8001"], orderSns: ["261124INCOME01"], incomeFor: [true] };
    const outcome = await runReaderJob(job, pageEnv());
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBeUndefined();
    const [income] = mapReaderJob(job, outcome.responses, NOW);
    expect(income!.rows[0]).toMatchObject({ payout: 160_000 });
  });

  it("a miss carries the row count and the first three labels, never an amount", async () => {
    document.body.innerHTML = incomeHtml(ROWS.slice(0, 13));
    const outcome = await runReaderJob({ id: "order_income", orderIds: ["8001"], orderSns: [""], incomeFor: [true] }, pageEnv());
    expect(outcome.detail).toBe(`${INCOME_NOT_SHOWN}:13:tong tien san pham/gia san pham/tong phi van chuyen`);
    expect(outcome.detail).not.toMatch(/\d{3}/);
  });
});

// -- C-H5 ----------------------------------------------------------------------------------------

describe("C-H5: the order page waits for its product lines", () => {
  /** A stored get_one_order answer: one combo parent (no SKU) with two child lines. */
  const combo = () =>
    trimOrderDetail({
      code: 0,
      data: {
        order_id: 8101,
        order_sn: "261124COMBO001",
        status_info: { status: "Hoàn thành" },
        create_time: Math.floor(NOW / 1000) - 86_400,
        complete_time: Math.floor(NOW / 1000),
        order_items: [{ amount: 1, order_price: "160000", bundle_deal_id: 77, item_list: [{ amount: 1 }, { amount: 1 }] }],
      },
    });
  const LINE = `<div class="product-item product"><div class="product-image"></div><div class="product-detail"><div class="product-name">Sản phẩm mẫu</div><div class="product-labels"></div><div class="product-meta"><div>Phân loại: Combo mẫu</div><div>SKU phân loại: SKU-COMBO-1</div></div></div><div>1</div><div>₫160.000</div></div>`;
  const job = { id: "order_income" as const, orderIds: ["8101"], orderSns: ["261124COMBO001"], incomeFor: [true], fixBodies: [combo()], fixLast: [false] };

  it("income drawn first, the one page line 3 s later: the line is read (one line, the page's SKU)", async () => {
    document.body.innerHTML = incomeHtml();
    let drawn = false;
    const env = pageEnv((elapsed) => {
      if (!drawn && elapsed >= 3_000) {
        drawn = true;
        document.body.insertAdjacentHTML("afterbegin", LINE);
      }
    });
    const outcome = await runReaderJob(job, env);
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBeUndefined();
    const mapped = mapReaderJob(job, outcome.responses, NOW);
    expect(mapped.map((m) => [m.dataset, m.rows.length])).toEqual([
      ["order_income", 1],
      ["order_lines", 1],
    ]);
    expect(mapped[1]!.rows[0]).toMatchObject({ variation_sku: "SKU-COMBO-1", promo_kind: "bundle" });
  });

  it("lines never drawn: the note says page lines vs the answer's lines (parent + children)", async () => {
    document.body.innerHTML = incomeHtml();
    const outcome = await runReaderJob(job, pageEnv());
    expect(outcome.detail).toBe("page_lines_unmatched:page_0:answer_1+2");
  });
});
