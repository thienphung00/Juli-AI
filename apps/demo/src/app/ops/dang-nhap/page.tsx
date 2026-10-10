"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { describeAuthCallbackError, parseAuthCallbackHash, storeAuthSession } from "../../../lib/supabase-auth";

/** The ops host's own Google sign-in landing (its session lives in its own origin). */
export default function OpsSignInCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const fromHash = parseAuthCallbackHash(window.location.hash);
      const result = fromHash.status === "empty" ? parseAuthCallbackHash(window.location.search.replace(/^\?/, "")) : fromHash;
      if (result.status === "success") {
        storeAuthSession(result.session);
        router.replace("/ops");
        return;
      }
      setError(result.status === "error" ? describeAuthCallbackError(result.message, result.errorCode) : "Không nhận được thông tin đăng nhập.");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [router]);
  return <main style={{ padding: 28, fontFamily: "system-ui" }}>{error ? <p role="alert">{error}</p> : <p role="status">Đang đăng nhập…</p>}</main>;
}
