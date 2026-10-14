/**
 * The visitor's analytics-cookie choice (Nghị định 13/2023: consent before the
 * TikTok Pixel processes personal data). Stored per browser; `null` means the
 * visitor has not chosen yet, which is treated exactly like a refusal until
 * they do.
 *
 * Storage can be missing or throw (private mode, blocked site data), so every
 * access is guarded: the worst case is that the banner shows again.
 */
export type ConsentChoice = "granted" | "denied";

/** Bump the suffix when what the visitor consents to changes, to ask again. */
export const CONSENT_STORAGE_KEY = "juli-cookie-consent-v1";

/** Dispatched on `window` by the footer's settings button to reopen the banner. */
export const OPEN_CONSENT_EVENT = "juli:open-cookie-settings";

const CHANGE_EVENT = "juli:cookie-consent-change";

export function readConsent(): ConsentChoice | null {
  try {
    const value = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    return value === "granted" || value === "denied" ? value : null;
  } catch {
    return null;
  }
}

export function writeConsent(choice: ConsentChoice): void {
  try {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, choice);
  } catch {
    // Unpersisted: the choice still applies to this page view.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function subscribeConsent(onChange: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * Remove the first-party cookies the TikTok Pixel sets on this domain, for a
 * visitor who withdraws consent after granting it.
 */
export function clearTikTokCookies(): void {
  const host = window.location.hostname;
  for (const entry of document.cookie.split(";")) {
    const name = entry.split("=")[0]?.trim();
    if (!name || !/^(_ttp|_tt_|ttcsid)/.test(name)) {
      continue;
    }
    for (const domain of ["", `; domain=${host}`, `; domain=.${host}`]) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${domain}`;
    }
  }
}
