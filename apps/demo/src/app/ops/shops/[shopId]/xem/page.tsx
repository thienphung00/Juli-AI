"use client";

import { useParams } from "next/navigation";

import { OpsGate } from "../../../../../components/ops/ops-shell";
import { OpsViewAs } from "../../../../../components/ops/ops-view-as";

export default function OpsViewAsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  return <OpsGate>{(me) => <OpsViewAs me={me} shopId={shopId} />}</OpsGate>;
}
