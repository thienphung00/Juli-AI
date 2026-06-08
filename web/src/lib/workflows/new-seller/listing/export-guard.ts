import type { ProductDraft } from "@/lib/mock-data/listing-workflow/schemas";

export function canExportProductDraft(draft: ProductDraft): boolean {
  return (
    draft.compliance.status !== "blocked" && draft.status === "ready_for_export"
  );
}
