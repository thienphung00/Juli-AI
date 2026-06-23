"use client";

import { useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { SellerHomeShell } from "./seller-home";
import { formatNumber, formatVND } from "@/lib/format";
import type {
  AffiliateHomeDashboard,
  HomeDashboardData,
} from "@/lib/mock-data/home";
import { useDemoPersonaOptional } from "@/lib/demo-persona-context";
import { useWorkspaceMode } from "@/lib/mode-context";
import { getHomeDashboard, getHomeSubtitle } from "@/lib/services/home";
import { resolveSellerWorkflow } from "@/lib/seller-workflows";
import { isUiOnly } from "@/lib/ui-only";

function formatPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits).replace(".", ",")}%`;
}

export function HomePage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { mode } = useWorkspaceMode();
  const personaContext = useDemoPersonaOptional();
  const [dashboard, setDashboard] = useState<HomeDashboardData | null>(null);
  const [loading, setLoading] = useState(mode === "affiliate");

  useEffect(() => {
    if (mode !== "affiliate") {
      setDashboard(null);
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const data = await getHomeDashboard("affiliate");
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

  const sellerSubtitle =
    mode === "seller" && personaContext?.persona
      ? resolveSellerWorkflow(personaContext.persona).label
      : undefined;

  const affiliateSubtitle = dashboard ? getHomeSubtitle(dashboard) : undefined;
  const subtitle = mode === "seller" ? sellerSubtitle : affiliateSubtitle;

  return (
    <AuthenticatedShell title="Juli" subtitle={subtitle}>
      {mode === "seller" ? (
        <SellerHomeShell />
      ) : loading || !dashboard || dashboard.mode !== "affiliate" ? (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      ) : (
        <AffiliateHomeView dashboard={dashboard} />
      )}
    </AuthenticatedShell>
  );
}

function AffiliateHomeView({ dashboard }: { dashboard: AffiliateHomeDashboard }) {
  return (
    <div className="space-y-3" data-testid="home-affiliate">
      <div className="space-y-3" data-testid="home-above-fold">
        <div className="grid grid-cols-2 gap-3">
          <div className="card p-4" data-testid="commission-card">
            <h2 className="text-muted text-sm font-medium">Hoa hồng hôm nay</h2>
            <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
              {formatVND(dashboard.kpis.commission_today_vnd)}
            </p>
            <p
              className="mt-1 flex items-center gap-1 text-xs font-medium"
              style={{ color: "var(--success)" }}
            >
              <TrendingUp size={14} aria-hidden className="shrink-0" />
              +{dashboard.kpis.commission_wow_pct}% WoW
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
