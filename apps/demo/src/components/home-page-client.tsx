"use client";

import { useShopReport } from "../lib/shop-report/shop-report-context";
import { useTiktokSharedRedirect } from "../lib/use-tiktok-shared-redirect";
import { DemoLanding } from "./demo-landing";
import { SignedInHome } from "./home/signed-in-home";

/**
 * `/` — the session split. A signed-in seller lands on their shop's Home;
 * anyone else gets the two-door landing (`DemoLanding`), whose replay door
 * reveals the sample Home. Waits for the shell to resolve the session so
 * the doors never flash for a signed-in seller.
 */
export function HomePageClient() {
  const { state } = useShopReport();
  // W3: a TikTok shop's Tổng quan is the shared /tong-quan; this ADR-108 Home stays behind one switch (decision #8).
  const leaving = useTiktokSharedRedirect(state, "/tong-quan");

  if (state.status === "resolving" || leaving) {
    return <p className="text-muted">Đang tải…</p>;
  }

  if (state.status === "anonymous") {
    return <DemoLanding />;
  }

  return <SignedInHome />;
}
