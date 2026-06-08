import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { getUxSessionId } from "@/lib/ux-analytics/session";
import type { ExportFormat } from "./export";

export interface ExportCompletedPayload {
  event: "export_completed";
  workflow: "new_seller";
  task_type: "list_products";
  persona_id: PersonaId;
  session_id: string;
  draft_id: string;
  format: ExportFormat;
  timestamp: string;
}

/** Fail-silent analytics for listing export completion (issue #156). */
export function trackExportCompleted(input: {
  personaId: PersonaId;
  draftId: string;
  format: ExportFormat;
}): void {
  if (typeof window === "undefined") return;

  try {
    const detail: ExportCompletedPayload = {
      event: "export_completed",
      workflow: "new_seller",
      task_type: "list_products",
      persona_id: input.personaId,
      session_id: getUxSessionId(),
      draft_id: input.draftId,
      format: input.format,
      timestamp: new Date().toISOString(),
    };

    window.dispatchEvent(new CustomEvent("juli:analytics", { detail }));

    if (process.env.NODE_ENV === "development") {
      console.info("export_completed", detail);
    }
  } catch {
    // Analytics must never break seller UX.
  }
}
