/**
 * `useRunStream` teardown: after unmount the stream client may still deliver
 * onEvent / onError / onClose (a pending retry timer waking up, a late fetch
 * rejection). None of them may touch React state -- in CI the jsdom `window`
 * was already gone by then and vitest reported an unhandled rejection
 * ("window is not defined") from a later test file.
 */

import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import type { AgentEventStreamHandlers } from "../../agent-event-stream";

const captured: { handlers?: AgentEventStreamHandlers; abort: ReturnType<typeof vi.fn> } = {
  abort: vi.fn(),
};

vi.mock("../../agent-event-stream", async () => {
  const actual = await vi.importActual<typeof import("../../agent-event-stream")>(
    "../../agent-event-stream",
  );
  return {
    ...actual,
    openAgentEventStream: (_config: unknown, handlers: AgentEventStreamHandlers) => {
      captured.handlers = handlers;
      return { abort: captured.abort, done: Promise.resolve() };
    },
  };
});

import { useRunStream } from "../use-run-stream";

const RUN_ID = "6fed3803-a77e-4d55-9ea3-ac72d25e77e2";

const lateEvent = {
  workflow_run_id: RUN_ID,
  sequence_number: 1,
  timestamp: "2026-09-05T00:00:00Z",
  v: 1,
  event_type: "workflow.started",
  payload: { workflow_key: "optimize_product_2" },
} as unknown as AgentEvent;

describe("useRunStream teardown", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    captured.handlers = undefined;
    captured.abort.mockClear();
  });

  it("ignores onEvent / onError / onClose delivered after unmount", async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on("unhandledRejection", onUnhandled);

    const { unmount } = renderHook(() => useRunStream(RUN_ID, { token: "t" }));
    const handlers = captured.handlers;
    expect(handlers).toBeDefined();

    unmount();
    expect(captured.abort).toHaveBeenCalledTimes(1);

    // The environment is gone: any React scheduling from here would throw.
    const realWindow = globalThis.window;
    vi.stubGlobal("window", undefined);
    try {
      expect(() => handlers!.onEvent(lateEvent)).not.toThrow();
      expect(() =>
        handlers!.onError?.(new Error("late") as never, { attempt: 1, willRetry: true }),
      ).not.toThrow();
      expect(() => handlers!.onClose?.("aborted")).not.toThrow();
      await new Promise((resolve) => setTimeout(resolve, 0));
    } finally {
      vi.stubGlobal("window", realWindow);
      process.off("unhandledRejection", onUnhandled);
    }
    expect(unhandled).toEqual([]);
  });
});
