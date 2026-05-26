"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { api, type Shop } from "@/lib/api-client";
import { formatVND } from "@/lib/format";
import { NavBar } from "./NavBar";

export function HomePage() {
  const { user } = useAuth();
  const [shop, setShop] = useState<Shop | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
  }, []);

  return (
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto flex max-w-lg items-center justify-between">
          <div>
            <h1 className="text-lg font-bold">Juli</h1>
            {shop && (
              <p className="text-xs text-gray-500">{shop.name}</p>
            )}
          </div>
          <div className="text-sm text-gray-600">
            {user?.phone}
          </div>
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
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="gmv-card">
      <h2 className="text-sm font-medium text-gray-500">GMV hôm nay</h2>
      <p className="mt-1 text-2xl font-bold">{formatVND(0)}</p>
      <p className="mt-1 text-xs text-gray-400">
        Chưa có dữ liệu đơn hàng
      </p>
    </div>
  );
}

function LivestreamFeedCard() {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="livestream-card">
      <h2 className="text-sm font-medium text-gray-500">Livestream</h2>
      <p className="mt-2 text-sm text-gray-400">
        Chưa có phiên livestream nào
      </p>
    </div>
  );
}

function AiRecommendationsCard() {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="recommendations-card">
      <h2 className="text-sm font-medium text-gray-500">Gợi ý AI</h2>
      <p className="mt-2 text-sm text-gray-400">
        Chưa có gợi ý — dữ liệu đang được thu thập
      </p>
    </div>
  );
}

function InventoryRiskCard() {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="inventory-risk-card">
      <h2 className="text-sm font-medium text-gray-500">Cảnh báo tồn kho</h2>
      <p className="mt-2 text-sm text-gray-400">
        Không có sản phẩm nào có nguy cơ hết hàng
      </p>
    </div>
  );
}
