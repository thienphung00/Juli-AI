/**
 * `useRunStream` — the two-error-kinds property (#1315).
 *
 * The assertion this file exists for is the last one: a dropped connection and
 * a failed run must not produce the same value. Collapsing them tells a seller
 * their run died because their wifi blinked, and hides a real failure behind a
 * spinner.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import { useRunStream } from "../use-run-stream";

const RUN_ID = "6fed3803-a77e-4d55-9ea3-ac72d25e77e2";

function sse(events: AgentEvent[]): string {
  return events.map((e) => `id: ${e.sequence_number}\ndata: ${JSON.stringify(e)}\n\n`).join("");
}

function event(seq: number, type: string, payload: Record<string, unknown>): AgentEvent {
  return {
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    timestamp: "2026-09-05T00:00:00Z",
    v: 1,
    event_type: type,
    payload,
  } as unknown as AgentEvent;
}

function streamResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("useRunStream", () => {
  it("does not connect without a token", () => {
    const fetchImpl = vi.fn();
    const { result } = renderHook(() => useRunStream(RUN_ID, { fetchImpl: fetchImpl as never }));
    expect(result.current.streamStatus).toBe("idle");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("folds streamed events into the view through the pure reducer", async () => {
    const events = [
      event(1, "workflow.started", { workflow_key: "optimize_product_2" }),
      event(2, "tool.started", { tool_call_id: "c1", tool_name: "get_product_information" }),
    ];
    const fetchImpl = vi.fn(async () => streamResponse(sse(events)));

    const { result } = renderHook(() =>
      useRunStream(RUN_ID, { token: "t", fetchImpl: fetchImpl as never }),
    );

    await waitFor(() => expect(result.current.view.lastSequence).toBe(2));
    expect(result.current.view.liveEdge).toBe("thong-tin-san-pham");
    expect(result.current.view.terminal).toBeUndefined();
  });

  it("SEPARATES a dropped connection from a failed run", async () => {
    // 1. A run that genuinely failed.
    const failed = [
      event(1, "workflow.started", { workflow_key: "optimize_product_2" }),
      event(2, "workflow.failed", { status: "failed", stop_reason: "tool_error_unrecoverable" }),
    ];
    const okFetch = vi.fn(async () => streamResponse(sse(failed)));
    const { result: failedRun } = renderHook(() =>
      useRunStream(RUN_ID, { token: "t", fetchImpl: okFetch as never }),
    );
    await waitFor(() => expect(failedRun.current.view.terminal?.kind).toBe("failed"));

    // 2. A connection that dropped, on a run that never failed.
    const deadFetch = vi.fn(async () => {
      throw new TypeError("network down");
    });
    const { result: droppedStream } = renderHook(() =>
      useRunStream(RUN_ID, { token: "t", fetchImpl: deadFetch as never }),
    );
    await waitFor(() => expect(droppedStream.current.streamError).toBeDefined());

    // THE ASSERTION. The failed run has a terminal state and no stream error;
    // the dropped stream has a stream error and NO terminal state. If a future
    // refactor collapses them, these two expectations cannot both hold.
    expect(failedRun.current.view.terminal).toBeDefined();
    expect(failedRun.current.streamError).toBeUndefined();

    expect(droppedStream.current.view.terminal).toBeUndefined();
    expect(droppedStream.current.streamError).toBeDefined();

    expect(droppedStream.current.streamStatus).not.toBe(failedRun.current.view.terminal?.kind);
  });

  it("seeds from initialEvents without connecting, for a finished run", () => {
    const fetchImpl = vi.fn();
    const { result } = renderHook(() =>
      useRunStream(RUN_ID, {
        fetchImpl: fetchImpl as never,
        initialEvents: [event(1, "workflow.started", { workflow_key: "optimize_product_2" })],
      }),
    );
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(result.current.view.liveEdge).toBe("phan-tich");
  });
});
