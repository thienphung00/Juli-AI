"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsTrialSignups } from "../../../components/ops/ops-trial-signups";

export default function OpsTrialSignupsPage() {
  return <OpsGate>{(me) => <OpsTrialSignups me={me} />}</OpsGate>;
}
