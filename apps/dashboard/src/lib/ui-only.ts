/** Local UI preview without backend (set NEXT_PUBLIC_UI_ONLY=1). */
export const isUiOnly = process.env.NEXT_PUBLIC_UI_ONLY === "1";

export interface DashboardEnvironment {
  NODE_ENV?: string;
  NEXT_PUBLIC_UI_ONLY?: string;
}

/**
 * Whether the reviewer-only demo login screen — and its placeholder-token
 * helper `loginAsReviewer` — should be reachable (#901).
 *
 * Reachable:
 *  - in local development and tests (`NODE_ENV !== "production"`);
 *  - in the App Review build, which explicitly opts in via
 *    `NEXT_PUBLIC_UI_ONLY=1` (see `infra/scripts/build-frontend-review.sh`,
 *    which asserts the login screen ships in that build).
 *
 * Hidden in a genuine production build (`NODE_ENV === "production"` with
 * `NEXT_PUBLIC_UI_ONLY` unset) so the placeholder token can never be
 * mistaken for a working login if this app is ever served in production.
 *
 * Takes an optional env object so both directions are unit-testable without
 * mutating the read-only `process.env.NODE_ENV` global; defaults to the
 * real process env at call time.
 */
export function isDemoLoginEnabled(
  env: DashboardEnvironment = process.env
): boolean {
  return env.NODE_ENV !== "production" || env.NEXT_PUBLIC_UI_ONLY === "1";
}

export const UI_ONLY_DEMO_USER = {
  id: "00000000-0000-4000-8000-000000000001",
  phone: "+84900000000",
};

export const UI_ONLY_DEMO_TOKEN = "ui-only-demo-token";

export const UI_ONLY_DEMO_SHOP = {
  id: "00000000-0000-4000-8000-000000000002",
  name: "Cửa hàng demo",
  tiktok_shop_id: "demo",
};
