"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AnalyticsDataProvider, useAnalyticsData } from "../lib/analytics/analytics-data-context";
import { looksLikeRunId } from "../lib/run-surface/run-id";
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
 *
 * The real run route (`/decisions/in-progress/<run id>`, issue #1910) keeps
 * only the rail; the run surface owns everything to its right.
 */

const RUN_DETAIL_PATH_PATTERN = /^\/decisions\/in-progress\/([^/]+)\/?$/;

function isRunFocusRoute(pathname: string): boolean {
  const match = RUN_DETAIL_PATH_PATTERN.exec(pathname);
  return match !== null && looksLikeRunId(match[1]);
}

function DemoShellContent({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const { feedback, resetMockState } = useDemoState();
  const { refreshAnalytics } = useAnalyticsData();
  const { state } = useShopReport();
  const reviewer = useReviewer();

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

  if (isRunFocusRoute(pathname)) {
    return (
      <div className="app-shell app-shell--run">
        <AppNavigation activePath={pathname} />
        <div className="app-shell__main">
          {reviewer ? <ReviewerBanner onReset={handleResetSample} reviewer={reviewer} /> : null}
          <main className="app-content app-content--run">{page}</main>
        </div>
      </div>
    );
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
            <DemoShellContent>{children}</DemoShellContent>
          </ReviewerProvider>
        </ShopReportProvider>
      </AnalyticsDataProvider>
    </DemoStateProvider>
  );
}
