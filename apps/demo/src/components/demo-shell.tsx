"use client";

import { PrimaryNavigation } from "@juli/ui";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { demoDestinations } from "../lib/mock-data";
import { sanitizeSellerReviewText } from "../lib/review-seller-copy";
import { AnalyticsDataProvider, useAnalyticsData } from "../lib/analytics/analytics-data-context";
import { DemoStateProvider, useDemoState } from "./demo-state";

const assistanceByPath = {
  "/": {
    destination: "Trang chủ",
    message:
      "Bạn có thể bắt đầu với Quyết định để xem việc cần làm, hoặc mở Phân tích để hiểu điều đang diễn ra trong shop.",
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
    requestSignIn,
    resetMockState,
  } = useDemoState();
  const { refreshAnalytics } = useAnalyticsData();

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
              Mock
            </button>
            <button
              className="demo-mode-switcher__option"
              type="button"
              aria-disabled="true"
              aria-pressed="false"
              onClick={requestSignIn}
            >
              Sign-in
            </button>
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
