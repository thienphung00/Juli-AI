"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeKeywords } from "../../../../../../components/ops/shopee/ops-shopee-keywords";

export default function OpsShopeeKeywordsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeKeywords me={me} shopId={shopId} />}</OpsGate>;
}
