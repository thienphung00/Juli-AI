"use client";

import { OpsGate } from "../../../components/ops/ops-shell";
import { OpsTerms } from "../../../components/ops/ops-terms";

export default function OpsTermsPage() {
  return <OpsGate>{(me) => <OpsTerms me={me} />}</OpsGate>;
}
