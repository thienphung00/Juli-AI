import { DISTRIBUTORS } from "./fixtures/distributors";
import { OPPORTUNITIES } from "./fixtures/opportunities";
import { PRODUCT_DRAFTS } from "./fixtures/product-drafts";

export { P16_ALLOWED_SOURCES } from "./schemas";
export type {
  CompetitionLevel,
  ComplianceResult,
  ComplianceStatus,
  Distributor,
  DistributorSource,
  DistributorVerificationStatus,
  ListingContent,
  Opportunity,
  OpportunitySource,
  P16AllowedSource,
  ProductDraft,
  ProductDraftSourceType,
  ProductDraftStatus,
  ProductInfo,
  ReadinessResult,
} from "./schemas";
export { validateListingFixtures } from "./validate";
export type { ValidationResult } from "./validate";

export function loadDistributors() {
  return [...DISTRIBUTORS];
}

export function loadOpportunities() {
  return [...OPPORTUNITIES];
}

export function loadProductDrafts() {
  return [...PRODUCT_DRAFTS];
}
