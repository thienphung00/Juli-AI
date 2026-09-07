/**
 * Stage navigation math for the staged run view (issue #1316, ADR-076
 * decision 3, PUI-DESIGN.md §2): frozen past, revisitable; live edge,
 * always reachable; anything beyond, locked -- unreachable by click, by
 * keyboard, and by direct URL.
 *
 * Pure and stateless on purpose: no React, no `window`, no clock. The
 * component owns *when* to call these (a click, a keydown, a mount reading
 * `?stage=`); this module owns only "is that move allowed" and "what index
 * does a stage id resolve to," so the clamping rule lives in exactly one
 * place regardless of which input triggered the navigation attempt.
 */

import { RUN_STAGE_IDS, type RunStageId } from "./reduce-run-view";

/** Index of a stage id in the fixed six-stage order. */
export function stageIndexOf(id: RunStageId): number {
  return RUN_STAGE_IDS.indexOf(id);
}

/** Clamps a requested index into `[0, liveEdgeIndex]` -- the only range a
 *  stage may ever be displayed from. Negative or beyond-live-edge requests
 *  both clamp rather than error, because every caller of this (a URL param,
 *  a stale click) is an untrusted request, not a programming error. */
export function clampStageIndex(requestedIndex: number, liveEdgeIndex: number): number {
  if (requestedIndex < 0) return 0;
  if (requestedIndex > liveEdgeIndex) return liveEdgeIndex;
  return requestedIndex;
}

/**
 * Resolves what stage a page load should open on, from an untrusted
 * requested stage id (typically a `?stage=` search param -- "direct URL"
 * in the acceptance criteria's language). An unknown id, an empty id, or a
 * locked stage's id all resolve to the live edge -- never to the
 * requested-but-locked stage. This is the one function a route/page needs
 * to call to satisfy "unreachable by direct URL": it never returns an
 * index beyond `liveEdgeIndex`.
 */
export function resolveRequestedStageIndex(
  requestedStageId: string | null | undefined,
  liveEdgeId: RunStageId,
): number {
  const liveEdgeIndex = stageIndexOf(liveEdgeId);
  if (!requestedStageId) return liveEdgeIndex;
  const requestedIndex = RUN_STAGE_IDS.indexOf(requestedStageId as RunStageId);
  if (requestedIndex === -1) return liveEdgeIndex;
  return clampStageIndex(requestedIndex, liveEdgeIndex);
}

/** Whether a stage at `index` can be navigated to given the current live
 *  edge -- the single predicate every click handler and keyboard handler
 *  gates on, so "unreachable by click" and "unreachable by keyboard" are
 *  proven by the same check rather than two independently-maintained ones. */
export function canNavigateToStageIndex(index: number, liveEdgeIndex: number): boolean {
  return index >= 0 && index <= liveEdgeIndex;
}
