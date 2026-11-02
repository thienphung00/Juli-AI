"use client";

import { useParams } from "next/navigation";

import { OpsCycle } from "../../../../../components/ops/cycle/ops-cycle";
import { OpsGate } from "../../../../../components/ops/ops-shell";

export default function OpsCyclePage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsCycle me={me} shopId={shopId} />}</OpsGate>;
}
