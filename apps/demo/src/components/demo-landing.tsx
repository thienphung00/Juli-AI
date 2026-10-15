"use client";

import { AuthScreen } from "./auth/auth-screen";
import { SampleHome } from "./home/sample-home";
import { showsSampleDemo, useLandingEntry } from "./landing-entry";

/**
 * `/` for a signed-out visitor (ADR-094; redesigned in P34-F, D44.5): the
 * auth screen (`AuthScreen`, no app shell), or — once the visitor chose
 * "Xem thử với dữ liệu mẫu" in this tab session — the sample Home inside the
 * shell. The choice flips local, session-scoped state only; it calls nothing.
 *
 * `/?entry=door` (issue #1907) is the explicit escape from the stored sample
 * choice: a bare `/` with it stored still goes straight to the sample Home
 * (`SampleHome`, AC-8.5), unchanged. `/?dang-ky=dung-thu` (D43 additions) also
 * forces the auth screen, in its trial variant (copy only). The URL and
 * storage reads live in `landing-entry.tsx`, shared with `DemoShell`, which
 * must know the same answer to drop its chrome.
 */
export function DemoLanding() {
  const entry = useLandingEntry();

  if (showsSampleDemo(entry)) {
    return <SampleHome />;
  }

  return <AuthScreen onEnterSample={entry.enterReplay} onTrialChange={entry.setTrial} trial={entry.trial} />;
}
