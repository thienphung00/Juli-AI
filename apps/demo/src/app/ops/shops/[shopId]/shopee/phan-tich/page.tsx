"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeAnalytics } from "../../../../../../components/ops/shopee/ops-shopee-analytics";

export default function OpsShopeeAnalyticsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeAnalytics me={me} shopId={shopId} />}</OpsGate>;
}
