"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsSimulateCurrent } from "../../../components/ops/ops-simulate-current";

export default function OpsSimulateCurrentPage() {
  return <OpsGate>{(me) => <OpsSimulateCurrent me={me} />}</OpsGate>;
}
