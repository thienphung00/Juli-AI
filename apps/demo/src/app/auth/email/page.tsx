"use client";

import { useEffect, useState } from "react";

import { AuthScreen, type AuthView } from "../../../components/auth/auth-screen";
import { PartnerSignIn, denialFromLocation } from "../../../components/partner-sign-in";
import { writeEntryMode } from "../../../lib/entry-mode";
import { isTrialSignupSearch } from "../../../lib/trial-signup-copy";

/**
 * `/auth/email` — the auth screen (P34-F, D44.5) where the shop-avatar menu's
 * "Đăng nhập bằng email" leads (email field focused), and the only page that
 * carries the partner password form (`#doi-tac`, P32-A): the landing's footer
 * link and the shell's reviewer denial (`?doi-tac=<reason>#doi-tac`) open it
 * here, in the partner view. Same screen, same flows as `/`.
 */

function enterSampleFromHere() {
  writeEntryMode("replay");
  window.location.assign("/");
}

export default function EmailSignInPage() {
  const [trial, setTrial] = useState(false);
  const [initialView, setInitialView] = useState<AuthView>("entry");

  // Read after mount, never during SSR (same as the landing's entry read).
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTrial(isTrialSignupSearch(window.location.search));
      if (window.location.hash === "#doi-tac" || denialFromLocation(window.location.search)) {
        setInitialView("partner");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <AuthScreen
      focusEmail={initialView === "entry"}
      initialView={initialView}
      // Remount when the deferred read picks the partner view.
      key={initialView}
      onEnterSample={enterSampleFromHere}
      onTrialChange={setTrial}
      renderPartner={() => <PartnerSignIn />}
      trial={trial}
    />
  );
}
