"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { api, type Shop } from "@/lib/api-client";
import { formatVND } from "@/lib/format";
import { NavBar } from "./NavBar";
import { UI_ONLY_DEMO_SHOP, isUiOnly } from "@/lib/ui-only";

export function HomePage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { user } = useAuth();
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
    <div className="min-h-screen pb-20">
      <header className="app-header sticky top-0 z-10 px-4 py-3">
        <div className="mx-auto flex max-w-lg items-center justify-between">
          <div>
            <h1 className="brand-wordmark brand-wordmark-sm">Juli</h1>
            {shop && (
              <p className="text-muted mt-0.5 text-xs">{shop.name}</p>
            )}
          </div>
          <div className="text-muted text-sm">{user?.phone}</div>
        </div>
      </header>

      <main className="mx-auto max-w-lg space-y-4 px-4 pt-4">
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
      </main>

      <NavBar />
    </div>
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
