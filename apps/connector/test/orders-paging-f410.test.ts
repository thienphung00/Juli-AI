// F4.10: the order list beyond page 1, through the list's own index call (page number changed),
// never the pager. Made-up ids.
import { describe, expect, it } from "vitest";
import {
  type FetchedReaderResponse,
  type OrderLink,
  pollingWaitFor,
  type ReaderEnv,
  type ReaderRequest,
  runReaderJob,
  type Template,
} from "../src/platforms/shopee/reader";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 19, 3, 0, 0);
const link = (id: number, day: string): OrderLink => ({ id: String(id), sn: `${day.slice(2, 4)}${day.slice(5, 7)}${day.slice(8, 10)}X${id}` });

/** Index answers per page; the shown (page 1) links come from the DOM. */
function env(shown: OrderLink[], more: boolean, indexPages: OrderLink[][], withTemplate = true, size = 2) {
  let clock = NOW;
  const sleep = async (ms: number) => void (clock += ms);
  const now = () => clock;
  const sent: ReaderRequest[] = [];
  const pauses: number[] = [];
  const search: Template = {
    query: {},
    body: { filter: { status: 1 }, pagination: { page_number: 1, page_size: size } },
    headers: { "x-test": "1" },
  };
  const e: ReaderEnv = {
    origin: SC,
    pacer: new Pacer({ sleep, now, random: () => 0 }),
    now,
    session: () => ({ SPC_CDS: "s", SPC_CDS_VER: "2" }),
    hasSession: () => true,
    template: (endpoint) => (endpoint === "order_search" && withTemplate ? search : undefined),
    waitFor: pollingWaitFor(sleep, now),
    fetch: async (request): Promise<FetchedReaderResponse> => {
      sent.push(request);
      if (request.endpoint === "order_search") {
        const page = JSON.parse(request.body!).pagination.page_number as number;
        const list = (indexPages[page - 2] ?? []).map((l) => ({ order_id: Number(l.id), order_sn: l.sn, buyer: "x" }));
        return { status: 200, text: async () => JSON.stringify({ code: 0, data: { list } }) };
      }
      const id = new URL(request.url).searchParams.get("order_id")!;
      return { status: 200, text: async () => JSON.stringify({ code: 0, data: { order_id: Number(id), order_sn: `S${id}` } }) };
    },
    pathname: () => "/portal/sale/order",
    pause: async (ms) => void pauses.push(ms),
    random: () => 0,
    orderLinks: () => shown,
    orderListEmpty: () => false,
    moreOrderPages: () => more,
  };
  return { e, sent, pauses };
}

const detailIds = (sent: ReaderRequest[]) =>
  sent.filter((r) => r.endpoint === "order_detail").map((r) => new URL(r.url).searchParams.get("order_id"));

describe("F4.10 order list beyond page 1 (no click)", () => {
  it("3-page fake: replays the index with only the page number changed, paced, then reads every order since the day", async () => {
    const h = env(
      [link(101, "2026-11-14"), link(102, "2026-11-14")],
      true,
      [
        [link(201, "2026-11-13"), link(202, "2026-11-12")],
        [link(301, "2026-11-11")], // short page: the last one
      ],
    );
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.e);
    expect(outcome.status).toBe("done");
    expect(outcome.detail).toBeUndefined(); // no partial:first_page: every page was read
    const indexCalls = h.sent.filter((r) => r.endpoint === "order_search");
    expect(indexCalls.map((r) => JSON.parse(r.body!).pagination.page_number)).toEqual([2, 3]);
    expect(JSON.parse(indexCalls[0]!.body!)).toEqual({ filter: { status: 1 }, pagination: { page_number: 2, page_size: 2 } });
    expect(indexCalls[0]!.headers["x-test"]).toBe("1");
    expect(h.pauses).toHaveLength(2); // a pause before each page
    expect(detailIds(h.sent)).toEqual(["101", "102", "201", "202", "301"]);
    expect(JSON.stringify(outcome.responses)).not.toContain("buyer");
  });

  it("stops at a page whose orders are all older than sinceDay (complete)", async () => {
    const h = env([link(101, "2026-11-14"), link(102, "2026-11-14")], true, [
      [link(201, "2026-11-03"), link(202, "2026-11-02")],
      [link(301, "2026-11-01"), link(302, "2026-10-31")],
    ]);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.e);
    expect(outcome.detail).toBeUndefined();
    expect(h.sent.filter((r) => r.endpoint === "order_search")).toHaveLength(1);
    expect(detailIds(h.sent)).toEqual(["101", "102"]); // older orders are not read
  });

  it("reads no further page when the list shows no next page", async () => {
    const h = env([link(101, "2026-11-14")], false, [[link(201, "2026-11-13")]]);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.e);
    expect(outcome.detail).toBeUndefined();
    expect(h.sent.filter((r) => r.endpoint === "order_search")).toHaveLength(0);
  });

  it("without a replayable index call it stays partial:first_page (as before)", async () => {
    const h = env([link(101, "2026-11-14"), link(102, "2026-11-14")], true, [], false);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.e);
    expect(outcome.detail).toBe("partial:first_page");
    expect(h.sent.filter((r) => r.endpoint === "order_search")).toHaveLength(0);
  });

  it("an error on a later page keeps what was read and says partial", async () => {
    const h = env([link(101, "2026-11-14"), link(102, "2026-11-14")], true, []);
    const original = h.e.fetch;
    h.e.fetch = async (request) =>
      request.endpoint === "order_search" ? { status: 500, text: async () => "{}" } : original(request);
    const outcome = await runReaderJob({ id: "orders", sinceDay: "2026-11-05" }, h.e);
    expect(outcome.detail).toMatch(/^partial:/);
    expect(detailIds(h.sent)).toEqual(["101", "102"]);
  });
});
