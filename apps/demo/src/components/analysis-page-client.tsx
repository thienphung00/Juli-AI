"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { useShopReport } from "../lib/shop-report/shop-report-context";
import { NoShopSampleStrip } from "./app-shell/no-shop-sample-strip";
import { AppPageHeader } from "./app-shell/page-header";
import { SamplePhanTich } from "./phan-tich/sample-phan-tich";
import { SignedInPhanTich } from "./phan-tich/signed-in-phan-tich";

/**
 * /analytics — Phân tích (ADR-109 Amendment 2, AC-12.x). Signed in, it reads
 * the report through the shell's `useShopReport()` (one `GET /v1/demo/analysis`
 * per visit, shared with the header and Home); the URL (`tab`, `stream`,
 * `metric`, `huong`, `row`) holds the open stream, the selected cell and the
 * expanded row, so Home's matrix and a card's "Xem phân tích ›" land on them.
 * Signed out → the bundled "Bản minh họa" (the Quyết định sample's shop; no
 * request); signed in without a shop → the same sample under the "Kết nối
 * TikTok Shop ›" strip (P13); signed in with a shop → the shop's report,
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
    huong: searchParams?.get("huong"),
    row: searchParams?.get("row"),
  };
  const onNavigate = useCallback((href: string) => router.replace(href, { scroll: false }), [router]);

  if (state.status === "anonymous") {
    return <SamplePhanTich onNavigate={onNavigate} query={query} />;
  }
  if (state.status === "no-shop") {
    // P13: signed in, no TikTok Shop yet → the same sample, under the connect strip.
    return (
      <>
        <NoShopSampleStrip />
        <SamplePhanTich onNavigate={onNavigate} query={query} />
      </>
    );
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
    <section aria-labelledby="analytics-title" className="pa-page">
      <AppPageHeader eyebrow="PHÂN TÍCH" title="Phân tích luồng truy cập" titleId="analytics-title" />
      {state.status === "empty" ? (
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
