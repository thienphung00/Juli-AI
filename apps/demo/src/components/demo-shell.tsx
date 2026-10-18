"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AnalyticsDataProvider, useAnalyticsData } from "../lib/analytics/analytics-data-context";
import { REVIEWER_READ_ONLY_TITLE } from "../lib/reviewer/copy";
import { ReviewerProvider, clearReviewerSignIn, useReviewer } from "../lib/reviewer/reviewer-context";
import { resetReviewerSample } from "../lib/reviewer/sample-store";
import { clearActiveShop } from "../lib/shop-session";
import { ShopReportProvider, useShopReport } from "../lib/shop-report/shop-report-context";
import { buildGoogleAuthorizeUrl, clearAuthSession } from "../lib/supabase-auth";
import { AppNavigation } from "./app-shell/app-navigation";
import { PermissionStrip } from "./app-shell/permission-strip";
import { ReviewerBanner } from "./app-shell/reviewer-banner";
import { TermStrip } from "./app-shell/term-strip";
import { ShopHeader } from "./app-shell/shop-header";
import { DemoStateProvider, useDemoState } from "./demo-state";
import { LandingEntryProvider, showsSampleDemo, useLandingEntry, type LandingEntry } from "./landing-entry";
import { SellerViewProvider } from "./seller-view-context";

/**
 * The app shell (AC-8.5, ADR-109 decisions 1, 7, 8) — the layout every page
 * renders inside, following the sales demo video:
 *
 *   ┌ rail ┐┌ ShopHeader (avatar menu · shop · "Juli đang chạy …") ┐
 *   │ nav  ││ <main class="app-content">  ← the page (the slot)     │
 *   └──────┘└────────────────────────────────────────────────────────┘
 *
 * Below 768px the rail becomes a bottom bar (CSS only, same `<nav>`).
 * Pages fill the slot with their own content and start with
 * `AppPageHeader` (`app-shell/page-header.tsx`) for the eyebrow + h1.
 * No global stepper (decision 8), no assistance aside, no mode toggle: the
 * former header controls (Đăng nhập, Làm mới Demo) and the former Cài đặt
 * tab live in the shop-avatar menu.
 */

/** The auth screen's own page: always bare (P34-F, D44.5). */
const AUTH_SCREEN_PATHS = new Set(["/auth/email"]);

/**
 * P34-F (D44.5): the signed-out sign-in screen renders WITHOUT the app shell
 * (no rail, no sample-shop header, no bottom tab bar). On `/` that is every
 * signed-out visit that is not showing the sample demo, and the moment before
 * the session and the entry choice are known (so the auth screen never
 * flashes inside the shell; a signed-in seller or a sample visitor gets the
 * shell one tick later, as they used to get "Đang tải…" inside it).
 */
export function rendersBare(
  pathname: string,
  status: string,
  entry: Pick<LandingEntry, "resolved" | "enteredReplay" | "forceDoor">,
): boolean {
  if (AUTH_SCREEN_PATHS.has(pathname)) return true;
  if (pathname !== "/") return false;
  if (status === "resolving") return true;
  if (status !== "anonymous") return false;
  return !entry.resolved || !showsSampleDemo(entry);
}

function DemoShellContent({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const { feedback, resetMockState } = useDemoState();
  const { refreshAnalytics } = useAnalyticsData();
  const { state } = useShopReport();
  const reviewer = useReviewer();
  const entry = useLandingEntry();

  // Đăng nhập (issue #1907) stays a real link to Supabase Auth, resolved on
  // mount (never during SSR) with the same builder the landing door uses.
  const [googleHref, setGoogleHref] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGoogleHref(buildGoogleAuthorizeUrl(`${window.location.origin}/auth/callback`));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const handleManualRefresh = () => {
    void refreshAnalytics();
    // P37: the sample store is tab-wide now — "Làm mới Demo" starts it over too.
    resetReviewerSample();
    resetMockState();
    router.replace("/decisions");
  };

  // P32-E: "Đặt lại dữ liệu mẫu" — a fresh sample store, every sample view remounts.
  const handleResetSample = () => {
    resetReviewerSample();
    resetMockState();
  };

  const handleSignOut = () => {
    resetReviewerSample();
    clearAuthSession();
    clearActiveShop();
    clearReviewerSignIn();
    // A full load, so every provider re-resolves the (now absent) session.
    window.location.assign("/?entry=door");
  };

  // P32-A: in the partner trial account pinned to a real shop every write
  // control of every page is read-only (Duyệt runs a simulation); the API
  // refuses the writes anyway. P32-E (D42 amendment 2): in the sample shop
  // (no pin) nothing is read-only — every write runs in the in-memory sample
  // store, labelled "Mô phỏng", and no shop route is ever called.
  const page = reviewer && !reviewer.sample ? (
    <SellerViewProvider readOnly readOnlyTitle={REVIEWER_READ_ONLY_TITLE} simulateApprove>
      {children}
    </SellerViewProvider>
  ) : (
    children
  );

  if (rendersBare(pathname, state.status, entry)) {
    return <>{children}</>;
  }

  return (
    <div className="app-shell">
      <AppNavigation activePath={pathname} />
      <div className="app-shell__main">
        <ShopHeader
          googleHref={googleHref}
          onRefreshDemo={handleManualRefresh}
          onSignOut={handleSignOut}
          reviewer={reviewer !== null}
          state={state}
        />
        {reviewer ? <ReviewerBanner onReset={handleResetSample} reviewer={reviewer} /> : null}
        <p aria-label="Phản hồi Demo" aria-live="polite" className="juli-sr-only" role="status">
          {feedback}
        </p>
        {state.status === "ready" ? <TermStrip shopId={state.shop.id} token={state.token} /> : null}
        {state.status === "ready" && !reviewer ? <PermissionStrip shopId={state.shop.id} token={state.token} /> : null}
        <main className="app-content">{page}</main>
      </div>
    </div>
  );
}

/** Juli Ops (P16) renders its own chrome: no seller shell, no seller providers. */
export function isOpsRoute(pathname: string): boolean {
  return pathname === "/ops" || pathname.startsWith("/ops/");
}

export function DemoShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  if (isOpsRoute(pathname)) {
    return <>{children}</>;
  }
  return (
    <DemoStateProvider>
      <AnalyticsDataProvider>
        <ShopReportProvider>
          <ReviewerProvider>
            <LandingEntryProvider readKey={pathname}>
              <DemoShellContent>{children}</DemoShellContent>
            </LandingEntryProvider>
          </ReviewerProvider>
        </ShopReportProvider>
      </AnalyticsDataProvider>
    </DemoStateProvider>
  );
}
