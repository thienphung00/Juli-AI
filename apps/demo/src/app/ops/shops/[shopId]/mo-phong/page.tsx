"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../components/ops/ops-shell";
import { OpsSimulate } from "../../../../../components/ops/ops-simulate";

export default function OpsSimulatePage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsSimulate me={me} shopId={shopId} />}</OpsGate>;
}
