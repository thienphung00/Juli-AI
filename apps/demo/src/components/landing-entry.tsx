"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { readEntryMode, writeEntryMode } from "../lib/entry-mode";
import { isTrialSignupSearch } from "../lib/trial-signup-copy";

/**
 * What `/` shows a signed-out visitor: the auth screen, or the sample demo
 * ("Xem thử với dữ liệu mẫu", formerly "Dùng thử Demo"). P34-F (D44.5) lifts
 * this read out of `DemoLanding` into the shell, because the shell must know
 * it too: the auth screen renders with NO app shell, the sample demo keeps it.
 *
 * Same rules as before the lift (ADR-094, issues #1907, D43 additions):
 * - "replay" stored in this tab session → the sample Home on a bare `/`;
 * - `/?entry=door` and `/?dang-ky=dung-thu` force the auth screen anyway, the
 *   latter in its trial variant.
 * The URL and sessionStorage are read in one deferred callback (never during
 * SSR, so server and client agree on the first paint; never `useSearchParams`,
 * which would force a Suspense boundary around the prerendered landing).
 */

export interface LandingEntry {
  /** The deferred read has run. Until then nothing is decided. */
  readonly resolved: boolean;
  readonly trial: boolean;
  readonly forceDoor: boolean;
  readonly enteredReplay: boolean;
  /** "Xem thử với dữ liệu mẫu": local, session-scoped state only, calls nothing. */
  readonly enterReplay: () => void;
  readonly setTrial: (trial: boolean) => void;
}

const LandingEntryContext = createContext<LandingEntry | null>(null);

function useLandingEntryState(readKey: string): LandingEntry {
  const [resolved, setResolved] = useState(false);
  const [trial, setTrial] = useState(false);
  const [forceDoor, setForceDoor] = useState(false);
  const [enteredReplay, setEnteredReplay] = useState(false);

  // Deferred via setTimeout(0) rather than set synchronously in the effect
  // body (`react-hooks/set-state-in-effect`), like `demo-state.tsx`. All
  // reads land in the same callback (one React batch), so the auth-screen
  // vs sample decision is made once — never a flash of the sample Home
  // before the escape param is honoured.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const search = window.location.search;
      const isTrial = isTrialSignupSearch(search);
      setTrial(isTrial);
      setForceDoor(isTrial || new URLSearchParams(search).get("entry") === "door");
      setEnteredReplay(readEntryMode() === "replay");
      setResolved(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [readKey]);

  const enterReplay = useCallback(() => {
    writeEntryMode("replay");
    setEnteredReplay(true);
    setForceDoor(false);
  }, []);

  return useMemo(
    () => ({ resolved, trial, forceDoor, enteredReplay, enterReplay, setTrial }),
    [resolved, trial, forceDoor, enteredReplay, enterReplay],
  );
}

/** Mounted by `DemoShell`; re-reads on every pathname change (`readKey`). */
export function LandingEntryProvider({ readKey, children }: { readKey: string; children: ReactNode }) {
  const value = useLandingEntryState(readKey);
  return <LandingEntryContext.Provider value={value}>{children}</LandingEntryContext.Provider>;
}

/**
 * The shell's value when mounted inside `DemoShell`; otherwise (a component
 * rendered alone, as in unit tests) the same read, local to the caller.
 */
export function useLandingEntry(): LandingEntry {
  const shared = useContext(LandingEntryContext);
  const local = useLandingEntryState("local");
  return shared ?? local;
}

/** True when a signed-out `/` shows the sample demo rather than the auth screen. */
export function showsSampleDemo(entry: Pick<LandingEntry, "enteredReplay" | "forceDoor">): boolean {
  return entry.enteredReplay && !entry.forceDoor;
}
