"use client";

import { useEffect, useState } from "react";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { HomeHeroMatches } from "./home/HomeHeroMatches";
import { formatNumber, formatVND } from "@/lib/format";
import type {
  AffiliateHomeDashboard,
  HomeDashboardData,
  SellerHomeDashboard,
} from "@/lib/mock-data/home";
import { useWorkspaceMode } from "@/lib/mode-context";
import { getHomeDashboard, getHomeSubtitle } from "@/lib/services/home";
import { isUiOnly } from "@/lib/ui-only";

function formatPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits).replace(".", ",")}%`;
}

function formatDeltaPct(value: number): string {
  const pct = (value * 100).toFixed(1).replace(".", ",");
  return `▲ +${pct}%`;
}

export function HomePage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { mode } = useWorkspaceMode();
  const [dashboard, setDashboard] = useState<HomeDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!mode) return;

    const workspaceMode = mode;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const data = await getHomeDashboard(workspaceMode);
        if (!cancelled) setDashboard(data);
      } catch (error) {
        console.error("home_dashboard_load_failed", { error });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mode, uiOnly]);

  const subtitle = dashboard ? getHomeSubtitle(dashboard) : undefined;

  return (
    <AuthenticatedShell title="Juli" subtitle={subtitle}>
      {loading || !dashboard || !mode ? (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      ) : dashboard.mode === "seller" ? (
        <SellerHomeView dashboard={dashboard} />
      ) : (
        <AffiliateHomeView dashboard={dashboard} />
      )}
    </AuthenticatedShell>
  );
}

function SellerHomeView({ dashboard }: { dashboard: SellerHomeDashboard }) {
  return (
    <div className="space-y-3" data-testid="home-seller">
      <div className="space-y-3" data-testid="home-above-fold">
        <HomeHeroMatches matches={dashboard.hero_matches} />

        <div className="grid grid-cols-2 gap-3">
          <div className="card p-4" data-testid="gmv-card">
            <h2 className="text-muted text-sm font-medium">GMV hôm nay</h2>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
              {formatVND(dashboard.kpis.gmv_today_vnd)}
            </p>
            <p className="mt-1 text-xs font-medium" style={{ color: "#10b981" }}>
              ▲ +{dashboard.kpis.gmv_wow_pct}% WoW
            </p>
          </div>

          <div className="card p-4" data-testid="livestream-card">
            <h2 className="text-muted text-sm font-medium">Livestream đang chạy</h2>
            <p className="mt-1 text-sm font-semibold">
              {dashboard.kpis.active_livestreams} phiên ·{" "}
              {formatNumber(dashboard.kpis.active_livestream_viewers)} xem
            </p>
            <a
              href="/livestreams"
              className="mt-2 inline-block text-xs font-semibold"
              style={{ color: "var(--primary)" }}
            >
              Xem chi tiết →
            </a>
          </div>
        </div>

      </div>

      <div className="card p-4" data-testid="top-creator-card">
        <h2 className="text-muted text-sm font-medium">Creator tốt nhất hôm nay</h2>
        <p className="mt-1 text-sm font-semibold">{dashboard.top_creator.handle}</p>
        <p className="text-muted mt-1 text-sm">
          {formatVND(dashboard.top_creator.gmv_today_vnd)} GMV · Tỷ lệ chuyển đổi:{" "}
          {formatPct(dashboard.top_creator.conversion_rate)}{" "}
          {formatDeltaPct(dashboard.top_creator.conversion_delta)}
        </p>
      </div>

      <div className="card p-4" data-testid="top-product-card">
        <h2 className="text-muted text-sm font-medium">Sản phẩm bán chạy</h2>
        <p className="mt-1 text-sm font-semibold">{dashboard.top_product.name}</p>
        <p className="text-muted mt-1 text-sm">
          {formatNumber(dashboard.top_product.orders_today)} đơn · GMV{" "}
          {formatVND(dashboard.top_product.gmv_today_vnd)} · CTR{" "}
          {formatPct(dashboard.top_product.ctr)}
        </p>
      </div>
    </div>
  );
}

function AffiliateHomeView({ dashboard }: { dashboard: AffiliateHomeDashboard }) {
  return (
    <div className="space-y-3" data-testid="home-affiliate">
      <div className="space-y-3" data-testid="home-above-fold">
        <HomeHeroMatches matches={dashboard.hero_matches} />

        <div className="grid grid-cols-2 gap-3">
          <div className="card p-4" data-testid="commission-card">
            <h2 className="text-muted text-sm font-medium">Hoa hồng hôm nay</h2>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
              {formatVND(dashboard.kpis.commission_today_vnd)}
            </p>
            <p className="mt-1 text-xs font-medium" style={{ color: "#10b981" }}>
              ▲ +{dashboard.kpis.commission_wow_pct}% WoW
            </p>
          </div>

          <div className="card p-4" data-testid="livestream-card">
            <h2 className="text-muted text-sm font-medium">Livestream hôm nay</h2>
            <p className="mt-1 text-sm font-semibold">
              {dashboard.kpis.livestream_sessions_today} phiên ·{" "}
              {formatVND(dashboard.kpis.livestream_gmv_vnd)}
            </p>
            <p className="text-muted mt-1 text-xs">
              Tỷ lệ chuyển đổi {formatPct(dashboard.kpis.livestream_conversion_rate)}
            </p>
          </div>
        </div>
      </div>

      <div className="card p-4" data-testid="audience-fit-card">
        <h2 className="text-muted text-sm font-medium">Sản phẩm phù hợp với audience</h2>
        <ul className="mt-2 space-y-2">
          {dashboard.audience_fit_products.map((product) => (
            <li key={product.id} className="text-sm">
              <span className="font-medium">{product.name}</span>
              <span className="text-muted">
                {" "}
                · Phù hợp {Math.round(product.fit_score * 100)}% · Hoa hồng{" "}
                {product.commission_pct}%
              </span>
            </li>
          ))}
        </ul>
        <a
          href="/trends"
          className="mt-3 inline-block text-xs font-semibold"
          style={{ color: "var(--primary)" }}
        >
          Xem thêm →
        </a>
      </div>

      <div className="card p-4" data-testid="content-performance-card">
        <h2 className="text-muted text-sm font-medium">Hiệu suất nội dung</h2>
        <p className="text-muted mt-2 text-sm">
          Video hôm qua: {formatNumber(dashboard.content_performance.video_yesterday_views)}{" "}
          lượt xem
        </p>
        <p className="text-muted text-sm">
          Tỷ lệ click sản phẩm:{" "}
          {formatPct(dashboard.content_performance.product_click_rate)}
        </p>
      </div>
    </div>
  );
}

