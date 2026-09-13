"use client";

import { PrimaryNavigation } from "@juli/ui";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { demoDestinations } from "../lib/mock-data";
import { sanitizeSellerReviewText } from "../lib/review-seller-copy";
import { AnalyticsDataProvider, useAnalyticsData } from "../lib/analytics/analytics-data-context";
import {
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY,
  buildGoogleAuthorizeUrl,
} from "../lib/supabase-auth";
import { DemoStateProvider, useDemoState } from "./demo-state";

const assistanceByPath = {
  "/": {
    destination: "Trang chủ",
    message:
      "Juli là trợ lý phân tích và tự động hóa của bạn, giúp bạn hiểu rõ dữ liệu cửa hàng và đưa ra quyết định tối ưu.",
  },
  "/decisions": {
    destination: "Quyết định",
    message:
      "Juli sẽ giải thích lý do, bằng chứng và tác động của từng đề xuất để bạn tự đưa ra quyết định.",
  },
  "/analytics": {
    destination: "Phân tích",
    message:
      "Juli sẽ giúp bạn đọc thay đổi của KPI, nguồn dữ liệu và điều đáng chú ý trong khoảng thời gian đang chọn.",
  },
  "/settings": {
    destination: "Cài đặt",
    message:
      "Juli sẽ làm rõ cách mẫu quy trình và ngưỡng ảnh hưởng đến các đề xuất trong tương lai.",
  },
} as const;

function DemoShellContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    feedback,
    mode,
    recommendationContext,
    resetMockState,
  } = useDemoState();
  const { refreshAnalytics } = useAnalyticsData();

  // The header's "Đăng nhập" control (issue #1907) — the seller's only
  // sign-in affordance once past the landing gate, so it must stay a real
  // link to Supabase Auth rather than an internal `/` link that immediately
  // short-circuits back to HomeLauncher for anyone who already entered the
  // replay demo. Resolved on mount (never during SSR) via the same
  // `buildGoogleAuthorizeUrl` DemoLanding uses — never a second URL builder.
  const [googleHref, setGoogleHref] = useState<string | null | undefined>(
    undefined,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGoogleHref(
        buildGoogleAuthorizeUrl(`${window.location.origin}/auth/callback`),
      );
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  const googleConfigured = googleHref !== null && googleHref !== undefined;

  // Resolve assistance by prefix matching for nested routes
  const getAssistance = () => {
    if (pathname.startsWith("/decisions")) {
      return assistanceByPath["/decisions"];
    }
    if (pathname.startsWith("/analytics")) {
      return assistanceByPath["/analytics"];
    }
    if (pathname.startsWith("/settings")) {
      return assistanceByPath["/settings"];
    }
    // Exact match for home or fallback
    return (
      assistanceByPath[pathname as keyof typeof assistanceByPath] ??
      assistanceByPath["/"]
    );
  };

  const assistance = getAssistance();

  // Format recommendation context message with proper sanitization and spacing
  const assistanceMessage =
    pathname.startsWith("/decisions") && recommendationContext
      ? [
          recommendationContext.title,
          sanitizeSellerReviewText(recommendationContext.evidence),
          `Rủi ro: ${recommendationContext.risks}`,
        ]
          .filter((part) => part.trim())
          .join("\n\n")
      : assistance.message;

  const handleManualRefresh = () => {
    void refreshAnalytics();
    resetMockState();
    router.replace("/decisions");
  };

  return (
    <div className="demo-shell">
      <header className="demo-header">
        <Link className="demo-wordmark" href="/" aria-label="Juli — Trang chủ">
          Juli
        </Link>
        <div className="demo-header__actions">
          <div className="demo-mode-switcher" role="group" aria-label="Chế độ Demo">
            <button
              className="demo-mode-switcher__option"
              type="button"
              aria-pressed={mode === "mock"}
            >
              Bản minh họa
            </button>
            {googleConfigured ? (
              <a className="demo-mode-switcher__option" href={googleHref}>
                Đăng nhập
              </a>
            ) : (
              <span
                aria-disabled="true"
                className="demo-mode-switcher__option"
                role="link"
                title={GOOGLE_SIGN_IN_UNAVAILABLE_COPY}
              >
                Đăng nhập
              </span>
            )}
          </div>
          <button
            className="demo-refresh"
            type="button"
            aria-label="Làm mới Demo"
            onClick={handleManualRefresh}
          >
            <span aria-hidden="true">↻</span>
            <span className="demo-refresh__label">Làm mới Demo</span>
          </button>
        </div>
      </header>
      <p
        className="demo-feedback"
        role="status"
        aria-label="Phản hồi Demo"
        aria-live="polite"
      >
        {feedback}
      </p>
      <PrimaryNavigation
        activePath={pathname}
        destinations={demoDestinations}
        label="Điều hướng chính"
      />
      <main className="demo-main">{children}</main>
      <aside
        className="demo-assistance"
        aria-labelledby="demo-assistance-title"
      >
        <p className="demo-assistance__eyebrow">{assistance.destination}</p>
        <h2 id="demo-assistance-title">Gợi ý từ Juli</h2>
        <p>{assistanceMessage}</p>
        <p className="demo-assistance__boundary">
          Juli chỉ giải thích trong ngữ cảnh này. Mọi quyết định và thao tác vẫn
          do bạn kiểm soát.
        </p>
      </aside>
    </div>
  );
}

export function DemoShell({ children }: { children: ReactNode }) {
  return (
    <DemoStateProvider>
      <AnalyticsDataProvider>
        <DemoShellContent>{children}</DemoShellContent>
      </AnalyticsDataProvider>
    </DemoStateProvider>
  );
}
