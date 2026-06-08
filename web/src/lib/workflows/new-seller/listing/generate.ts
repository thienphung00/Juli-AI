import type { ProductDraft } from "@/lib/mock-data/listing-workflow/schemas";
import { READINESS_EXPORT_THRESHOLD } from "./constants";
import { evaluateCompliance } from "./compliance";
import {
  buildListingContent,
  buildProductInfo,
  extractProductFields,
} from "./extraction";
import {
  deterministicDraftId,
  deterministicTimestamp,
} from "./hash";
import { evaluateReadiness } from "./readiness";
import type { ListingGenerationContext } from "./types";

function normalizeContextKey(context: ListingGenerationContext): string {
  return JSON.stringify(context, Object.keys(context).sort());
}

function resolveDraftStatus(
  complianceStatus: ProductDraft["compliance"]["status"],
  readinessScore: number,
): ProductDraft["status"] {
  if (complianceStatus === "blocked") {
    return "blocked";
  }
  if (readinessScore >= READINESS_EXPORT_THRESHOLD) {
    return "ready_for_export";
  }
  return "in_progress";
}

export function generateProductDraft(
  context: ListingGenerationContext,
): ProductDraft {
  const fields = extractProductFields(context);
  const product_info = buildProductInfo(fields);
  const listing_content = buildListingContent(fields);
  const compliance = evaluateCompliance(fields);
  const readiness = evaluateReadiness(fields, listing_content, compliance);

  const contextKey = normalizeContextKey(context);
  const timestamp = deterministicTimestamp(contextKey);

  return {
    draft_id: deterministicDraftId(contextKey),
    seller_id: context.seller_id,
    shop_id: context.shop_id,
    status: resolveDraftStatus(compliance.status, readiness.overall_score),
    source_type: context.source_type,
    product_info,
    listing_content,
    compliance,
    readiness,
    created_at: timestamp,
    updated_at: timestamp,
  };
}
