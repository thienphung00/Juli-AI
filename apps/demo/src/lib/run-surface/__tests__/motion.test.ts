import { describe, expect, it } from "vitest";

import {
  RUN_SURFACE_MOTION_PRIMITIVE_IDS,
  RUN_SURFACE_MOTION_TABLE,
  resolveRunSurfaceMotion,
  type MotionTiming,
  type RunSurfaceMotionPrimitiveId,
  type RunSurfaceMotionTrigger,
} from "../motion";

/**
 * Issue #1314 / AGT-W6A. Independently transcribed from PUI-DESIGN.md §5
 * -- deliberately a *second* copy of the table, not a re-export of
 * `RUN_SURFACE_MOTION_TABLE`, so a change to the module that silently
 * drifts from the design doc actually fails a test instead of comparing
 * the table to itself.
 */
const EXPECTED_MOTION_TABLE: Record<
  RunSurfaceMotionPrimitiveId,
  { full: MotionTiming; reducedMotion: MotionTiming }
> = {
  "stage-advance": {
    full: { durationMs: 320, easing: "ease-out", description: "Canvas slides left, stepper node fills" },
    reducedMotion: { durationMs: 150, easing: "linear", description: "Crossfade" },
  },
  "assistant-text-reveal": {
    full: {
      durationMs: 30,
      easing: "linear",
      description: "Typewriter reveal, block-paced, ~30ms/char cap",
    },
    reducedMotion: { durationMs: 150, easing: "ease-out", description: "Full text fade-in" },
  },
  "thinking-state": {
    full: {
      durationMs: 1600,
      easing: "ease-in-out",
      description: "Soft breathing indicator on the active stepper node (loop)",
    },
    reducedMotion: { durationMs: 0, easing: "linear", description: "Static pulse dot" },
  },
  "option-cards-arrive": {
    full: {
      durationMs: 240,
      easing: "ease-out",
      description: "Stagger-in, 150ms offsets (agent \"presenting\")",
    },
    reducedMotion: { durationMs: 150, easing: "linear", description: "Simultaneous fade" },
  },
  "select-option": {
    full: { durationMs: 180, easing: "ease-out", description: "Card elevates, siblings dim to 60%" },
    reducedMotion: { durationMs: 0, easing: "linear", description: "Border emphasis only" },
  },
  "confirm-to-update": {
    full: {
      durationMs: 400,
      easing: "ease-in-out",
      description: "Selected card animates forward into the next stage's header",
    },
    reducedMotion: { durationMs: 0, easing: "linear", description: "Cut with header carry" },
  },
  "tool-chip-complete": {
    full: { durationMs: 200, easing: "ease-out", description: "Check-in with subtle scale settle" },
    reducedMotion: { durationMs: 0, easing: "linear", description: "Instant check" },
  },
  "terminal-complete": {
    full: {
      durationMs: 600,
      easing: "ease-in-out",
      description: "Stepper completes in sequence, then summary rises",
    },
    reducedMotion: { durationMs: 150, easing: "linear", description: "Fade" },
  },
};

describe("all eight PUI-DESIGN.md §5 motion-table entries exist (AC 3)", () => {
  it("all eight motion primitives exist with stated durations, easings, and prefers-reduced-motion paths", () => {
    expect(RUN_SURFACE_MOTION_PRIMITIVE_IDS).toHaveLength(8);
    expect([...RUN_SURFACE_MOTION_PRIMITIVE_IDS].sort()).toEqual(
      Object.keys(EXPECTED_MOTION_TABLE).sort(),
    );

    for (const id of RUN_SURFACE_MOTION_PRIMITIVE_IDS) {
      const entry = RUN_SURFACE_MOTION_TABLE[id];
      const expected = EXPECTED_MOTION_TABLE[id];
      expect(entry.full.durationMs).toBe(expected.full.durationMs);
      expect(entry.full.easing).toBe(expected.full.easing);
      expect(entry.reducedMotion.durationMs).toBe(expected.reducedMotion.durationMs);
      expect(entry.reducedMotion.easing).toBe(expected.reducedMotion.easing);
      expect(entry.reducedMotion.description).toBe(expected.reducedMotion.description);
    }
  });

  it("exposes exactly the 8 primitive ids the design table names", () => {
    expect(RUN_SURFACE_MOTION_PRIMITIVE_IDS).toHaveLength(8);
    expect([...RUN_SURFACE_MOTION_PRIMITIVE_IDS].sort()).toEqual(
      Object.keys(EXPECTED_MOTION_TABLE).sort(),
    );
  });

  it.each(RUN_SURFACE_MOTION_PRIMITIVE_IDS)(
    "%s: full-motion duration and easing match the design table",
    (id) => {
      const entry = RUN_SURFACE_MOTION_TABLE[id];
      const expected = EXPECTED_MOTION_TABLE[id].full;
      expect(entry.full.durationMs).toBe(expected.durationMs);
      expect(entry.full.easing).toBe(expected.easing);
    },
  );

  it.each(RUN_SURFACE_MOTION_PRIMITIVE_IDS)(
    "%s: has a prefers-reduced-motion path matching the table's stated alternative",
    (id) => {
      const entry = RUN_SURFACE_MOTION_TABLE[id];
      const expected = EXPECTED_MOTION_TABLE[id].reducedMotion;
      expect(entry.reducedMotion.durationMs).toBe(expected.durationMs);
      expect(entry.reducedMotion.easing).toBe(expected.easing);
      expect(entry.reducedMotion.description).toBe(expected.description);
    },
  );
});

describe("resolveRunSurfaceMotion requires a real trigger (AC 6)", () => {
  const agentEventTrigger: RunSurfaceMotionTrigger = {
    kind: "agent-event",
    eventType: "workflow.approval_required",
  };
  const stateTransitionTrigger: RunSurfaceMotionTrigger = {
    kind: "state-transition",
    from: "presenting",
    to: "selected",
  };

  it("resolves the full-motion timing when reduced motion is off", () => {
    const resolved = resolveRunSurfaceMotion("option-cards-arrive", agentEventTrigger, false);
    expect(resolved.durationMs).toBe(240);
    expect(resolved.easing).toBe("ease-out");
    expect(resolved.reduced).toBe(false);
    expect(resolved.trigger).toEqual(agentEventTrigger);
  });

  it("resolves the reduced-motion timing when reduced motion is on", () => {
    const resolved = resolveRunSurfaceMotion("option-cards-arrive", agentEventTrigger, true);
    expect(resolved.durationMs).toBe(150);
    expect(resolved.description).toBe("Simultaneous fade");
    expect(resolved.reduced).toBe(true);
  });

  it("accepts a state-transition trigger", () => {
    const resolved = resolveRunSurfaceMotion("select-option", stateTransitionTrigger, false);
    expect(resolved.durationMs).toBe(180);
  });

  it("throws when called with no trigger at runtime (untyped caller)", () => {
    // Simulates a caller that bypassed the type system (plain JS, `any`).
    const untypedCall = resolveRunSurfaceMotion as unknown as (
      id: RunSurfaceMotionPrimitiveId,
      trigger: unknown,
      reduced: boolean,
    ) => unknown;
    expect(() => untypedCall("stage-advance", undefined, false)).toThrow(/trigger/i);
  });

  it("throws for an agent-event trigger naming an unknown event type", () => {
    const badTrigger = { kind: "agent-event", eventType: "assistant.text.delta" } as unknown as RunSurfaceMotionTrigger;
    expect(() => resolveRunSurfaceMotion("thinking-state", badTrigger, false)).toThrow(
      /not one of the 8 known agent event types/,
    );
  });

  it("throws for a state-transition trigger missing from/to", () => {
    const badTrigger = { kind: "state-transition", from: "", to: "" } as RunSurfaceMotionTrigger;
    expect(() => resolveRunSurfaceMotion("confirm-to-update", badTrigger, false)).toThrow(
      /non-empty/,
    );
  });

  it("no timer-only overload -- motion primitives require a real trigger argument", () => {
    const callWithMissingTrigger = () => {
      // @ts-expect-error -- resolveRunSurfaceMotion has no 2-argument
      // overload; omitting `trigger` is a type error, checked by
      // `tsc --noEmit` (`pnpm --filter @juli/demo exec tsc --noEmit`), and
      // the runtime guard below still refuses the call defensively too.
      resolveRunSurfaceMotion("stage-advance", false);
    };
    expect(callWithMissingTrigger).toThrow();
  });
});
