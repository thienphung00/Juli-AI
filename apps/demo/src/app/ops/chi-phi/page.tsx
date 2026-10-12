"use client";

import { OpsCosts } from "../../../components/ops/ops-costs";
import { OpsGate } from "../../../components/ops/ops-shell";

export default function OpsCostsPage() {
  return <OpsGate>{(me) => <OpsCosts me={me} />}</OpsGate>;
}
