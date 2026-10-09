/**
 * Browser storage for the seller's sign-in (`supabase-auth.ts`) and active
 * shop (`shop-session.ts`): `localStorage`, Supabase's own default, so a
 * signed-in seller stays signed in across new tabs and a browser restart.
 *
 * Every access is wrapped: the storage accessor itself throws in some
 * privacy modes and with blocked site data, and `setItem` throws when full.
 * A value an older build wrote to `sessionStorage` is moved over once, on
 * the first read. Pure browser-storage module — no network call site.
 */

type StorageName = "localStorage" | "sessionStorage";

function storage(name: StorageName): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window[name] ?? null;
  } catch {
    return null;
  }
}

function get(name: StorageName, key: string): string | null {
  try {
    return storage(name)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function set(name: StorageName, key: string, value: string): boolean {
  const store = storage(name);
  if (!store) return false;
  try {
    store.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function remove(name: StorageName, key: string): void {
  try {
    storage(name)?.removeItem(key);
  } catch {
    // nothing to clear in a store we cannot open
  }
}

/** Reads `key` from localStorage; a value left in sessionStorage by an older build is migrated once. */
export function readPersistent(key: string): string | null {
  const stored = get("localStorage", key);
  if (stored !== null) return stored;
  const legacy = get("sessionStorage", key);
  if (legacy === null) return null;
  if (set("localStorage", key, legacy)) remove("sessionStorage", key);
  return legacy;
}

/** Writes `key` to localStorage (sessionStorage when localStorage is unavailable). */
export function writePersistent(key: string, value: string): void {
  if (set("localStorage", key, value)) {
    remove("sessionStorage", key);
    return;
  }
  set("sessionStorage", key, value);
}

/** Clears `key` from both stores (sign-out). */
export function removePersistent(key: string): void {
  remove("localStorage", key);
  remove("sessionStorage", key);
}
