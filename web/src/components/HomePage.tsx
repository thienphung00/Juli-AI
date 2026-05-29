"use client";

import { useEffect, useState } from "react";
import { api, type Shop } from "@/lib/api-client";
import { formatVND } from "@/lib/format";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { UI_ONLY_DEMO_SHOP, isUiOnly } from "@/lib/ui-only";

export function HomePage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const [shop, setShop] = useState<Shop | null>(
    uiOnly
      ? {
          id: UI_ONLY_DEMO_SHOP.id,
          name: UI_ONLY_DEMO_SHOP.name,
          tiktok_shop_id: UI_ONLY_DEMO_SHOP.tiktok_shop_id,
        }
      : null
  );
  const [loading, setLoading] = useState(!uiOnly);

  useEffect(() => {
    if (uiOnly) return;

    let cancelled = false;
    async function loadShop() {
      try {
        const shops = await api.shops.list();
        if (!cancelled && shops.length > 0) {
          const firstShop = shops[0];
          localStorage.setItem("active_shop_id", firstShop.id);
          setShop(firstShop);
        }
      } catch (error) {
        console.error("Failed to load shop data", { error });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadShop();
    return () => {
      cancelled = true;
    };
  }, [uiOnly]);

  return (
    <AuthenticatedShell title="Juli" subtitle={shop?.name}>
      <div className="space-y-4">
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : (
          <>
            <GmvCard />
            <LivestreamFeedCard />
            <AiRecommendationsCard />
            <InventoryRiskCard />
          </>
        )}
      </div>
    </AuthenticatedShell>
  );
}

function GmvCard() {
  return (
    <div className="card p-4" data-testid="gmv-card">
      <h2 className="text-muted text-sm font-medium">GMV hôm nay</h2>
      <p className="mt-1 text-2xl font-bold" style={{ color: "var(--primary)" }}>
        {formatVND(0)}
      </p>
      <p className="text-muted mt-1 text-xs">
        Chưa có dữ liệu đơn hàng
      </p>
    </div>
  );
}

function LivestreamFeedCard() {
  return (
    <div className="card p-4" data-testid="livestream-card">
      <h2 className="text-muted text-sm font-medium">Livestream</h2>
      <p className="text-muted mt-2 text-sm">
        Chưa có phiên livestream nào
      </p>
    </div>
  );
}

function AiRecommendationsCard() {
  return (
    <div className="card p-4" data-testid="recommendations-card">
      <h2 className="text-muted text-sm font-medium">Gợi ý AI</h2>
      <p className="text-muted mt-2 text-sm">
        Chưa có gợi ý — dữ liệu đang được thu thập
      </p>
    </div>
  );
}

function InventoryRiskCard() {
  return (
    <div className="card p-4" data-testid="inventory-risk-card">
      <h2 className="text-muted text-sm font-medium">Cảnh báo tồn kho</h2>
      <p className="text-muted mt-2 text-sm">
        Không có sản phẩm nào có nguy cơ hết hàng
      </p>
    </div>
  );
}
