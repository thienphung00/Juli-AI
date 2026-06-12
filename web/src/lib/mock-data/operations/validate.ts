import type {
  AdCampaignPerformance,
  InventoryRecord,
  ProbationData,
  ProductPerformance,
  ReturnsRefundsData,
  ShopMetadata,
  UnifiedOperationalDataModel,
  ValidatedWorkflowId,
} from "./schemas";
import {
  VALIDATED_WORKFLOW_IDS,
  type HealthDataSource,
  type ShopProfileType,
} from "./schemas";

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

function validateShopMetadata(metadata: ShopMetadata, errors: string[]): void {
  if (!isNonEmptyString(metadata.shop_id)) errors.push("shop_metadata.shop_id is required");
  if (!isNonEmptyString(metadata.shop_name)) errors.push("shop_metadata.shop_name is required");
  if (!["NEW_SHOP", "MID_LARGE_SHOP"].includes(metadata.profile)) {
    errors.push("shop_metadata.profile must be NEW_SHOP or MID_LARGE_SHOP");
  }
  if (!["active", "graduated", "not_applicable"].includes(metadata.probation_status)) {
    errors.push("shop_metadata.probation_status is invalid");
  }
  if (metadata.graduation_date !== null && !isIsoDateString(metadata.graduation_date)) {
    errors.push("shop_metadata.graduation_date must be null or ISO date");
  }
  if (!isFiniteNumber(metadata.shop_age_days) || metadata.shop_age_days < 0) {
    errors.push("shop_metadata.shop_age_days must be >= 0");
  }
}

function validateProbation(probation: ProbationData, errors: string[]): void {
  if (!isIsoDateString(probation.probation_start_date)) {
    errors.push("probation.probation_start_date must be ISO date");
  }
  if (!isIsoDateString(probation.probation_end_date)) {
    errors.push("probation.probation_end_date must be ISO date");
  }
  if (!isFiniteNumber(probation.sps_current) || probation.sps_current < 0) {
    errors.push("probation.sps_current must be >= 0");
  }
  if (!isFiniteNumber(probation.sps_threshold) || probation.sps_threshold <= 0) {
    errors.push("probation.sps_threshold must be > 0");
  }
  if (!isFiniteNumber(probation.ahr_current) || probation.ahr_current < 0) {
    errors.push("probation.ahr_current must be >= 0");
  }
  if (!isFiniteNumber(probation.ahr_threshold) || probation.ahr_threshold <= 0) {
    errors.push("probation.ahr_threshold must be > 0");
  }
  probation.violations.forEach((violation, index) => {
    const prefix = `probation.violations[${index}]`;
    if (!isNonEmptyString(violation.violation_id)) {
      errors.push(`${prefix}.violation_id is required`);
    }
    if (!isNonEmptyString(violation.category)) errors.push(`${prefix}.category is required`);
    if (!isFiniteNumber(violation.count) || violation.count < 0) {
      errors.push(`${prefix}.count must be >= 0`);
    }
    if (!["high", "medium", "low"].includes(violation.severity)) {
      errors.push(`${prefix}.severity is invalid`);
    }
  });
}

function validateAdCampaign(campaign: AdCampaignPerformance, errors: string[], index: number): void {
  const prefix = `ad_campaigns[${index}]`;
  if (!isNonEmptyString(campaign.campaign_id)) errors.push(`${prefix}.campaign_id is required`);
  if (!isNonEmptyString(campaign.campaign_name)) {
    errors.push(`${prefix}.campaign_name is required`);
  }
  if (!["active", "paused", "ended"].includes(campaign.status)) {
    errors.push(`${prefix}.status is invalid`);
  }
  if (!isFiniteNumber(campaign.spend_vnd) || campaign.spend_vnd < 0) {
    errors.push(`${prefix}.spend_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.impressions) || campaign.impressions < 0) {
    errors.push(`${prefix}.impressions must be >= 0`);
  }
  if (!isFiniteNumber(campaign.clicks) || campaign.clicks < 0) {
    errors.push(`${prefix}.clicks must be >= 0`);
  }
  if (!isFiniteNumber(campaign.ctr) || campaign.ctr < 0) {
    errors.push(`${prefix}.ctr must be >= 0`);
  }
  if (!isFiniteNumber(campaign.conversions) || campaign.conversions < 0) {
    errors.push(`${prefix}.conversions must be >= 0`);
  }
  if (!isFiniteNumber(campaign.revenue_vnd) || campaign.revenue_vnd < 0) {
    errors.push(`${prefix}.revenue_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.roas) || campaign.roas < 0) {
    errors.push(`${prefix}.roas must be >= 0`);
  }
  if (!isFiniteNumber(campaign.cpc_vnd) || campaign.cpc_vnd < 0) {
    errors.push(`${prefix}.cpc_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.cpm_vnd) || campaign.cpm_vnd < 0) {
    errors.push(`${prefix}.cpm_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.period_days) || campaign.period_days < 1) {
    errors.push(`${prefix}.period_days must be >= 1`);
  }
}

function validateProduct(product: ProductPerformance, errors: string[], index: number): void {
  const prefix = `products[${index}]`;
  if (!isNonEmptyString(product.product_id)) errors.push(`${prefix}.product_id is required`);
  if (!isNonEmptyString(product.sku_id)) errors.push(`${prefix}.sku_id is required`);
  if (!isNonEmptyString(product.product_name)) errors.push(`${prefix}.product_name is required`);
  if (!isNonEmptyString(product.category)) errors.push(`${prefix}.category is required`);

  for (const field of [
    "units_sold_24h",
    "units_sold_7d",
    "units_sold_30d",
    "revenue_vnd_24h",
    "revenue_vnd_7d",
    "revenue_vnd_30d",
    "price_vnd",
    "margin_pct",
    "sell_through_rate",
  ] as const) {
    if (!isFiniteNumber(product[field]) || product[field] < 0) {
      errors.push(`${prefix}.${field} must be >= 0`);
    }
  }
}

function validateInventory(record: InventoryRecord, errors: string[], index: number): void {
  const prefix = `inventory[${index}]`;
  if (!isNonEmptyString(record.product_id)) errors.push(`${prefix}.product_id is required`);
  if (!isNonEmptyString(record.sku_id)) errors.push(`${prefix}.sku_id is required`);
  if (!isFiniteNumber(record.inventory_level) || record.inventory_level < 0) {
    errors.push(`${prefix}.inventory_level must be >= 0`);
  }
  if (
    !isFiniteNumber(record.sales_velocity_units_per_day) ||
    record.sales_velocity_units_per_day < 0
  ) {
    errors.push(`${prefix}.sales_velocity_units_per_day must be >= 0`);
  }
  if (!isFiniteNumber(record.reorder_lead_time_days) || record.reorder_lead_time_days < 0) {
    errors.push(`${prefix}.reorder_lead_time_days must be >= 0`);
  }
}

function validateReturns(returns: ReturnsRefundsData, errors: string[]): void {
  for (const field of [
    "refund_count_7d",
    "refund_count_30d",
    "refund_rate_7d",
    "refund_rate_30d",
    "baseline_refund_rate_30d",
  ] as const) {
    if (!isFiniteNumber(returns[field]) || returns[field] < 0) {
      errors.push(`returns.${field} must be >= 0`);
    }
  }

  returns.top_refund_reasons.forEach((reason, index) => {
    const prefix = `returns.top_refund_reasons[${index}]`;
    if (!isNonEmptyString(reason.reason)) errors.push(`${prefix}.reason is required`);
    if (!isFiniteNumber(reason.count_30d) || reason.count_30d < 0) {
      errors.push(`${prefix}.count_30d must be >= 0`);
    }
    if (!isFiniteNumber(reason.share_pct) || reason.share_pct < 0) {
      errors.push(`${prefix}.share_pct must be >= 0`);
    }
  });

  returns.pending_return_authorizations.forEach((item, index) => {
    const prefix = `returns.pending_return_authorizations[${index}]`;
    if (!isNonEmptyString(item.return_id)) errors.push(`${prefix}.return_id is required`);
    if (!isNonEmptyString(item.order_id)) errors.push(`${prefix}.order_id is required`);
    if (!isNonEmptyString(item.product_name)) errors.push(`${prefix}.product_name is required`);
    if (!["pending", "approved", "rejected"].includes(item.status)) {
      errors.push(`${prefix}.status is invalid`);
    }
    if (!isFiniteNumber(item.refund_vnd) || item.refund_vnd <= 0) {
      errors.push(`${prefix}.refund_vnd must be > 0`);
    }
  });
}

function validateProfileConsistency(model: UnifiedOperationalDataModel, errors: string[]): void {
  const { profile } = model.shop_metadata;

  if (profile === "NEW_SHOP") {
    if (model.probation === null) {
      errors.push("NEW_SHOP fixture must include probation data");
    }
    if (model.shop_metadata.probation_status === "graduated") {
      errors.push("NEW_SHOP fixture must not have graduated probation_status");
    }
  }

  if (profile === "MID_LARGE_SHOP") {
    if (model.probation !== null) {
      errors.push("MID_LARGE_SHOP fixture must set probation to null");
    }
    if (model.ad_campaigns.length < 2) {
      errors.push("MID_LARGE_SHOP fixture must include at least 2 ad campaigns");
    }
  }
}

export function validateUnifiedOperationalModel(
  model: UnifiedOperationalDataModel,
): ValidationResult {
  const errors: string[] = [];

  validateShopMetadata(model.shop_metadata, errors);

  if (model.probation !== null) {
    validateProbation(model.probation, errors);
  }

  model.ad_campaigns.forEach((campaign, index) => validateAdCampaign(campaign, errors, index));
  model.products.forEach((product, index) => validateProduct(product, errors, index));
  model.inventory.forEach((record, index) => validateInventory(record, errors, index));
  validateReturns(model.returns, errors);

  const healthSources: HealthDataSource[] = ["mock", "seller_center_proxy", "unavailable"];
  if (!healthSources.includes(model.health_data_source)) {
    errors.push("health_data_source is invalid");
  }
  if (!isIsoDateString(model.collected_at)) {
    errors.push("collected_at must be ISO date");
  }

  if (model.products.length === 0) {
    errors.push("products must include at least one record");
  }
  if (model.inventory.length === 0) {
    errors.push("inventory must include at least one record");
  }

  validateProfileConsistency(model, errors);

  return { valid: errors.length === 0, errors };
}

export function validateOperationalFixtures(
  models: UnifiedOperationalDataModel[],
): ValidationResult {
  const errors: string[] = [];

  for (const model of models) {
    const result = validateUnifiedOperationalModel(model);
    errors.push(...result.errors);
  }

  const profiles = new Set(models.map((model) => model.shop_metadata.profile));
  const requiredProfiles: ShopProfileType[] = ["NEW_SHOP", "MID_LARGE_SHOP"];
  for (const profile of requiredProfiles) {
    if (!profiles.has(profile)) {
      errors.push(`missing fixture for shop profile ${profile}`);
    }
  }

  return { valid: errors.length === 0, errors };
}

export function isValidatedWorkflowId(value: string): value is ValidatedWorkflowId {
  return (VALIDATED_WORKFLOW_IDS as readonly string[]).includes(value);
}
