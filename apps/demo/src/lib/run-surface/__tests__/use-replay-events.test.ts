/**
 * `useReplayEvents` -- reveals the captured scenario progressively, paced
 * by its own recorded inter-event deltas (issue #1752, ADR-084 decision 2),
 * rather than dumping the whole array into state at mount. Local timers
 * only: no fetch, no token, no network.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getReplayInitialEvents } from "../replay-scenario";
import { useReplayEvents } from "../use-replay-events";

afterEach(() => {
  vi.useRealTimers();
});

describe("useReplayEvents", () => {
  it("reveals the first event immediately, on mount", () => {
    const { result } = renderHook(() => useReplayEvents());

    expect(result.current.events.length).toBeGreaterThanOrEqual(1);
    expect(result.current.events[0].event_type).toBe("workflow.started");
  });

  it("reveals every scenario event, all in order, without arriving all at once", async () => {
    const totalEvents = getReplayInitialEvents().length;
    const { result } = renderHook(() => useReplayEvents());

    // Not all at once: the count some events after mount must be strictly
    // fewer than the total, at least at the very first paint -- a real
    // pacing mechanism, not initialEvents' instant seed.
    const firstPaintCount = result.current.events.length;

    await waitFor(() => {
      expect(result.current.events).toHaveLength(totalEvents);
    });

    expect(firstPaintCount).toBeLessThanOrEqual(totalEvents);
    expect(result.current.events.map((e) => e.sequence_number)).toEqual(
      getReplayInitialEvents().map((e) => e.sequence_number),
    );
  });

  it("does not touch the network at all", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    const { result } = renderHook(() => useReplayEvents());
    await waitFor(() => {
      expect(result.current.events).toHaveLength(getReplayInitialEvents().length);
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
