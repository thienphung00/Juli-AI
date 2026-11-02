"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeAds } from "../../../../../../components/ops/shopee/ops-shopee-ads";

export default function OpsShopeeAdsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeAds me={me} shopId={shopId} />}</OpsGate>;
}
