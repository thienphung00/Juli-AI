"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

type LegacyRouteRedirectProps = {
  destination?: string;
};

/** Client-side fallback when Next.js config redirect is not active (e.g. tests). */
export function LegacyRouteRedirect({ destination = "/" }: LegacyRouteRedirectProps) {
  const router = useRouter();

  useEffect(() => {
    router.replace(destination);
  }, [router, destination]);

  return (
    <div
      className="flex min-h-screen items-center justify-center"
      role="status"
      aria-live="polite"
      aria-label="Đang chuyển hướng"
    >
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
    </div>
  );
}
