"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../components/ops/ops-shell";
import { OpsShopSettings } from "../../../../components/ops/ops-shop-settings";

export default function OpsShopSettingsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsShopSettings me={me} shopId={shopId} />}</OpsGate>;
}
