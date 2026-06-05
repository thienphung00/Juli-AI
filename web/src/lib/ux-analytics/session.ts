export const UX_SESSION_STORAGE_KEY = "juli_ux_session_id";

function createSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `ux-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Stable analytics session id for the browser tab (Phase 1 UX test). */
export function getUxSessionId(): string {
  if (typeof window === "undefined") {
    return "server";
  }

  try {
    const existing = sessionStorage.getItem(UX_SESSION_STORAGE_KEY);
    if (existing) return existing;

    const next = createSessionId();
    sessionStorage.setItem(UX_SESSION_STORAGE_KEY, next);
    return next;
  } catch {
    return createSessionId();
  }
}

export function clearUxSessionId(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(UX_SESSION_STORAGE_KEY);
}
