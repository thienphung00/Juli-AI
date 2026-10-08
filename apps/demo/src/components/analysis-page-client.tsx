"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { useShopReport } from "../lib/shop-report/shop-report-context";
import { AppPageHeader } from "./app-shell/page-header";
import { SamplePhanTich } from "./phan-tich/sample-phan-tich";
import { SignedInPhanTich } from "./phan-tich/signed-in-phan-tich";

/**
 * /analytics — Phân tích (AC-8.6, ADR-109 d.2–5). Reads the report through
 * the shell's `useShopReport()` (one `GET /v1/demo/analysis` per visit, shared
 * with the header and Home); the URL (`tab`, `stream`, `metric`) holds the
 * sub-tab and the selected cell, so Home's matrix links land on it.
 * Anonymous → the bundled sample (no request); signed in → the shop's report,
 * honest empty / error states, never the sample in its place.
 */
export function AnalysisPageClient() {
  const { state, reload } = useShopReport();
  const searchParams = useSearchParams();
  const router = useRouter();
  const query = {
    tab: searchParams?.get("tab"),
    stream: searchParams?.get("stream"),
    metric: searchParams?.get("metric"),
  };
  const onNavigate = useCallback((href: string) => router.replace(href, { scroll: false }), [router]);

  if (state.status === "anonymous" && state.envelope) {
    return <SamplePhanTich envelope={state.envelope} onNavigate={onNavigate} query={query} />;
  }
  if (state.status === "ready") {
    return (
      <SignedInPhanTich
        envelope={state.envelope}
        onNavigate={onNavigate}
        query={query}
        shopId={state.shop.id}
        token={state.token}
      />
    );
  }

  return (
    <section aria-labelledby="analytics-title" className="pt-page">
      <AppPageHeader eyebrow="Phân tích" title="Phân tích luồng truy cập" titleId="analytics-title" />
      {state.status === "no-shop" ? (
        <div className="card analysis-empty" role="status">
          <p>Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.</p>
          <Link className="btn-secondary" href="/auth/connect-shop">
            Kết nối TikTok Shop
          </Link>
        </div>
      ) : state.status === "empty" ? (
        <div className="card analysis-empty" role="status">
          <p className="analysis-eyebrow">Chưa có báo cáo</p>
          <p>
            Juli đang thu thập dữ liệu shop của bạn. Phân tích đầu tiên sẽ xuất hiện sau khi có đủ số liệu, và
            được cập nhật mỗi ngày.
          </p>
        </div>
      ) : state.status === "error" ? (
        <div className="card analysis-empty" role="alert">
          <p className="analysis-eyebrow">Chưa thể tải nội dung</p>
          <p>Không thể tải phân tích cho shop của bạn. Vui lòng thử lại.</p>
          <button className="btn-secondary" onClick={reload} type="button">
            Thử lại
          </button>
        </div>
      ) : (
        <p aria-live="polite" className="text-muted" role="status">
          Đang tải phân tích…
        </p>
      )}
    </section>
  );
}
