"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeFunnel } from "../../../../../../components/ops/shopee/ops-shopee-funnel";

export default function OpsShopeeFunnelPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeFunnel me={me} shopId={shopId} />}</OpsGate>;
}
