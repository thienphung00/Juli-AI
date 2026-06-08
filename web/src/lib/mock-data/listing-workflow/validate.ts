import { DISTRIBUTORS } from "./fixtures/distributors";
import { OPPORTUNITIES } from "./fixtures/opportunities";
import { PRODUCT_DRAFTS } from "./fixtures/product-drafts";
import type { Distributor, Opportunity, ProductDraft } from "./schemas";
import { P16_ALLOWED_SOURCES } from "./schemas";

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isIsoDateString(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

function validateDistributor(
  distributor: Distributor,
  errors: string[],
  index: number,
): void {
  const prefix = `distributors[${index}]`;

  if (!isNonEmptyString(distributor.distributor_id)) {
    errors.push(`${prefix}.distributor_id is required`);
  }
  if (!isNonEmptyString(distributor.name)) {
    errors.push(`${prefix}.name is required`);
  }
  if (!Array.isArray(distributor.category_coverage) || distributor.category_coverage.length === 0) {
    errors.push(`${prefix}.category_coverage must be a non-empty array`);
  }
  if (!isFiniteNumber(distributor.moq) || distributor.moq < 0) {
    errors.push(`${prefix}.moq must be a non-negative number`);
  }
  if (!isFiniteNumber(distributor.lead_time_days) || distributor.lead_time_days < 0) {
    errors.push(`${prefix}.lead_time_days must be a non-negative number`);
  }
  if (
    !isFiniteNumber(distributor.reliability_score) ||
    distributor.reliability_score < 0 ||
    distributor.reliability_score > 1
  ) {
    errors.push(`${prefix}.reliability_score must be between 0 and 1`);
  }
}

function validateOpportunity(
  opportunity: Opportunity,
  errors: string[],
  index: number,
): void {
  const prefix = `opportunities[${index}]`;

  if (!isNonEmptyString(opportunity.opportunity_id)) {
    errors.push(`${prefix}.opportunity_id is required`);
  }
  if (!isNonEmptyString(opportunity.product_name)) {
    errors.push(`${prefix}.product_name is required`);
  }
  if (!isNonEmptyString(opportunity.category)) {
    errors.push(`${prefix}.category is required`);
  }
  if (
    !isFiniteNumber(opportunity.estimated_demand) ||
    opportunity.estimated_demand < 1 ||
    opportunity.estimated_demand > 10
  ) {
    errors.push(`${prefix}.estimated_demand must be between 1 and 10`);
  }
  if (!isFiniteNumber(opportunity.min_capital_vnd) || opportunity.min_capital_vnd <= 0) {
    errors.push(`${prefix}.min_capital_vnd must be a positive number`);
  }
  if (
    !isFiniteNumber(opportunity.max_capital_vnd) ||
    opportunity.max_capital_vnd < opportunity.min_capital_vnd
  ) {
    errors.push(`${prefix}.max_capital_vnd must be >= min_capital_vnd`);
  }
  if (typeof opportunity.supports_dropship !== "boolean") {
    errors.push(`${prefix}.supports_dropship must be a boolean`);
  }
}

function validateProductDraft(
  draft: ProductDraft,
  errors: string[],
  index: number,
): void {
  const prefix = `product_drafts[${index}]`;

  if (!isNonEmptyString(draft.draft_id)) {
    errors.push(`${prefix}.draft_id is required`);
  }
  if (!isNonEmptyString(draft.seller_id)) {
    errors.push(`${prefix}.seller_id is required`);
  }
  if (!isNonEmptyString(draft.shop_id)) {
    errors.push(`${prefix}.shop_id is required`);
  }
  if (!isNonEmptyString(draft.product_info.product_name)) {
    errors.push(`${prefix}.product_info.product_name is required`);
  }
  if (!isNonEmptyString(draft.listing_content.title)) {
    errors.push(`${prefix}.listing_content.title is required`);
  }
  if (
    !isFiniteNumber(draft.readiness.overall_score) ||
    draft.readiness.overall_score < 0 ||
    draft.readiness.overall_score > 100
  ) {
    errors.push(`${prefix}.readiness.overall_score must be between 0 and 100`);
  }
  if (!isIsoDateString(draft.created_at)) {
    errors.push(`${prefix}.created_at must be a valid ISO date`);
  }
  if (!isIsoDateString(draft.updated_at)) {
    errors.push(`${prefix}.updated_at must be a valid ISO date`);
  }
}

export function validateListingFixtures(): ValidationResult {
  const errors: string[] = [];

  DISTRIBUTORS.forEach((distributor, index) => {
    validateDistributor(distributor, errors, index);
    if (!P16_ALLOWED_SOURCES.includes(distributor.source as (typeof P16_ALLOWED_SOURCES)[number])) {
      errors.push(`distributors[${index}].source must be P1.6-allowed`);
    }
  });

  OPPORTUNITIES.forEach((opportunity, index) => {
    validateOpportunity(opportunity, errors, index);
    if (!P16_ALLOWED_SOURCES.includes(opportunity.source as (typeof P16_ALLOWED_SOURCES)[number])) {
      errors.push(`opportunities[${index}].source must be P1.6-allowed`);
    }
  });

  PRODUCT_DRAFTS.forEach((draft, index) => {
    validateProductDraft(draft, errors, index);
  });

  return { valid: errors.length === 0, errors };
}
