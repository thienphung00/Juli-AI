"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeProducts } from "../../../../../../components/ops/shopee/ops-shopee-products";

export default function OpsShopeeProductsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeProducts me={me} shopId={shopId} />}</OpsGate>;
}
