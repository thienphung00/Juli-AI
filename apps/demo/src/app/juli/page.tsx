"use client";

import "./juli.css";

import { useMemo } from "react";

import { JuliChat } from "../../components/juli/juli-chat";
import { createJuliClient } from "../../lib/juli/client";
import { useShopPlatformResolved } from "../../lib/shopee-analytics/platform";
import { useShopReport } from "../../lib/shop-report/shop-report-context";

/** `/juli`: the seller-facing chat of the analytics agent (U1). Same page on Shopee and TikTok Shop. */
export default function JuliPage() {
  const { state } = useShopReport();
  const platform = useShopPlatformResolved(state);
  const token = "token" in state ? state.token : null;
  const shop = "shop" in state ? state.shop : null;
  const client = useMemo(() => (token && shop ? createJuliClient({ token, shopId: shop.id }) : null), [token, shop]);

  if (state.status === "resolving" || platform === null) return <p className="juli-loading">Đang tải…</p>;
  if (!client || !shop) {
    return (
      <div className="juli-page">
        <p className="juli-none">Đăng nhập và chọn shop để hỏi Juli.</p>
      </div>
    );
  }
  return <JuliChat key={shop.id} client={client} platform={platform} shopKey={shop.id} />;
}
