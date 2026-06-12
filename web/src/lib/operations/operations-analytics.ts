import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { getUxSessionId } from "@/lib/ux-analytics/session";

export interface ReasoningExpansionPayload {
  event: "reasoning_expanded";
  workflow_id: ValidatedWorkflowId;
  persona_id: PersonaId;
  session_id: string;
  timestamp: string;
}

/** Fail-silent — reasoning expansion clicks for P1.8 metrics (issue #180). */
export function trackReasoningExpansion(input: {
  workflow_id: ValidatedWorkflowId;
  persona_id: PersonaId;
}): void {
  if (typeof window === "undefined") return;

  try {
    const detail: ReasoningExpansionPayload = {
      event: "reasoning_expanded",
      workflow_id: input.workflow_id,
      persona_id: input.persona_id,
      session_id: getUxSessionId(),
      timestamp: new Date().toISOString(),
    };

    window.dispatchEvent(new CustomEvent("juli:analytics", { detail }));

    if (process.env.NODE_ENV === "development") {
      console.info("reasoning_expanded", detail);
    }
  } catch {
    // Analytics must never break seller UX.
  }
}
