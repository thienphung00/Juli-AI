"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { parseAuthCallbackHash, storeAuthSession } from "../../../lib/supabase-auth";

type Phase =
  | { kind: "processing" }
  | { kind: "error"; message: string };

/**
 * Where Supabase's implicit-grant redirect lands after "Đăng nhập với
 * Google". Reads the `#access_token=...` (or `#error=...`) hash fragment
 * GoTrue appends to `redirect_to`, stores the real session, and moves on to
 * the connect-shop screen. A provider failure or an unexpectedly empty
 * callback renders a real, announced error — never a silent fall-through.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ kind: "processing" });

  useEffect(() => {
    // Deferred via setTimeout(0), matching `demo-state.tsx`'s established
    // pattern — `react-hooks/set-state-in-effect` forbids calling a setter
    // synchronously in the effect body.
    const timer = window.setTimeout(() => {
      const result = parseAuthCallbackHash(window.location.hash);

      if (result.status === "success") {
        storeAuthSession(result.session);
        router.replace("/auth/connect-shop");
        return;
      }

      if (result.status === "error") {
        setPhase({
          kind: "error",
          message: `Đăng nhập không thành công: ${result.message}`,
        });
        return;
      }

      setPhase({
        kind: "error",
        message:
          "Không nhận được thông tin đăng nhập từ Google. Vui lòng thử lại.",
      });
    }, 0);

    return () => window.clearTimeout(timer);
    // Runs once against the redirect this page was loaded with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase.kind === "error") {
    return (
      <section aria-labelledby="auth-callback-error-title" className="demo-placeholder">
        <p className="demo-kicker">Đăng nhập với Google</p>
        <h1 id="auth-callback-error-title">Không thể hoàn tất đăng nhập</h1>
        <p role="alert" aria-live="assertive">
          {phase.message}
        </p>
        <Link className="demo-placeholder__recovery" href="/">
          Về trang chào mừng
        </Link>
      </section>
    );
  }

  return (
    <section aria-labelledby="auth-callback-title" className="demo-placeholder">
      <p className="demo-kicker">Đăng nhập với Google</p>
      <h1 id="auth-callback-title">Đang xử lý đăng nhập…</h1>
      <p role="status" aria-live="polite">
        Đang xử lý đăng nhập…
      </p>
    </section>
  );
}
