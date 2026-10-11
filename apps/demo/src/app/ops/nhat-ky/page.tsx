"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsAudit } from "../../../components/ops/ops-staff-audit";

export default function OpsAuditPage() {
  return <OpsGate>{(me) => <OpsAudit me={me} />}</OpsGate>;
}
