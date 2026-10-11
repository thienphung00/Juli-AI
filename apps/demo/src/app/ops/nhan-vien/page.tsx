"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsStaff } from "../../../components/ops/ops-staff-audit";

export default function OpsStaffPage() {
  return <OpsGate>{(me) => <OpsStaff me={me} />}</OpsGate>;
}
