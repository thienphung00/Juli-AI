/**
 * Landing-gate entry choice — deliberately its own storage key, independent
 * of `demo-state.tsx`'s `juli_demo_mode`/`juli_demo_mutable_state` (owned by
 * a concurrent slice). "replay" means the visitor picked Dùng thử Demo and
 * should skip straight back to the launcher on a later visit to `/` within
 * the same tab session; it implies nothing about identity or persistence —
 * ADR-094 decision 1 withdrew the anonymous session entirely.
 */
export const ENTRY_MODE_STORAGE_KEY = "juli_demo_entry_mode";

export type EntryMode = "unset" | "replay";

const VALID_ENTRY_MODES: readonly EntryMode[] = ["replay"];

export function readEntryMode(): EntryMode {
  if (typeof window === "undefined") {
    return "unset";
  }

  const stored = window.sessionStorage.getItem(ENTRY_MODE_STORAGE_KEY);

  return (VALID_ENTRY_MODES as readonly string[]).includes(stored ?? "")
    ? (stored as EntryMode)
    : "unset";
}

export function writeEntryMode(mode: EntryMode): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, mode);
}
