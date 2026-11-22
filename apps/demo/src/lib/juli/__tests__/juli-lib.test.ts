import { describe, expect, it, vi } from "vitest";
import { parseJuliEvent, type JuliAgentEvent } from "@juli/contracts";

import { adaptConversation, createJuliClient, JuliApiError } from "../client";
import { EXPLANATION_CARD, EXPLANATION_REPLACED, MULTI_INTENT, RUNNING } from "../fixtures";
import { formatDong, formatPercent, formatSignedDong, dirOfChange } from "../format";
import { juliHref } from "../links";
import { normalizeDataAnswer, reduceAnswer, stripMarkdown } from "../reduce";

describe("format (U10a)", () => {
  it("formats đồng, signs and percents the Vietnamese way", () => {
    expect(formatDong(8728160)).toBe("8.728.160đ");
    expect(formatSignedDong(15833)).toBe("+15.833đ");
    expect(formatSignedDong(-665)).toBe("−665đ");
    expect(formatPercent(16.14)).toBe("16,1%");
    expect(dirOfChange(16.1, 15.5)).toBe("down");
  });
});

describe("parseJuliEvent", () => {
  it("accepts {type,data}, flat and event-line frames and rejects unknown types", () => {
    expect(parseJuliEvent({ type: "restated", data: { text_vi: "a" } })?.data).toEqual({ text_vi: "a" });
    expect(parseJuliEvent({ type: "text_delta", text: "x" })?.data).toEqual({ text: "x" });
    expect(parseJuliEvent({ text: "x" }, "text_delta")?.type).toBe("text_delta");
    expect(parseJuliEvent({ type: "debug", data: {} })).toBeNull();
  });
});

describe("reduceAnswer", () => {
  it("shows the restated line first and keeps one status line while running", () => {
    const v = reduceAnswer(RUNNING);
    expect(v.restated?.startsWith("Đang tìm hiểu: ")).toBe(true);
    expect(v.status?.key).toBe("finding_cause");
    expect(v.doneSteps.map((s) => s.key)).toEqual(["checking_data", "comparing"]);
    expect(v.blocks[0]!.text).toContain("Thẻ sản phẩm");
    expect(v.finished).toBe(false);
  });
  it("text_replace replaces the streamed text", () => {
    const v = reduceAnswer(EXPLANATION_REPLACED);
    expect(v.blocks[0]!.text).toBe("CTOR giảm từ 7,94% xuống 4,78%, chủ yếu ở Thẻ sản phẩm.");
  });
  it("card answer has path + card and finishes", () => {
    const v = reduceAnswer(EXPLANATION_CARD);
    expect(v.blocks[0]!.path).toHaveLength(3);
    expect(v.blocks[0]!.card?.versions).toHaveLength(4);
    expect(v.finished).toBe(true);
    expect(v.status).toBeNull();
  });
  it("multi-intent makes one block per intent and keeps Xem tiếp", () => {
    const v = reduceAnswer(MULTI_INTENT);
    expect(v.blocks.map((b) => b.title)).toEqual(["GMV", "Đơn hàng", "CTR"]);
    expect(v.more).toHaveLength(1);
  });
  it("is idempotent for a replayed prefix of the same events", () => {
    expect(reduceAnswer([...EXPLANATION_CARD])).toEqual(reduceAnswer([...EXPLANATION_CARD]));
  });
});

describe("juliHref (U7)", () => {
  it("routes metric / channel / product / ads / card links", () => {
    expect(juliHref({ kind: "metric", metric: "ctor", from: "2026-11-12", to: "2026-11-18" })).toContain("/phan-tich");
    expect(juliHref({ kind: "channel", metric: "ctor", channel: "product_card" })).toContain("channel=product_card");
    expect(juliHref({ kind: "product", item_id: "1001" })).toBe("/san-pham/1001");
    expect(juliHref({ kind: "ads" })).toBe("/quang-cao");
    expect(juliHref({ kind: "card", card_code: "JC-1" })).toContain("the=JC-1");
  });
});

function sseResponse(frames: string[], keepOpen = false): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      if (!keepOpen) controller.close();
    },
  });
  return new Response(body, { status: 200 });
}
/** The server's wire format: `id`, `event` and the payload as data. */
const frame = (id: number, ev: JuliAgentEvent) => `id: ${id}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`;

describe("createJuliClient", () => {
  it("sends bearer + shop headers, resumes with Last-Event-ID and dedupes the replay", async () => {
    const restated: JuliAgentEvent = { type: "restated", data: { text_vi: "Đang tìm hiểu: x" } };
    const text: JuliAgentEvent = { type: "text_delta", data: { text: "a" } };
    const done: JuliAgentEvent = { type: "done", data: { stop_reasons: [] } };
    const calls: Headers[] = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(new Headers(init?.headers));
      return calls.length === 1
        ? sseResponse([frame(1, restated), frame(2, text)]) // drops without a terminal event
        : sseResponse([frame(2, text), frame(3, done)]); // replays 2
    }) as unknown as typeof fetch;
    const client = createJuliClient({ token: "tok", shopId: "shop-1", fetchImpl, reconnectDelayMs: () => 0 });
    const seen: JuliAgentEvent[] = [];
    const reconnecting: boolean[] = [];
    await new Promise<void>((resolve) => {
      client.stream("m1", { onEvent: (e) => seen.push(e), onReconnecting: (r) => reconnecting.push(r), onClose: () => resolve() });
    });
    expect(seen.map((e) => e.type)).toEqual(["restated", "text_delta", "done"]);
    expect(calls[0]!.get("Authorization")).toBe("Bearer tok");
    expect(calls[0]!.get("X-Shop-Id")).toBe("shop-1");
    expect(calls[0]!.get("Last-Event-ID")).toBeNull();
    expect(calls[1]!.get("Last-Event-ID")).toBe("2");
    expect(reconnecting).toContain(true);
  });

  it("surfaces the 429 retry_at and does not retry a 404 stream", async () => {
    const limited = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: { code: "juli_limited", message: "m", retry_at: "2026-11-20T08:40:00Z", retry_after_seconds: 60 } }), {
          status: 429,
          headers: { "Retry-After": "60" },
        }),
    ) as unknown as typeof fetch;
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl: limited });
    await expect(client.ask({ text: "x" })).rejects.toMatchObject({ status: 429, retryAt: "2026-11-20T08:40:00Z", code: "juli_limited" });
    expect(new JuliApiError(403).status).toBe(403);

    const missing = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const c2 = createJuliClient({ token: "t", shopId: "s", fetchImpl: missing, reconnectDelayMs: () => 0 });
    const reason = await new Promise((resolve) => c2.stream("m", { onEvent: () => undefined, onClose: resolve }));
    expect(reason).toBe("failed");
    expect(missing).toHaveBeenCalledTimes(1);
  });
});

describe("T3 shapes", () => {
  it("parses event: + payload frames, comments, and keeps the flat fallbacks", () => {
    expect(parseJuliEvent({ code: "failed" }, "error")).toEqual({ type: "error", data: { code: "failed" } });
    expect(parseJuliEvent({ type: "error", payload: { code: "busy" } })?.data).toEqual({ code: "busy" });
  });

  it("GET /templates and /conversations are unwrapped", async () => {
    const fetchImpl = vi.fn(async (url: RequestInfo | URL) =>
      String(url).endsWith("/templates")
        ? new Response(JSON.stringify({ templates: [{ key: "improve_gmv", label_vi: "Cải thiện GMV" }], shop_state: { read_only: true } }))
        : new Response(JSON.stringify({ conversations: [{ id: "c1", platform: "shopee", title: "t", created_at: "x", updated_at: "y" }] })),
    ) as unknown as typeof fetch;
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl });
    expect((await client.templates()).shop_state.read_only).toBe(true);
    expect((await client.conversations())[0]!.id).toBe("c1");
  });

  it("pairs user + assistant rows and turns {seq,type,payload} into events", () => {
    const conv = adaptConversation({
      id: "c1",
      title: "t",
      messages: [
        { id: "u1", role: "user", status: "done", created_at: "2026-11-16T03:00:00Z", text: null, template: "improve_gmv" },
        {
          id: "a1",
          role: "assistant",
          status: "done",
          created_at: "2026-11-16T03:00:05Z",
          events: [
            { seq: 1, type: "restated", payload: { text_vi: "Đang tìm hiểu: x" } },
            { seq: 2, type: "mystery", payload: {} },
            { seq: 3, type: "done", payload: { stop_reasons: [] } },
          ],
          data_until_vi: "15/11",
          cards: [{ draft_ref: "d1", status: "sent", sent_card_code: "JC-1", version_label: "v" }],
        },
      ],
    });
    expect(conv.messages).toHaveLength(1);
    expect(conv.messages[0]!.template).toBe("improve_gmv");
    expect(conv.messages[0]!.events.map((e) => e.type)).toEqual(["restated", "done"]);
    expect(conv.messages[0]!.cards![0]!.sent_card_code).toBe("JC-1");
  });
});

describe("429 handling", () => {
  const limited = (headers: Record<string, string>) =>
    vi.fn(async () => new Response(JSON.stringify({ detail: "Too many concurrent event streams" }), { status: 429, headers })) as unknown as typeof fetch;

  it("a stream 429 is a limit: one request, closes 'limited' with Retry-After as the time", async () => {
    const fetchImpl = limited({ "Retry-After": "120" });
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl, reconnectDelayMs: () => 0 });
    const closed = await new Promise<[string, { retryAt?: string } | undefined]>((resolve) =>
      client.stream("m", { onEvent: () => undefined, onClose: (r, i) => resolve([r, i]) }),
    );
    expect(closed[0]).toBe("limited");
    expect(Date.parse(closed[1]!.retryAt!)).toBeGreaterThan(Date.now());
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("a stream 429 with neither time nor header still closes 'limited' without a time", async () => {
    const fetchImpl = limited({});
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl, reconnectDelayMs: () => 0 });
    const closed = await new Promise<[string, { retryAt?: string } | undefined]>((resolve) =>
      client.stream("m", { onEvent: () => undefined, onClose: (r, i) => resolve([r, i]) }),
    );
    expect(closed).toEqual(["limited", { retryAt: undefined }]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("ask 429 uses Retry-After when the body has no retry_at", async () => {
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl: limited({ "Retry-After": "60" }) });
    await expect(client.ask({ text: "x" })).rejects.toMatchObject({ status: 429, retryAt: expect.any(String) });
  });
});

describe("history query", () => {
  it("GET /conversations carries ?platform=", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ conversations: [] }))) as unknown as typeof fetch;
    await createJuliClient({ token: "t", shopId: "s", fetchImpl }).conversations("tiktok");
    expect((fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]![0]).toBe("/v1/demo/juli/conversations?platform=tiktok");
  });
});

describe("data answers saved with the engine's older shapes (22/11 crash)", () => {
  it("a metric_total value object becomes its text, so it can render", () => {
    const d = normalizeDataAnswer({
      kind: "metric_total",
      title_vi: "Đơn hàng",
      value: { now: 12, before: 27, value_vi: "12", before_vi: "27" } as unknown as string,
      window_vi: "14/11–20/11",
      fresh_vi: "Số liệu đến hết 20/11",
    });
    expect(d.value).toBe("12");
  });

  it("top product rows and series get the UI's keys", () => {
    const d = normalizeDataAnswer({
      kind: "top_products",
      title_vi: "Top sản phẩm theo GMV",
      rows: [{ name: "Sản phẩm A", gmv_vi: "7.000đ", orders_vi: "3", item_id: "p1" }] as never,
      series: [{ day: "20/11", value: 1, value_vi: "1" }] as never,
      window_vi: "",
      fresh_vi: "",
    });
    expect(d.rows?.[0]).toMatchObject({ label_vi: "Sản phẩm A", value_vi: "7.000đ", detail_vi: "3 đơn" });
    expect(d.rows?.[0]?.link).toEqual({ kind: "product", item_id: "p1" });
    expect(d.series?.[0]?.label_vi).toBe("20/11");
  });

  it("markdown emphasis never reaches the screen", () => {
    expect(stripMarkdown("Nguyên nhân: **Thẻ sản phẩm** giảm")).toBe("Nguyên nhân: Thẻ sản phẩm giảm");
  });
});
