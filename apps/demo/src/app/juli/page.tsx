"use client";

import "./juli.css";

import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";

import { JuliChat } from "../../components/juli/juli-chat";
import { createJuliClient } from "../../lib/juli/client";
import { useJuliEnabled } from "../../lib/juli/enabled";
import { useShopPlatformResolved } from "../../lib/shopee-analytics/platform";
import { useShopReport } from "../../lib/shop-report/shop-report-context";

/** `/juli`: the seller-facing chat of the analytics agent (U1). Same page on Shopee and TikTok Shop. */
export default function JuliPage() {
  const { state } = useShopReport();
  const platform = useShopPlatformResolved(state);
  const token = "token" in state ? state.token : null;
  const shop = "shop" in state ? state.shop : null;
  const enabled = useJuliEnabled(state);
  const router = useRouter();
  const notOn = state.status !== "resolving" && platform !== null && enabled === false;
  // The tab is off for this shop (or there is no shop): go to the default page, show nothing meanwhile.
  useEffect(() => {
    if (notOn) router.replace(platform === "shopee" ? "/tong-quan" : "/");
  }, [notOn, platform, router]);
  const client = useMemo(() => (token && shop ? createJuliClient({ token, shopId: shop.id }) : null), [token, shop]);

  if (notOn) return null;
  if (state.status === "resolving" || platform === null || enabled === null) return <p className="juli-loading">Đang tải…</p>;
  if (!client || !shop) {
    return (
      <div className="juli-page">
        <p className="juli-none">Đăng nhập và chọn shop để hỏi Juli.</p>
      </div>
    );
  }
  return <JuliChat key={shop.id} client={client} platform={platform} shopKey={shop.id} />;
}
