import { describe, expect, it } from "vitest";
import {
  blockedPath,
  isPasswordPrompt,
  buildReaderRequest,
  classify,
  dayBounds,
  findList,
  type FetchedReaderResponse,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  replayHeaders,
  runReaderJob,
  type Template,
  totalOf,
} from "../src/shopee/reader";
import { TRAFFIC_MAX_REQUESTS_PER_JOB } from "../src/config";
import { gmt7DateStart } from "../src/shopee/time";
import { Pacer } from "../src/shopee/runner";
import type { ReaderEndpoint } from "../src/shopee/endpoints";
import adsHome from "./fixtures/readers/ads_homepage.json";
import adsGraph from "./fixtures/readers/ads_time_graph.json";
import campaignInfo from "./fixtures/readers/campaign_info.json";
import healthConfigs from "./fixtures/readers/health_metric_configs.json";
import healthList from "./fixtures/readers/health_metric_list.json";
import healthOverview from "./fixtures/readers/health_overview.json";
import products1 from "./fixtures/readers/product_list.json";
import products2 from "./fixtures/readers/product_list_page2.json";
import trafficDetails from "./fixtures/readers/traffic_details.json";
import vouchers from "./fixtures/readers/voucher_list.json";

const SC = "https://banhang.shopee.vn";

interface Harness {
  env: ReaderEnv;
  sent: ReaderRequest[];
  sleeps: number[];
}

type Handler = (request: ReaderRequest, index: number) => { status?: number; body?: unknown; text?: string } | "network";

function harness(
  templates: Partial<Record<ReaderEndpoint, Template>>,
  handler: Handler,
  options: { session?: boolean; captcha?: () => boolean; pathname?: string } = {},
): Harness {
  let clock = 1_000_000;
  const sent: ReaderRequest[] = [];
  const sleeps: number[] = [];
  const sleep = async (ms: number) => {
    sleeps.push(ms);
    clock += ms;
  };
  const now = () => clock;
  const env: ReaderEnv = {
    origin: SC,
    pacer: new Pacer({ sleep, now, random: () => 0 }),
    now,
    session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
    hasSession: () => options.session !== false,
    template: (endpoint) => templates[endpoint],
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      const index = sent.length;
      sent.push(request);
      const answer = handler(request, index);
      if (answer === "network") throw new Error("offline");
      return { status: answer.status ?? 200, text: async () => answer.text ?? JSON.stringify(answer.body ?? null) };
    },
    captchaVisible: options.captcha,
    pathname: () => options.pathname ?? "/portal/x",
  };
  return { env, sent, sleeps };
}

describe("buildReaderRequest", () => {
  it("GET: the page's query plus overrides plus the session params; the public url has no session", () => {
    const request = buildReaderRequest(
      SC,
      "product_list",
      { query: { page_number: "1", page_size: "24", list_type: "live_all", need_ads: "true" }, headers: { "x-sample": "1", Cookie: "no", "sec-fetch-mode": "cors" } },
      { query: { page_number: "3" } },
      { SPC_CDS: "s", SPC_CDS_VER: "2" },
    );
    const url = new URL(request.url);
    expect(url.pathname).toBe("/api/v3/opt/mpsku/list/v2/get_product_list");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      page_number: "3",
      page_size: "24",
      list_type: "live_all",
      need_ads: "true",
      SPC_CDS: "s",
      SPC_CDS_VER: "2",
    });
    expect(request.publicUrl).not.toContain("SPC_CDS");
    expect(request.method).toBe("GET");
    expect(request.headers).toEqual({ "x-sample": "1" });
    expect(request.body).toBeUndefined();
  });

  it("POST: the page's JSON body with only the overrides changed; json content type", () => {
    const template: Template = {
      query: {},
      body: { start_time: 1, end_time: 2, filter_list: [{ k: "v" }], offset: 0, limit: 20, use_paid_gmv: false },
      headers: { "af-sample": "abc", "content-length": "99" },
    };
    const request = buildReaderRequest(SC, "ads_homepage", template, { body: { start_time: 10, end_time: 20 } }, { SPC_CDS: "s" });
    expect(request.method).toBe("POST");
    expect(JSON.parse(request.body as string)).toEqual({
      start_time: 10,
      end_time: 20,
      filter_list: [{ k: "v" }],
      offset: 0,
      limit: 20,
      use_paid_gmv: false,
    });
    expect(request.headers).toEqual({ "af-sample": "abc", "Content-Type": "application/json" });
  });

  it("POST without a template uses the given fallback body", () => {
    const request = buildReaderRequest(SC, "ads_homepage", undefined, { body: { offset: 0 } }, {}, { filter_list: [] });
    expect(JSON.parse(request.body as string)).toEqual({ filter_list: [], offset: 0 });
  });

  it("replayHeaders drops cookie-like and browser-set headers", () => {
    expect(replayHeaders({ Cookie: "a", Host: "h", "Content-Length": "1", Origin: "o", "Sec-Ch-Ua": "x", Accept: "application/json" })).toEqual({
      Accept: "application/json",
    });
  });
});

describe("classify and finders", () => {
  it("separates data, login wall, CAPTCHA and errors", () => {
    expect(classify(200, { code: 0, data: {} })).toBe("ok");
    expect(classify(200, { data: {} })).toBe("ok");
    expect(classify(200, null)).toBe("login");
    expect(classify(401, null)).toBe("login");
    expect(classify(403, { error: 90309999 })).toBe("captcha");
    expect(classify(403, null)).toBe("captcha");
    expect(classify(403, { error: 123 })).toBe("rate"); // P97: any other 403 stops every reader too
    expect(classify(200, { error: "error_not_login", msg: "" })).toBe("login");
    expect(classify(200, { code: 5, msg: "invalid param" })).toBe("error");
    expect(classify(429, {})).toBe("rate");
    expect(classify(200, { code: 429, msg: "" })).toBe("rate");
    expect(classify(200, { code: 7, msg: "Too many requests, please try again later" })).toBe("rate");
    expect(classify(200, { code: 7, msg: "Thao tác quá nhanh, thử lại sau" })).toBe("rate");
    expect(classify(500, {})).toBe("error");
  });

  it("finds a list by its element shape, total included", () => {
    const found = findList({ code: 0, data: { deep: { items: [{ voucher_id: 1 }] } } }, (o) => "voucher_id" in o);
    expect(found?.list).toHaveLength(1);
    expect(findList([{ metric_id: 1 }], (o) => "metric_id" in o)?.list).toHaveLength(1);
    expect(findList({ a: [] }, () => true)).toBeNull();
    expect(totalOf(products1)).toBe(3);
    expect(totalOf({ data: { total_count: "7" } })).toBe(7);
    expect(totalOf({ data: {} })).toBeUndefined();
  });

  it("recognises login and verification paths", () => {
    expect(blockedPath("/account/signin")).toBe("login");
    expect(blockedPath("/seller/login")).toBe("login");
    expect(blockedPath("/verify/captcha")).toBe("captcha");
    expect(blockedPath("/portal/marketing/pas/index")).toBeNull();
    expect(blockedPath("/portal/accounthealth")).toBeNull();
  });

  it("day bounds are GMT+7 midnight to 23:59:59", () => {
    expect(dayBounds("2026-11-02")).toEqual({ start_time: Date.UTC(2026, 10, 1, 17) / 1000, end_time: Date.UTC(2026, 10, 1, 17) / 1000 + 86399 });
  });
});

describe("products", () => {
  const template: Template = { query: { page_number: "1", page_size: "2", list_type: "live_all", need_ads: "true" } };

  it("pages with the page's own page_size until the total, paced at ≥ 2 s", async () => {
    const h = harness({ product_list: template }, (_, i) => ({ body: i === 0 ? products1 : products2 }));
    const outcome = await runReaderJob({ id: "products" }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent.map((r) => new URL(r.url).searchParams.get("page_number"))).toEqual(["1", "2"]);
    expect(h.sent.every((r) => new URL(r.url).searchParams.get("page_size") === "2")).toBe(true);
    expect(outcome.responses.map((r) => r.page)).toEqual([1, 2]);
    expect(h.sleeps.filter((ms) => ms >= 2000)).toHaveLength(1); // one gap, between the two requests
  });

  it("attaches the page's own campaign answer without replaying that request", async () => {
    const h = harness(
      { product_list: template, campaign_info: { query: {}, lastResponse: campaignInfo } },
      (_, i) => ({ body: i === 0 ? products1 : products2 }),
    );
    const outcome = await runReaderJob({ id: "products" }, h.env);
    expect(h.sent.every((r) => r.endpoint === "product_list")).toBe(true);
    const campaign = outcome.responses.find((r) => r.endpoint === "campaign_info");
    expect(campaign).toMatchObject({ source: "page", status: 200, body: campaignInfo });
  });

  it("stops on a short page and caps runaway paging", async () => {
    const h = harness({ product_list: { query: { page_size: "24" } } }, () => ({ body: products1 }));
    await runReaderJob({ id: "products" }, h.env);
    expect(h.sent).toHaveLength(1);
    const always = harness({ product_list: { query: { page_size: "1" } } }, (_, i) => ({
      body: { code: 0, data: { products: [{ id: 5000 + i, price_detail: {}, model_list: [] }] } },
    }));
    const outcome = await runReaderJob({ id: "products" }, always.env);
    expect(outcome.status).toBe("done");
    expect(always.sent.length).toBeLessThanOrEqual(40);
  });

  it("without the page's own call: needs_template (session seen) or needs_data_page (no session)", async () => {
    expect((await runReaderJob({ id: "products" }, harness({}, () => ({})).env)).status).toBe("needs_template");
    expect((await runReaderJob({ id: "products" }, harness({}, () => ({}), { session: false }).env)).status).toBe("needs_data_page");
  });
});

describe("ads", () => {
  const home: Template = {
    query: {},
    body: { start_time: 5, end_time: 6, filter_list: [{ sample: 1 }], offset: 0, limit: 1, use_paid_gmv: false },
    headers: { "x-sample": "h" },
  };
  const graph: Template = { query: {}, body: { agg_interval: 1, campaign_type: "all", start_time: 5, end_time: 6, need_roi_target_setting: true, filter_params: {} } };

  it("one day per call: day bounds in the body, offset paging by the page's limit, then the time graph", async () => {
    const h = harness({ ads_homepage: home, ads_time_graph: graph }, (request) => {
      if (request.endpoint === "ads_time_graph") return { body: adsGraph };
      const offset = JSON.parse(request.body as string).offset as number;
      return { body: { code: 0, data: { entry_list: adsHome.data.entry_list.slice(offset, offset + 1), total: 2 } } };
    });
    const outcome = await runReaderJob({ id: "ads", days: ["2026-11-02"] }, h.env);
    expect(outcome.status).toBe("done");
    const bounds = dayBounds("2026-11-02");
    const bodies = h.sent.map((r) => JSON.parse(r.body as string));
    expect(h.sent.map((r) => r.endpoint)).toEqual(["ads_homepage", "ads_homepage", "ads_time_graph"]);
    expect(bodies[0]).toMatchObject({ ...bounds, offset: 0, limit: 1, use_paid_gmv: false, filter_list: [{ sample: 1 }] });
    expect(bodies[1]).toMatchObject({ ...bounds, offset: 1 });
    expect(bodies[2]).toMatchObject({ ...bounds, agg_interval: 1, campaign_type: "all", filter_params: {} });
    expect(h.sent[0]!.headers["x-sample"]).toBe("h");
    expect(outcome.responses.every((r) => r.day === "2026-11-02")).toBe(true);
    expect(outcome.responses[0]!.usePaidGmv).toBe(false);
  });

  it("several days = several request sets, never one multi-day call", async () => {
    const h = harness({ ads_homepage: { ...home, body: { ...(home.body as object), limit: 20 } } }, () => ({ body: adsHome }));
    await runReaderJob({ id: "ads", days: ["2026-11-02", "2026-11-01"] }, h.env);
    const starts = h.sent.map((r) => JSON.parse(r.body as string).start_time);
    expect(starts).toEqual([dayBounds("2026-11-02").start_time, dayBounds("2026-11-01").start_time]);
    for (const request of h.sent) {
      const body = JSON.parse(request.body as string);
      expect(body.end_time - body.start_time).toBe(86399);
    }
  });

  it("with no homepage call seen, uses only the keys the recon recorded", async () => {
    const h = harness({}, () => ({ body: { code: 0, data: { entry_list: [] } } }));
    await runReaderJob({ id: "ads", days: ["2026-11-02"] }, h.env);
    const body = JSON.parse(h.sent[0]!.body as string);
    expect(Object.keys(body).sort()).toEqual(["end_time", "filter_list", "limit", "offset", "start_time", "use_paid_gmv"]);
    expect(h.sent.map((r) => r.endpoint)).toEqual(["ads_homepage"]); // no graph template -> no graph guess
  });

  it("a paid-orders page template is replayed as paid and flagged on the response", async () => {
    const h = harness({ ads_homepage: { ...home, body: { ...(home.body as object), limit: 20, use_paid_gmv: true } } }, () => ({ body: adsHome }));
    const outcome = await runReaderJob({ id: "ads", days: ["2026-11-02"] }, h.env);
    expect(JSON.parse(h.sent[0]!.body as string).use_paid_gmv).toBe(true);
    expect(outcome.responses[0]!.usePaidGmv).toBe(true);
  });
});

describe("vouchers and health", () => {
  it("vouchers: the page's own query paged by offset", async () => {
    const h = harness({ voucher_list: { query: { promotion_type: "0", offset: "0", limit: "1" } } }, (_, i) => ({
      body: { code: 0, data: { voucher_list: [{ voucher_id: 100 + i, name: "v", start_time: 1 }], total: 2 } },
    }));
    const outcome = await runReaderJob({ id: "vouchers" }, h.env);
    expect(h.sent.map((r) => Object.fromEntries(new URL(r.url).searchParams))).toMatchObject([
      { promotion_type: "0", offset: "0", limit: "1" },
      { promotion_type: "0", offset: "1", limit: "1" },
    ]);
    expect(outcome.responses).toHaveLength(2);
    const whole = harness({ voucher_list: { query: { limit: "20" } } }, () => ({ body: vouchers }));
    await runReaderJob({ id: "vouchers" }, whole.env);
    expect(whole.sent).toHaveLength(1);
  });

  it("health: three plain GETs, one at a time", async () => {
    const answers: Record<string, unknown> = {
      health_overview: healthOverview,
      health_metric_list: healthList,
      health_metric_configs: healthConfigs,
    };
    const h = harness({}, (request) => ({ body: answers[request.endpoint] }));
    const outcome = await runReaderJob({ id: "health" }, h.env);
    expect(h.sent.map((r) => r.endpoint)).toEqual(["health_overview", "health_metric_list", "health_metric_configs"]);
    expect(h.sent.every((r) => r.method === "GET")).toBe(true);
    expect(outcome.status).toBe("done");
  });
});

describe("stops", () => {
  const template: Template = { query: { page_size: "2" } };

  it("an HTML answer is a login wall: stop, keep what was read, send nothing more", async () => {
    const h = harness({ product_list: template }, (_, i) => (i === 0 ? { body: products1 } : { text: "<html>login</html>" }));
    const outcome = await runReaderJob({ id: "products" }, h.env);
    expect(outcome.status).toBe("blocked_login");
    expect(h.sent).toHaveLength(2);
  });

  it("403 anti-fraud is a CAPTCHA stop", async () => {
    const h = harness({ product_list: template }, () => ({ status: 403, body: { error: 90309999 } }));
    expect((await runReaderJob({ id: "products" }, h.env)).status).toBe("blocked_captcha");
    expect(h.sent).toHaveLength(1);
  });

  it("a CAPTCHA overlay or a verification path stops before any request", async () => {
    const overlay = harness({ product_list: template }, () => ({ body: products1 }), { captcha: () => true });
    expect((await runReaderJob({ id: "products" }, overlay.env)).status).toBe("blocked_captcha");
    expect(overlay.sent).toHaveLength(0);
    const redirected = harness({ product_list: template }, () => ({ body: products1 }), { pathname: "/account/signin" });
    expect((await runReaderJob({ id: "products" }, redirected.env)).status).toBe("blocked_login");
    expect(redirected.sent).toHaveLength(0);
  });

  it("an error code, a 500 or a network failure ends the job as an error, not a block", async () => {
    for (const answer of [{ body: { code: 5, msg: "invalid" } }, { status: 500 }, "network" as const]) {
      const h = harness({ product_list: template }, () => answer);
      const outcome = await runReaderJob({ id: "products" }, h.env);
      expect(outcome.status).toBe("error");
      expect(h.sent).toHaveLength(1);
    }
  });
});

describe("item_traffic", () => {
  const job = { id: "item_traffic" as const, days: ["2026-11-02", "2026-11-01"], itemIds: ["11", "12"] };
  const ok = () => ({ body: trafficDetails });

  it("one paced GET per item per day: period=day, order_type=confirmed, item_id, end = next midnight", async () => {
    const h = harness({ traffic_details: { query: { period: "yesterday", extra: "x" }, headers: { "x-h": "1" } } }, ok);
    const outcome = await runReaderJob(job, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(4);
    const urls = h.sent.map((r) => new URL(r.url));
    expect(urls[0]!.pathname).toBe("/api/mydata/v1/product/traffic/details/");
    expect(Object.fromEntries(urls[0]!.searchParams)).toMatchObject({
      period: "day",
      order_type: "confirmed",
      item_id: "11",
      extra: "x",
      start_time: String(gmt7DateStart("2026-11-02")),
      end_time: String(gmt7DateStart("2026-11-02") + 86_400),
    });
    expect(urls.map((u) => u.searchParams.get("item_id"))).toEqual(["11", "12", "11", "12"]);
    expect(h.sent[0]!.headers).toEqual({ "x-h": "1" });
    expect(outcome.responses.map((r) => [r.day, r.itemId])).toEqual([
      ["2026-11-02", "11"],
      ["2026-11-02", "12"],
      ["2026-11-01", "11"],
      ["2026-11-01", "12"],
    ]);
    // only the four source blocks are kept, and every request after the first waited >= 2 s
    expect(Object.keys((outcome.responses[0]!.body as { result: object }).result)).toEqual(["product_card", "live", "video", "affiliate"]);
    expect(h.sleeps.filter((ms) => ms >= 2_000).length).toBeGreaterThanOrEqual(3);
  });

  it("falls back to the page's other mydata headers when it never called traffic/details", async () => {
    const h = harness({}, ok, {});
    h.env.mydataHeaders = () => ({ "x-mydata": "1" });
    await runReaderJob({ ...job, days: ["2026-11-02"], itemIds: ["11"] }, h.env);
    expect(h.sent[0]!.headers).toEqual({ "x-mydata": "1" });
  });

  it("the password re-confirmation modal stops with blocked_login before any request", async () => {
    const h = harness({}, ok, { session: false });
    h.env.passwordModalVisible = () => true;
    const outcome = await runReaderJob(job, h.env);
    expect(outcome).toMatchObject({ status: "blocked_login", detail: "password_modal" });
    expect(h.sent).toEqual([]);
  });

  it("a modal that appears mid-job stops it after the requests already made", async () => {
    const h = harness({}, ok);
    let n = 0;
    h.env.passwordModalVisible = () => h.sent.length >= 2 && ++n > 0;
    const outcome = await runReaderJob(job, h.env);
    expect(outcome.status).toBe("blocked_login");
    expect(h.sent).toHaveLength(2);
  });

  it("one failing item does not stop the job; five in a row do; a CAPTCHA/login answer stops at once", async () => {
    const some = harness({}, (_r, i) => (i === 1 ? { status: 500, body: {} } : ok()));
    const done = await runReaderJob(job, some.env);
    expect(done.status).toBe("done");
    expect(done.responses.filter((r) => r.status === 500)).toHaveLength(1);

    const all = harness({}, () => ({ status: 500, body: {} }));
    const many = await runReaderJob({ ...job, itemIds: ["1", "2", "3", "4", "5", "6"] }, all.env);
    expect(many.status).toBe("error");
    expect(all.sent).toHaveLength(5);

    const login = harness({}, () => ({ status: 401, body: {} }));
    expect((await runReaderJob(job, login.env)).status).toBe("blocked_login");
    const captcha = harness({}, () => ({ status: 403, body: { error: 90309999 } }));
    expect((await runReaderJob(job, captcha.env)).status).toBe("blocked_captcha");
  });

  it("is capped at TRAFFIC_MAX_REQUESTS_PER_JOB requests", async () => {
    const ids = Array.from({ length: 150 }, (_, i) => String(1000 + i));
    const h = harness({}, ok);
    const outcome = await runReaderJob({ id: "item_traffic", days: ["2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30", "2026-10-29"], itemIds: ids }, h.env);
    expect(outcome.status).toBe("done");
    expect(h.sent).toHaveLength(TRAFFIC_MAX_REQUESTS_PER_JOB);
  });

  it("isPasswordPrompt matches the modal text only", () => {
    expect(isPasswordPrompt("Vui lòng nhập mật khẩu Shopee của bạn để tiếp tục")).toBe(true);
    expect(isPasswordPrompt("Trang tổng quan")).toBe(false);
  });
});
