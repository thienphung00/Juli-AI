"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

type AuthGuardMode = "require-auth" | "require-guest";

/**
 * Redirects based on auth state:
 *  - "require-auth": unauthenticated users → /login
 *  - "require-guest": authenticated users → /
 */
export function useAuthGuard(mode: AuthGuardMode): { loading: boolean } {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;

    if (mode === "require-auth" && !isAuthenticated) {
      router.replace("/login");
    } else if (mode === "require-guest" && isAuthenticated) {
      router.replace("/");
    }
  }, [isAuthenticated, isLoading, mode, router]);

  const shouldRender =
    mode === "require-auth" ? isAuthenticated : !isAuthenticated;

  return { loading: isLoading || !shouldRender };
}
