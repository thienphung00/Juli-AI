/**
 * Canonical constants for the scoped run-surface visual identity
 * (`packages/theme/run-surface-tokens.css`, PUI-DESIGN.md §6, issue #1314 /
 * AGT-W6A). Downstream view slices (#1316 staged run view, #1317 option
 * picker, #1318 ledger) import these instead of hand-typing the attribute
 * name or the live-edge class names, so the scope contract and the "one
 * accent, three surfaces" rule cannot drift between this token layer and
 * its consumers.
 *
 * `packages/theme/__tests__/run-surface-tokens.test.ts` is the source of
 * truth for what the CSS actually enforces; `__tests__/tokens.test.ts`
 * alongside this file cross-checks that every string below is exactly
 * what that CSS file defines.
 */

/** The attribute a run-surface root element carries to opt into the
 *  scoped token layer -- e.g. `<div data-juli-surface="run">`. */
export const RUN_SURFACE_DATA_ATTRIBUTE = "data-juli-surface";

/** The attribute's value for the run surface (as opposed to some other
 *  future scoped surface reusing the same attribute name). */
export const RUN_SURFACE_DATA_VALUE = "run";

/**
 * The exact three class names the CSS layer treats as the live edge --
 * the only rules allowed to reference `--juli-run-live-edge`. A consumer
 * that needs the accent for anything else is, by definition, using it for
 * "ordinary emphasis," which `packages/theme/__tests__/run-surface-tokens
 * .test.ts` rejects.
 */
export const RUN_SURFACE_LIVE_EDGE_CLASS_NAMES = Object.freeze({
  /** The active node in the top stepper (PUI-DESIGN.md §2). */
  stepperNodeActive: "juli-run-stepper-node--active",
  /** The streaming caret trailing `assistant.text` reveal. */
  streamingCaret: "juli-run-streaming-caret",
  /** The armed "Xác nhận phương án này" CTA (PUI-DESIGN.md §3). */
  ctaArmed: "juli-run-cta--armed",
} as const);

/** General ground/panel utility class names, none of which touch the
 *  live-edge accent. */
export const RUN_SURFACE_PANEL_CLASS_NAMES = Object.freeze({
  panel: "juli-run-panel",
  panelRaised: "juli-run-panel--raised",
  textMuted: "juli-run-text-muted",
  narration: "juli-run-narration",
} as const);
