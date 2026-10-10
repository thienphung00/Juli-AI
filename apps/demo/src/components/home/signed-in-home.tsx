"use client";

import { useCallback } from "react";

import { onboardingReportReady, type OnboardingStatus } from "../../lib/onboarding/api-client";
import { useShopReport } from "../../lib/shop-report/shop-report-context";
import { ShopOnboardingStrip } from "../onboarding/onboarding-strip";
import { NoShopSampleStrip } from "../app-shell/no-shop-sample-strip";
import { AppPageHeader } from "../app-shell/page-header";
import { HomeOverview } from "./home-overview";
import { SampleHome } from "./sample-home";

/**
 * Trang chủ for a SIGNED-IN seller: the acting shop's latest ADR-108 report,
 * read once by the shell (`ShopReportProvider`) — Home issues no request of
 * its own. No shop connected yet → the sample Home under the "Kết nối TikTok
 * Shop ›" strip (P13; nothing is the seller's). No report yet (404) and a
 * failed read each get an honest state; the sample never stands in for a
 * connected shop.
 */
export function SignedInHome() {
  const { state, reload } = useShopReport();
  const reportEmpty = state.status === "empty";
  const onOnboardingStatus = useCallback(
    (status: OnboardingStatus) => {
      if (reportEmpty && onboardingReportReady(status)) reload();
    },
    [reportEmpty, reload],
  );
  // P17: a seller with a shop sees Juli's progress reading it (nothing once done).
  const strip =
    "shop" in state ? (
      <ShopOnboardingStrip onStatus={onOnboardingStatus} shopId={state.shop.id} token={state.token} />
    ) : null;

  if (state.status === "ready") {
    return (
      <>
        {strip}
        <HomeOverview envelope={state.envelope} />
      </>
    );
  }

  if (state.status === "no-shop") {
    // P13: no TikTok Shop yet → the sample Home (no request), under the connect strip.
    return (
      <>
        <NoShopSampleStrip />
        <SampleHome />
      </>
    );
  }

  let body;
  if (state.status === "empty") {
    body = (
      <div className="card home-state" role="status">
        <p className="eyebrow">Chưa có báo cáo</p>
        <p>
          Juli đang thu thập dữ liệu shop của bạn. Báo cáo đầu tiên sẽ xuất hiện sau khi có đủ số
          liệu, và được cập nhật mỗi ngày.
        </p>
      </div>
    );
  } else if (state.status === "error") {
    body = (
      <div className="card home-state" role="alert">
        <p className="eyebrow">Chưa thể tải nội dung</p>
        <p>Không thể tải báo cáo của shop. Vui lòng thử lại.</p>
        <button className="btn-secondary" onClick={reload} type="button">
          Thử lại
        </button>
      </div>
    );
  } else {
    body = (
      <p aria-live="polite" className="text-muted" role="status">
        Đang tải báo cáo của shop…
      </p>
    );
  }

  return (
    <>
    {strip}
    <section aria-labelledby="home-title" className="home-overview">
      <AppPageHeader eyebrow="Trang chủ" title="Báo cáo của shop" titleId="home-title" />
      {body}
    </section>
    </>
  );
}
