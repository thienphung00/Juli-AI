const CLICK_ID_STORAGE_KEY = "juli_tiktok_click_id";
const CLICK_ID_QUERY_PARAM = "ttclid";

/**
 * TikTok's click id is the strongest signal that a conversion belongs to a
 * particular ad click, and it is handed over exactly once: as a `ttclid` query
 * parameter on the ad's landing URL. The pixel's own `_ttp` cookie does not
 * carry it, and it is gone the moment the visitor navigates.
 *
 * So capture it on arrival and keep it. Every later event in the same browser
 * — a demo click three pages on, a sign-up next week — then carries the click
 * that produced it.
 *
 * Deliberately not scoped to the session: the interval between seeing an ad
 * and signing up is the thing being measured, and a sessionStorage copy would
 * drop every conversion that takes more than one sitting.
 */
export function captureTikTokClickId(search: string = window.location.search): void {
  let clickId: string | null;

  try {
    clickId = new URLSearchParams(search).get(CLICK_ID_QUERY_PARAM);
  } catch {
    return;
  }

  if (!clickId) {
    return;
  }

  try {
    window.localStorage.setItem(CLICK_ID_STORAGE_KEY, clickId);
  } catch {
    // Storage disabled. The in-flight event still carries the id via the URL
    // read above; only later events lose it.
  }
}

export function readTikTokClickId(): string | undefined {
  let stored: string | null = null;

  try {
    stored = window.localStorage.getItem(CLICK_ID_STORAGE_KEY);
  } catch {
    stored = null;
  }

  if (stored) {
    return stored;
  }

  // Same page load as the ad click, with storage unavailable.
  try {
    return new URLSearchParams(window.location.search).get(CLICK_ID_QUERY_PARAM) ?? undefined;
  } catch {
    return undefined;
  }
}

export { CLICK_ID_QUERY_PARAM, CLICK_ID_STORAGE_KEY };
