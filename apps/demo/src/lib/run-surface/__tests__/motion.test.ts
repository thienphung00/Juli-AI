import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

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

/**
 * Issue #1915 AC 1 -- every one of the eight PUI-DESIGN.md §5 primitives
 * is passed to `resolveRunSurfaceMotion` by at least one module under
 * `apps/demo/src/components/`. This is the guard that makes a future
 * orphaned primitive impossible.
 *
 * "A guard must be seen failing" (code-quality.mdc): this is exactly the
 * shape that goes vacuous -- a scan that silently collects nothing still
 * compares an empty set against itself. Three defences:
 *  1. the collector is fed known-good and known-bad fixture source and
 *     must extract the call from one and nothing from the other;
 *  2. the resolved list and its count are printed, so a silently-short
 *     list is visible in the runner output, never inferred from a green;
 *  3. the assertion is an exact set equality against
 *     `RUN_SURFACE_MOTION_PRIMITIVE_IDS`, plus one named test per
 *     primitive so a RED names the orphan.
 */

/** Every primitive id passed as the first argument of a
 *  `resolveRunSurfaceMotion(...)` call in `source`, in order. */
export function extractResolvedPrimitiveIds(source: string): string[] {
  const ids: string[] = [];
  const call = /resolveRunSurfaceMotion\(\s*["']([a-z-]+)["']/g;
  let match: RegExpExecArray | null;
  while ((match = call.exec(source)) !== null) {
    ids.push(match[1]!);
  }
  return ids;
}

describe("every §5 primitive has a component consumer (issue #1915 AC 1)", () => {
  const componentsDir = path.resolve(__dirname, "../../../components");
  const componentFiles = readdirSync(componentsDir).filter(
    (name) =>
      (name.endsWith(".tsx") || name.endsWith(".ts")) &&
      statSync(path.join(componentsDir, name)).isFile(),
  );

  const resolvedByFile = new Map<string, string[]>();
  for (const file of componentFiles) {
    const ids = extractResolvedPrimitiveIds(
      readFileSync(path.join(componentsDir, file), "utf8"),
    );
    if (ids.length > 0) resolvedByFile.set(file, ids);
  }
  const resolvedIds = new Set([...resolvedByFile.values()].flat());

  it("the collector itself is not vacuous -- it sees a multi-line call and flags callless source", () => {
    const fixtureWithCall = [
      "const motion = resolveRunSurfaceMotion(",
      '  "tool-chip-complete",',
      '  { kind: "agent-event", eventType: "tool.completed" },',
      "  false,",
      ");",
    ].join("\n");
    expect(extractResolvedPrimitiveIds(fixtureWithCall)).toEqual(["tool-chip-complete"]);
    expect(extractResolvedPrimitiveIds("const nothing = 1;")).toEqual([]);
  });

  it("the scan saw a real component corpus, not an empty directory", () => {
    expect(componentFiles.length).toBeGreaterThan(10);
    expect(componentFiles).toContain("option-picker.tsx");
  });

  it("resolves exactly the eight primitive ids -- the list and count are printed, never inferred", () => {
    const sorted = [...resolvedIds].sort();
    // Printed by design (issue #1915): a silently-short list must be
    // visible in the runner output beside the green, not deduced from it.
    console.info(
      `[motion-coverage] resolved ${sorted.length}/8 primitives: ${sorted.join(", ")}`,
    );
    for (const [file, ids] of resolvedByFile) {
      console.info(`[motion-coverage]   ${file}: ${[...new Set(ids)].sort().join(", ")}`);
    }
    expect(sorted).toEqual([...RUN_SURFACE_MOTION_PRIMITIVE_IDS].sort());
  });

  it.each([...RUN_SURFACE_MOTION_PRIMITIVE_IDS])(
    "%s is passed to resolveRunSurfaceMotion by at least one component module",
    (id) => {
      const consumers = [...resolvedByFile.entries()]
        .filter(([, ids]) => ids.includes(id))
        .map(([file]) => file);
      expect(
        consumers.length,
        `orphaned primitive: "${id}" is resolved by no module under apps/demo/src/components/`,
      ).toBeGreaterThan(0);
    },
  );
});
