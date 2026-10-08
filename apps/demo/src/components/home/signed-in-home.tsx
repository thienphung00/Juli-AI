"use client";

import Link from "next/link";

import { CONNECT_SHOP_HREF } from "../../lib/app-navigation";
import { useShopReport } from "../../lib/shop-report/shop-report-context";
import { AppPageHeader } from "../app-shell/page-header";
import { HomeOverview } from "./home-overview";

/**
 * Trang chủ for a SIGNED-IN seller: the acting shop's latest ADR-108 report,
 * read once by the shell (`ShopReportProvider`) — Home issues no request of
 * its own. Missing shop, no report yet (404) and a failed read each get an
 * honest state; the sample never stands in for the seller's shop.
 */
export function SignedInHome() {
  const { state, reload } = useShopReport();

  if (state.status === "ready") {
    return <HomeOverview envelope={state.envelope} />;
  }

  let body;
  if (state.status === "no-shop") {
    body = (
      <div className="card home-state" role="status">
        <p>Bạn chưa chọn shop đang thao tác. Kết nối TikTok Shop để Juli bắt đầu đọc số liệu.</p>
        <Link className="btn-secondary" href={CONNECT_SHOP_HREF}>
          Kết nối TikTok Shop
        </Link>
      </div>
    );
  } else if (state.status === "empty") {
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
    <section aria-labelledby="home-title" className="home-overview">
      <AppPageHeader eyebrow="Trang chủ" title="Báo cáo của shop" titleId="home-title" />
      {body}
    </section>
  );
}
