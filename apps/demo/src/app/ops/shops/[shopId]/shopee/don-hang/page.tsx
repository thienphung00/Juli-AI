"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeOrders } from "../../../../../../components/ops/shopee/ops-shopee-orders";

export default function OpsShopeeOrdersPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeOrders me={me} shopId={shopId} />}</OpsGate>;
}
