"use client";

/**
 * The partner reviewer guide's state and auto-tick seam (fast track P77).
 * Only a reviewer account gets a live guide: for a seller (or the signed-out
 * door) the context is inert and `useGuideMark()` is a no-op, so any page may
 * call it. Presentation only — no backend call anywhere.
 */

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { GUIDE_STEPS, type GuideStepId } from "./guide-copy";
import { GUIDE_INITIAL, guideUserId, readGuideState, writeGuideState, type GuideState } from "./guide-store";
import { isSandboxReviewer, useReviewer } from "./mode";

export interface ReviewerGuideApi {
  /** False for a seller: nothing renders. */
  readonly enabled: boolean;
  readonly state: GuideState;
  readonly mark: (id: GuideStepId) => void;
  readonly toggle: (id: GuideStepId) => void;
  readonly reset: () => void;
  readonly setOpen: (open: boolean) => void;
}

const NOOP_API: ReviewerGuideApi = {
  enabled: false,
  state: GUIDE_INITIAL,
  mark: () => undefined,
  toggle: () => undefined,
  reset: () => undefined,
  setOpen: () => undefined,
};

const ReviewerGuideContext = createContext<ReviewerGuideApi>(NOOP_API);

export function useReviewerGuide(): ReviewerGuideApi {
  return useContext(ReviewerGuideContext);
}

/** Tick a step when the reviewer does the thing; a no-op outside a reviewer account. */
export function useGuideMark(): (id: GuideStepId) => void {
  return useContext(ReviewerGuideContext).mark;
}

function LiveGuideProvider({ userId, children }: { readonly userId: string; readonly children: ReactNode }) {
  const reviewer = useReviewer();
  const pathname = usePathname() ?? "/";
  const [state, setState] = useState<GuideState>(() => readGuideState(userId));
  const latest = useRef(state);

  const commit = useCallback(
    (next: GuideState) => {
      latest.current = next;
      setState(next);
      writeGuideState(userId, next);
    },
    [userId],
  );

  const mark = useCallback(
    (id: GuideStepId) => {
      if (latest.current.done.includes(id)) return;
      commit({ ...latest.current, done: [...latest.current.done, id] });
    },
    [commit],
  );
  const toggle = useCallback(
    (id: GuideStepId) => {
      const done = latest.current.done.includes(id)
        ? latest.current.done.filter((entry) => entry !== id)
        : [...latest.current.done, id];
      commit({ ...latest.current, done });
    },
    [commit],
  );
  const reset = useCallback(() => commit({ ...latest.current, done: [] }), [commit]);
  const setOpen = useCallback((open: boolean) => commit({ ...latest.current, open }), [commit]);

  // Steps 1-2: visiting Trang chủ / Phân tích on the masked shop (sample shop included).
  const sandbox = isSandboxReviewer(reviewer);
  useEffect(() => {
    if (sandbox) return;
    if (pathname === "/") mark("home");
    else if (pathname === "/analytics" || pathname.startsWith("/analytics/")) mark("analysis");
  }, [pathname, sandbox, mark]);

  // Step 4 for an account with a single (sandbox) pin: there is no menu entry to use.
  const pinCount = reviewer?.shops?.length ?? 0;
  useEffect(() => {
    if (sandbox && pinCount < 2) mark("switch");
  }, [sandbox, pinCount, mark]);

  const api = useMemo<ReviewerGuideApi>(
    () => ({ enabled: true, state, mark, toggle, reset, setOpen }),
    [state, mark, toggle, reset, setOpen],
  );
  return <ReviewerGuideContext.Provider value={api}>{children}</ReviewerGuideContext.Provider>;
}

export function ReviewerGuideProvider({ children }: { readonly children: ReactNode }) {
  const reviewer = useReviewer();
  if (!reviewer) {
    return <ReviewerGuideContext.Provider value={NOOP_API}>{children}</ReviewerGuideContext.Provider>;
  }
  const userId = guideUserId();
  return (
    <LiveGuideProvider key={userId} userId={userId}>
      {children}
    </LiveGuideProvider>
  );
}

export const GUIDE_TOTAL = GUIDE_STEPS.length;
