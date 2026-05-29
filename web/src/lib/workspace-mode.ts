export type WorkspaceMode = "seller" | "affiliate";

export const WORKSPACE_MODE_STORAGE_KEY = "juli_workspace_mode";

export function isWorkspaceMode(value: string | null): value is WorkspaceMode {
  return value === "seller" || value === "affiliate";
}

export function readStoredWorkspaceMode(): WorkspaceMode | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY);
  return isWorkspaceMode(stored) ? stored : null;
}

export function persistWorkspaceMode(mode: WorkspaceMode): void {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
}

export function clearStoredWorkspaceMode(): void {
  localStorage.removeItem(WORKSPACE_MODE_STORAGE_KEY);
}

/** Post-login destination when workspace mode is already set. */
export function postAuthPath(): string {
  return readStoredWorkspaceMode() ? "/" : "/mode-select";
}

export function applyWorkspaceTheme(mode: WorkspaceMode): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (mode === "seller") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}
