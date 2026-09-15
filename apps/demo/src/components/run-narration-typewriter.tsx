"use client";

/**
 * The block-paced typewriter over the Phân tích narration (issue #1915,
 * PUI-DESIGN.md §5 row 2 -- `assistant.text`). This is the
 * `assistant-text-reveal` primitive's consumer: each line the stream
 * appends to `view.narration` reveals character by character at the §5
 * ~30ms/char cap, with the caret element carrying
 * `RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.streamingCaret` while the line
 * reveals and gone once it settles.
 *
 * THE TRIGGER IS THE EVENT, NEVER A TIMER. The reveal starts only when
 * `lines` grows past what has already settled -- i.e. when a real
 * `assistant.text` event arrived and the reducer appended its text --
 * and that is the trigger passed to `resolveRunSurfaceMotion`. The
 * interval below merely plays out the resolved per-character timing for
 * a reveal that was already triggered, the same way a CSS animation
 * plays out its duration; nothing here schedules or paces EVENTS.
 * Replay pacing stays in `use-replay-events.ts` -- this module adds no
 * second clock to it.
 *
 * HISTORY IS NOT REPLAYED. Narration present at mount was not delivered
 * by an event in this session (a finished run opens fully frozen; a
 * frozen-stage snapshot remounts with history), so it renders whole with
 * no motion and no timer. Only lines appended after mount animate.
 *
 * REDUCED MOTION renders §5's stated alternative -- the full line fades
 * in at once (150ms ease-out), no caret, no per-character timer.
 *
 * ACCESSIBILITY: while a line reveals, the partial text is aria-hidden
 * churn; the full line is exposed to assistive tech immediately via a
 * visually-hidden span, so a screen reader never hears a word split
 * mid-reveal.
 */

import { useEffect, useState } from "react";

import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import { RUN_STAGE_EMPTY_COPY } from "../lib/run-surface/stage-copy";
import {
  RUN_SURFACE_LIVE_EDGE_CLASS_NAMES,
  RUN_SURFACE_PANEL_CLASS_NAMES,
} from "../lib/run-surface/tokens";

export interface RunNarrationTypewriterProps {
  /** `view.narration` -- append-only, one entry per assistant.text event. */
  readonly lines: readonly string[];
}

function joinClassNames(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(" ");
}

export function RunNarrationTypewriter({ lines }: RunNarrationTypewriterProps) {
  // The mount baseline: everything before this index is history and
  // renders whole, motionless.
  const [initialCount] = useState(() => lines.length);
  const [settledCount, setSettledCount] = useState(initialCount);
  const [revealedChars, setRevealedChars] = useState(0);

  const reduced = prefersReducedMotion();

  // "Adjusting state when a prop changes" -- the sanctioned
  // conditional-setState-during-render pattern `run-staged-view.tsx`
  // already uses: settle the revealing line the render after its last
  // character appears, and settle everything instantly under reduced
  // motion (§5: the alternative is a whole-line fade, not a slower type).
  if (reduced && settledCount < lines.length) {
    setSettledCount(lines.length);
    setRevealedChars(0);
  } else if (
    settledCount < lines.length &&
    revealedChars >= lines[settledCount]!.length
  ) {
    setSettledCount(settledCount + 1);
    setRevealedChars(0);
  }

  const revealingIndex = !reduced && settledCount < lines.length ? settledCount : null;
  const revealingLine = revealingIndex !== null ? lines[revealingIndex]! : null;

  // The per-character cadence for a reveal the assistant.text event
  // already triggered. The primitive's full-motion durationMs IS §5's
  // ~30ms/char cap (see RUN_SURFACE_MOTION_TABLE).
  useEffect(() => {
    if (revealingLine === null) return;
    const motion = resolveRunSurfaceMotion(
      "assistant-text-reveal",
      { kind: "agent-event", eventType: "assistant.text" },
      false,
    );
    const timer = window.setInterval(() => {
      setRevealedChars((chars) => chars + 1);
    }, motion.durationMs);
    return () => window.clearInterval(timer);
  }, [revealingLine]);

  if (lines.length === 0) {
    // Owning the empty state keeps this component MOUNTED from the
    // stage's first render, so the very first assistant.text line is
    // "appended after mount" -- i.e. a real trigger -- rather than
    // being swallowed into the mount baseline.
    return (
      <p className={RUN_SURFACE_PANEL_CLASS_NAMES.narration}>
        {RUN_STAGE_EMPTY_COPY["phan-tich"]}
      </p>
    );
  }

  return (
    <div>
      {lines.map((line, index) => {
        if (revealingIndex !== null && index > revealingIndex) {
          // Queued behind the line currently revealing -- it has not
          // visually "arrived" yet.
          return null;
        }

        const isRevealing = index === revealingIndex;
        // A line at or past the mount baseline arrived via a real
        // assistant.text event in this session; under reduced motion it
        // gets §5's whole-line fade-in.
        const fadeMotion =
          reduced && index >= initialCount
            ? resolveRunSurfaceMotion(
                "assistant-text-reveal",
                { kind: "agent-event", eventType: "assistant.text" },
                true,
              )
            : null;

        return (
          <p
            className={joinClassNames(
              RUN_SURFACE_PANEL_CLASS_NAMES.narration,
              fadeMotion ? "run-stage__narration-line--fade" : undefined,
            )}
            key={index}
            style={
              fadeMotion
                ? {
                    animationDuration: `${fadeMotion.durationMs}ms`,
                    animationTimingFunction: fadeMotion.easing,
                  }
                : undefined
            }
          >
            {isRevealing ? (
              <>
                <span className="juli-sr-only">{line}</span>
                <span aria-hidden="true" className="run-stage__narration-reveal">
                  {line.slice(0, Math.min(revealedChars, line.length))}
                  <span
                    aria-hidden="true"
                    className={RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.streamingCaret}
                  />
                </span>
              </>
            ) : (
              line
            )}
          </p>
        );
      })}
    </div>
  );
}
