"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../../components/ops/ops-shell";
import { OpsShopeeReco } from "../../../../../../components/ops/shopee/ops-shopee-reco";

export default function OpsShopeeRecoPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopeeReco me={me} shopId={shopId} />}</OpsGate>;
}
