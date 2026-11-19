import { describe, expect, it, vi } from "vitest";
import { parseJuliEvent, type JuliAgentEvent } from "@juli/contracts";

import { createJuliClient, JuliApiError } from "../client";
import { EXPLANATION_CARD, EXPLANATION_REPLACED, MULTI_INTENT, RUNNING } from "../fixtures";
import { formatDong, formatPercent, formatSignedDong, dirOfChange } from "../format";
import { juliHref } from "../links";
import { reduceAnswer } from "../reduce";

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
const frame = (id: number, ev: JuliAgentEvent) => `id: ${id}\ndata: ${JSON.stringify(ev)}\n\n`;

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
    const limited = vi.fn(async () => new Response(JSON.stringify({ retry_at: "2026-11-20T08:40:00Z" }), { status: 429 })) as unknown as typeof fetch;
    const client = createJuliClient({ token: "t", shopId: "s", fetchImpl: limited });
    await expect(client.ask({ text: "x" })).rejects.toMatchObject({ status: 429, retryAt: "2026-11-20T08:40:00Z" });
    expect(new JuliApiError(403).status).toBe(403);

    const missing = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const c2 = createJuliClient({ token: "t", shopId: "s", fetchImpl: missing, reconnectDelayMs: () => 0 });
    const reason = await new Promise((resolve) => c2.stream("m", { onEvent: () => undefined, onClose: resolve }));
    expect(reason).toBe("failed");
    expect(missing).toHaveBeenCalledTimes(1);
  });
});
