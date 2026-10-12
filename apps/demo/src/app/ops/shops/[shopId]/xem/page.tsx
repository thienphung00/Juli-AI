"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { OpsGate } from "../../../../../components/ops/ops-shell";
import { OpsViewAs } from "../../../../../components/ops/ops-view-as";

export default function OpsViewAsPage() {
  const { shopId } = useParams<{ shopId: string }>();
  // OpsViewAs reads `?trang=…` (useSearchParams): a Suspense boundary keeps the page buildable.
  return (
    <Suspense>
      <OpsGate>{(me) => <OpsViewAs me={me} shopId={shopId} />}</OpsGate>
    </Suspense>
  );
}
