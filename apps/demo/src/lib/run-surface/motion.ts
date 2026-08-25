import { AGENT_EVENT_TYPES, type AgentEventType } from "@juli/contracts";

/**
 * The eight motion primitives from PUI-DESIGN.md §5 (issue #1314 /
 * AGT-W6A), one per row of that table, each with its stated full-motion
 * duration/easing and its stated `prefers-reduced-motion` alternative.
 *
 * "Motion is choreography for the stream -- every animated moment
 * corresponds to a real event; nothing animates to fake progress"
 * (PUI-DESIGN.md §5). `resolveRunSurfaceMotion` below is the enforcement:
 * its `trigger` parameter is required, typed against the real eight-event
 * union in `@juli/contracts` (or a named state transition), and validated
 * at runtime. There is no timer-only overload -- a caller cannot express
 * "animate to look busy" through this module.
 */

export const RUN_SURFACE_MOTION_PRIMITIVE_IDS = [
  "stage-advance",
  "assistant-text-reveal",
  "thinking-state",
  "option-cards-arrive",
  "select-option",
  "confirm-to-update",
  "tool-chip-complete",
  "terminal-complete",
] as const;

export type RunSurfaceMotionPrimitiveId = (typeof RUN_SURFACE_MOTION_PRIMITIVE_IDS)[number];

export interface MotionTiming {
  durationMs: number;
  easing: string;
  description: string;
}

export interface RunSurfaceMotionSpecEntry {
  id: RunSurfaceMotionPrimitiveId;
  /** The PUI-DESIGN.md §5 "Moment" column, verbatim. */
  moment: string;
  full: MotionTiming;
  reducedMotion: MotionTiming;
}

/**
 * PUI-DESIGN.md §5, transcribed field-for-field. Do not derive this table
 * from anything else -- `__tests__/motion.test.ts` diffs each entry
 * against its own independently-transcribed copy of the same spec table,
 * so a change here that silently drifts from the design doc fails that
 * test, not just a tautological self-comparison.
 */
export const RUN_SURFACE_MOTION_TABLE: Readonly<
  Record<RunSurfaceMotionPrimitiveId, RunSurfaceMotionSpecEntry>
> = Object.freeze({
  "stage-advance": {
    id: "stage-advance",
    moment: "Stage advance",
    full: {
      durationMs: 320,
      easing: "ease-out",
      description: "Canvas slides left, stepper node fills",
    },
    reducedMotion: {
      durationMs: 150,
      easing: "linear",
      description: "Crossfade",
    },
  },
  "assistant-text-reveal": {
    id: "assistant-text-reveal",
    moment: "assistant.text",
    full: {
      // PUI-DESIGN.md §5 gives no fixed duration, only a per-character
      // cap ("~30ms/char cap") for the block-paced typewriter reveal.
      durationMs: 30,
      easing: "linear",
      description: "Typewriter reveal, block-paced, ~30ms/char cap",
    },
    reducedMotion: {
      durationMs: 150,
      easing: "ease-out",
      description: "Full text fade-in",
    },
  },
  "thinking-state": {
    id: "thinking-state",
    moment: "Thinking state",
    full: {
      durationMs: 1600,
      easing: "ease-in-out",
      description: "Soft breathing indicator on the active stepper node (loop)",
    },
    reducedMotion: {
      durationMs: 0,
      easing: "linear",
      description: "Static pulse dot",
    },
  },
  "option-cards-arrive": {
    id: "option-cards-arrive",
    moment: "Option cards arrive",
    full: {
      durationMs: 240,
      easing: "ease-out",
      description: "Stagger-in, 150ms offsets (agent \"presenting\")",
    },
    reducedMotion: {
      durationMs: 150,
      easing: "linear",
      description: "Simultaneous fade",
    },
  },
  "select-option": {
    id: "select-option",
    moment: "Select option",
    full: {
      durationMs: 180,
      easing: "ease-out",
      description: "Card elevates, siblings dim to 60%",
    },
    reducedMotion: {
      durationMs: 0,
      easing: "linear",
      description: "Border emphasis only",
    },
  },
  "confirm-to-update": {
    id: "confirm-to-update",
    moment: "Confirm → Cập nhật",
    full: {
      durationMs: 400,
      easing: "ease-in-out",
      description: "Selected card animates forward into the next stage's header",
    },
    reducedMotion: {
      durationMs: 0,
      easing: "linear",
      description: "Cut with header carry",
    },
  },
  "tool-chip-complete": {
    id: "tool-chip-complete",
    moment: "Tool chip complete",
    full: {
      durationMs: 200,
      easing: "ease-out",
      description: "Check-in with subtle scale settle",
    },
    reducedMotion: {
      durationMs: 0,
      easing: "linear",
      description: "Instant check",
    },
  },
  "terminal-complete": {
    id: "terminal-complete",
    moment: "Terminal (Hoàn tất)",
    full: {
      durationMs: 600,
      easing: "ease-in-out",
      description: "Stepper completes in sequence, then summary rises",
    },
    reducedMotion: {
      durationMs: 150,
      easing: "linear",
      description: "Fade",
    },
  },
});

/**
 * A motion primitive's trigger: either a real agent event from the shared
 * eight-event union (`@juli/contracts`), or a named UI state transition
 * (e.g. selecting an option card). Either way it names something that
 * actually happened -- never a bare tick.
 */
export type RunSurfaceMotionTrigger =
  | { readonly kind: "agent-event"; readonly eventType: AgentEventType }
  | { readonly kind: "state-transition"; readonly from: string; readonly to: string };

export interface ResolvedRunSurfaceMotion extends MotionTiming {
  id: RunSurfaceMotionPrimitiveId;
  trigger: RunSurfaceMotionTrigger;
  reduced: boolean;
}

const AGENT_EVENT_TYPE_SET = new Set<string>(AGENT_EVENT_TYPES);

/**
 * Resolves the CSS timing for one PUI-DESIGN.md §5 motion primitive.
 *
 * `trigger` is a required, typed parameter -- there is no overload that
 * omits it, so `resolveRunSurfaceMotion(id, reduced)` is a compile error
 * (see `__tests__/motion.test.ts`'s `@ts-expect-error` case, checked by
 * `tsc --noEmit`). The runtime guards below defend the same invariant for
 * a caller that reaches this function through untyped JS or an `any`
 * cast: a missing, empty, or unrecognized trigger throws rather than
 * silently animating. This is the concrete answer to AC 6 ("No motion
 * primitive can be driven by a timer alone") -- nothing in this module
 * exposes a duration/easing pair without a trigger argument attached to
 * it.
 */
export function resolveRunSurfaceMotion(
  id: RunSurfaceMotionPrimitiveId,
  trigger: RunSurfaceMotionTrigger,
  prefersReducedMotion: boolean,
): ResolvedRunSurfaceMotion {
  if (trigger === undefined || trigger === null) {
    throw new Error(
      `resolveRunSurfaceMotion(${id}): a trigger naming the real agent event or state transition is required`,
    );
  }
  if (trigger.kind === "agent-event") {
    if (!AGENT_EVENT_TYPE_SET.has(trigger.eventType)) {
      throw new Error(
        `resolveRunSurfaceMotion(${id}): "${String(trigger.eventType)}" is not one of the 8 known agent event types`,
      );
    }
  } else if (trigger.kind === "state-transition") {
    if (!trigger.from || !trigger.to) {
      throw new Error(
        `resolveRunSurfaceMotion(${id}): a state-transition trigger requires non-empty "from" and "to"`,
      );
    }
  } else {
    throw new Error(`resolveRunSurfaceMotion(${id}): unknown trigger kind`);
  }

  const entry = RUN_SURFACE_MOTION_TABLE[id];
  if (!entry) {
    throw new Error(`resolveRunSurfaceMotion: unknown motion primitive id "${id}"`);
  }

  const timing = prefersReducedMotion ? entry.reducedMotion : entry.full;
  return { id, trigger, reduced: prefersReducedMotion, ...timing };
}

/** Reads the live `prefers-reduced-motion` media query -- the same
 *  pattern `recommendations-panel.tsx` already uses, centralized here so
 *  every run-surface consumer reads it the same way. Callers pass the
 *  boolean into `resolveRunSurfaceMotion` rather than that function
 *  reading `window` itself, which keeps it pure and unit-testable without
 *  a DOM. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
