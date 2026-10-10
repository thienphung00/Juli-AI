"use client";

import { useEffect, useState } from "react";

import { AcceptInvite } from "../../components/accept-invite";

/** /nhan-shop#<token> — the e-mailed link keeps the token in the fragment (never sent to a server). */
export default function AcceptInvitePage() {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const timer = window.setTimeout(() => setToken(window.location.hash.replace(/^#/, "") || null), 0);
    return () => window.clearTimeout(timer);
  }, []);
  if (token === undefined) return null;
  return <AcceptInvite inviteToken={token} />;
}
