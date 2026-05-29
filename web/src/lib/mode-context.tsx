"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  applyWorkspaceTheme,
  persistWorkspaceMode,
  readStoredWorkspaceMode,
  type WorkspaceMode,
} from "./workspace-mode";

interface ModeContextValue {
  mode: WorkspaceMode | null;
  isReady: boolean;
  setMode: (mode: WorkspaceMode) => void;
  clearMode: () => void;
}

const ModeContext = createContext<ModeContextValue | null>(null);

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<WorkspaceMode | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const stored = readStoredWorkspaceMode();
    setModeState(stored);
    if (stored) {
      applyWorkspaceTheme(stored);
    }
    setIsReady(true);
  }, []);

  const setMode = useCallback((next: WorkspaceMode) => {
    persistWorkspaceMode(next);
    applyWorkspaceTheme(next);
    setModeState(next);
  }, []);

  const clearMode = useCallback(() => {
    localStorage.removeItem("juli_workspace_mode");
    setModeState(null);
    document.documentElement.classList.remove("dark");
  }, []);

  const value = useMemo(
    () => ({ mode, isReady, setMode, clearMode }),
    [mode, isReady, setMode, clearMode]
  );

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useWorkspaceMode(): ModeContextValue {
  const ctx = useContext(ModeContext);
  if (!ctx) {
    throw new Error("useWorkspaceMode must be used within ModeProvider");
  }
  return ctx;
}

/** For shared shell components that render in tests without ModeProvider. */
export function useWorkspaceModeOptional(): ModeContextValue | null {
  return useContext(ModeContext);
}
