// Platform-free configuration of the Connector core. The API origin is baked in at build time
// (scripts/build.mjs replaces __JULI_API_ORIGIN__); it must match the manifest's host permission.

declare const __JULI_API_ORIGIN__: string;

export const API_ORIGIN: string =
  typeof __JULI_API_ORIGIN__ === "string" ? __JULI_API_ORIGIN__ : "https://api.app-juli.com";

// -- the shared daily request budget (P97 T1) -------------------------------------------------
/**
 * ONE budget for every request the Connector sends to a seller centre in a GMT+7 day: the readers,
 * the daily sync and the backfill all count. Checked before every replay; when it is spent the
 * remaining jobs wait for the next day. Tunable.
 */
export const DAILY_REQUEST_BUDGET = 800;
/**
 * The budget is split (0.3.15): today's readers (orders, traffic, ads, affiliate, daily sync) keep
 * TODAY_REQUEST_RESERVE requests that the 30-day backfill can never touch, and while a backfill is
 * running it keeps BACKFILL_REQUEST_SHARE that the readers leave alone, so neither starves the other.
 */
export const TODAY_REQUEST_RESERVE = 250;
export const BACKFILL_REQUEST_SHARE = 150;
/** 0.3.30: requests readers (incl. catch-up) never touch, so a fill or a read-back always has room for its page loads. */
export const FILL_REQUEST_RESERVE = 60;
/** A report page makes a handful of calls of its own when it loads: each opened tab is counted as this many. */
export const READER_PAGE_LOAD_COST = 10;

// -- the fill engine (p91 D-13) ---------------------------------------------------------------

/** The address fragment the Juli button adds: `#juli-fill=JC-2611-0007`. Only the card's code. */
export const FILL_HASH_KEY = "juli-fill";
export const FILL_CODE_PATTERN = /^JC-\d{4}-\d{4,}$/;
/** How long the page gets to draw its form before the Connector gives up and offers copy buttons. */
export const FILL_WAIT_MS = 25_000;
export const FILL_POLL_MS = 400;
/**
 * 0.3.20: the edit page loads the product into the form AFTER the controls appear and overwrites
 * what was typed too early (2026-11-15). A control is written only once its value has
 * not changed for FILL_STABLE_MS; FILL_RECHECK_MS after a write it is read again and written once
 * more if it reverted, up to FILL_MAX_REWRITES times. A field counts as filled only if the last read
 * equals the target.
 */
export const FILL_STABLE_MS = 800;
export const FILL_RECHECK_MS = 1_500;
export const FILL_MAX_REWRITES = 3;
/**
 * 0.3.24: a fill job waits for the page's form to be drawn (the form's probe) and then for the
 * page to stop changing (no DOM mutation for FILL_QUIET_MS) before it types anything; after the
 * whole form is typed every field is read again FILL_CONFIRM_MS later, and the panel keeps
 * watching for FILL_WATCH_MS (every FILL_WATCH_POLL_MS) so a value the page puts back turns ✗.
 */
export const FILL_QUIET_MS = 1_200;
export const FILL_CONFIRM_MS = 3_000;
export const FILL_WATCH_MS = 12_000;
export const FILL_WATCH_POLL_MS = 2_000;
/**
 * 0.3.27 (E10, E42, F2.6): after the panel is up the page is followed for FILL_FOLLOW_MS: every
 * FILL_WATCH_POLL_MS the fields are read again (a step the person fixed by hand turns ✓, one the
 * page changed back turns ✗; a change counts once it reads the same on two turns in a row), and
 * the person's save (the redirect to the list, the platform's success toast) is seen.
 */
export const FILL_FOLLOW_MS = 30 * 60_000;

// -- fill jobs (P97 D85.6): approved cards queued by Juli, opened and filled page by page -------
//
// The allowlist is "this token's shop" (a paired Connector): Juli serves jobs only for the token's
// own shop and only while its server flag CONNECTOR_FILL_LISTING is on (the kill switch).

export const FILL_JOBS_ACTIVE = true;
export const FILL_JOBS_ALARM = "juli-fill-jobs";
export const FILL_JOBS_POLL_MINUTES = 3;
/** Jobs with no progress after this long are given up (the tab may have been closed). */
export const FILL_JOB_STALE_MS = 6 * 3_600_000;
/** A password prompt on a fill page stops that pairing's pages for this long (like a login wall). */
export const FILL_HALT_MS = 6 * 3_600_000;
/** `#juli-fill=<job id>` -- the job's UUID. */
export const FILL_JOB_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** Fill jobs run for the paired token's shop; the server decides whether anything is served. */
export function fillJobsActive(shopId: string | undefined): boolean {
  return FILL_JOBS_ACTIVE && !!shopId;
}
