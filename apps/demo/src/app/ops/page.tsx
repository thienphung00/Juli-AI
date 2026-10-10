"use client";

import { OpsGate } from "../../components/ops/ops-shell";
import { OpsOverview } from "../../components/ops/ops-overview";

export default function OpsOverviewPage() {
  return <OpsGate>{(me) => <OpsOverview me={me} />}</OpsGate>;
}
