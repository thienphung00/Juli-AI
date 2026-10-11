"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsSimulatePicker } from "../../../components/ops/ops-simulate-picker";

export default function OpsSimulatePickerPage() {
  return <OpsGate>{(me) => <OpsSimulatePicker me={me} />}</OpsGate>;
}
