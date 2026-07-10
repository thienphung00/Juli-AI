"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useWorkspaceMode } from "@/lib/mode-context";
import { postAuthPath } from "@/lib/workspace-mode";

type ModeGuardMode = "require-mode" | "require-no-mode";

/**
 * - require-mode: authenticated flows need a saved workspace mode → /mode-select
 * - require-no-mode: mode selection screen only when mode is not set yet
 */
export function useModeGuard(mode: ModeGuardMode): { loading: boolean } {
  const { mode: workspaceMode, isReady } = useWorkspaceMode();
  const router = useRouter();

  useEffect(() => {
    if (!isReady) return;

    if (mode === "require-mode" && !workspaceMode) {
      router.replace("/mode-select");
    } else if (mode === "require-no-mode" && workspaceMode) {
      router.replace("/");
    }
  }, [isReady, mode, workspaceMode, router]);

  const shouldRender =
    mode === "require-mode" ? Boolean(workspaceMode) : !workspaceMode;

  return { loading: !isReady || !shouldRender };
}

export function usePostAuthRedirect(isAuthenticated: boolean, isAuthLoading: boolean): void {
  const router = useRouter();

  useEffect(() => {
    if (isAuthLoading || !isAuthenticated) return;
    router.replace(postAuthPath());
  }, [isAuthenticated, isAuthLoading, router]);
}
