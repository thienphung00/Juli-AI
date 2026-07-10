import { collectForbiddenPiiKeys, isMaskedBuyerId } from "./pii";
import type {
  MockAdCampaign,
  MockAffiliateEvent,
  MockOrder,
  MockReturn,
  MockTask,
  PersonaId,
  SellerPersona,
  SellerProfile,
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

function validateSellerProfile(profile: SellerProfile, errors: string[]): void {
  const personaIds: PersonaId[] = ["new", "leakage", "growth"];

  if (!personaIds.includes(profile.id)) {
    errors.push(`profile.id must be one of ${personaIds.join(", ")}`);
  }
  if (!isNonEmptyString(profile.shop_id)) errors.push("profile.shop_id is required");
  if (!isNonEmptyString(profile.shop_name)) errors.push("profile.shop_name is required");
  if (!isFiniteNumber(profile.shop_age_days) || profile.shop_age_days < 0) {
    errors.push("profile.shop_age_days must be a non-negative number");
  }
  if (!isFiniteNumber(profile.order_count_30d) || profile.order_count_30d < 0) {
    errors.push("profile.order_count_30d must be a non-negative number");
  }
  if (!isFiniteNumber(profile.return_rate_30d) || profile.return_rate_30d < 0) {
    errors.push("profile.return_rate_30d must be a non-negative number");
  }
  if (!isFiniteNumber(profile.ad_spend_30d_vnd) || profile.ad_spend_30d_vnd < 0) {
    errors.push("profile.ad_spend_30d_vnd must be a non-negative number");
  }
  if (!isFiniteNumber(profile.gmv_30d_vnd) || profile.gmv_30d_vnd < 0) {
    errors.push("profile.gmv_30d_vnd must be a non-negative number");
  }
}

function validateTask(task: MockTask, errors: string[], index: number): void {
  const prefix = `tasks[${index}]`;

  if (!isNonEmptyString(task.id)) errors.push(`${prefix}.id is required`);
  if (!isNonEmptyString(task.workflow)) errors.push(`${prefix}.workflow is required`);
  if (!isNonEmptyString(task.type)) errors.push(`${prefix}.type is required`);
  if (!["high", "medium", "low", "info"].includes(task.severity)) {
    errors.push(`${prefix}.severity is invalid`);
  }
  if (!isNonEmptyString(task.title)) errors.push(`${prefix}.title is required`);
  if (!isNonEmptyString(task.body)) errors.push(`${prefix}.body is required`);
  if (!isNonEmptyString(task.cta_label)) errors.push(`${prefix}.cta_label is required`);
  if (task.estimated_impact_vnd !== null && !isFiniteNumber(task.estimated_impact_vnd)) {
    errors.push(`${prefix}.estimated_impact_vnd must be null or a number`);
  }
  if (!Array.isArray(task.evidence_refs)) {
    errors.push(`${prefix}.evidence_refs must be an array`);
  }
  if (task.copy_source !== "mock") {
    errors.push(`${prefix}.copy_source must be "mock"`);
  }
}

function validateOrder(order: MockOrder, errors: string[], index: number): void {
  const prefix = `orders[${index}]`;

  if (!isNonEmptyString(order.id)) errors.push(`${prefix}.id is required`);
  if (!isNonEmptyString(order.shop_id)) errors.push(`${prefix}.shop_id is required`);
  if (!isNonEmptyString(order.buyer_id) || !isMaskedBuyerId(order.buyer_id)) {
    errors.push(`${prefix}.buyer_id must be a masked buyer id`);
  }
  if (!isNonEmptyString(order.product_title)) errors.push(`${prefix}.product_title is required`);
  if (!isFiniteNumber(order.quantity) || order.quantity < 1) {
    errors.push(`${prefix}.quantity must be >= 1`);
  }
  if (!isFiniteNumber(order.total_vnd) || order.total_vnd <= 0) {
    errors.push(`${prefix}.total_vnd must be > 0`);
  }
  if (!isIsoDateString(order.created_at)) errors.push(`${prefix}.created_at must be ISO date`);
}

function validateReturn(ret: MockReturn, errors: string[], index: number): void {
  const prefix = `returns[${index}]`;

  if (!isNonEmptyString(ret.id)) errors.push(`${prefix}.id is required`);
  if (!isNonEmptyString(ret.order_id)) errors.push(`${prefix}.order_id is required`);
  if (!isNonEmptyString(ret.buyer_id) || !isMaskedBuyerId(ret.buyer_id)) {
    errors.push(`${prefix}.buyer_id must be a masked buyer id`);
  }
  if (!isNonEmptyString(ret.product_title)) errors.push(`${prefix}.product_title is required`);
  if (!isNonEmptyString(ret.reason)) errors.push(`${prefix}.reason is required`);
  if (!isFiniteNumber(ret.refund_vnd) || ret.refund_vnd <= 0) {
    errors.push(`${prefix}.refund_vnd must be > 0`);
  }
  if (!isIsoDateString(ret.created_at)) errors.push(`${prefix}.created_at must be ISO date`);
}

function validateAffiliateEvent(
  event: MockAffiliateEvent,
  errors: string[],
  index: number,
): void {
  const prefix = `affiliate_events[${index}]`;

  if (!isNonEmptyString(event.id)) errors.push(`${prefix}.id is required`);
  if (!isNonEmptyString(event.affiliate_id)) errors.push(`${prefix}.affiliate_id is required`);
  if (!isNonEmptyString(event.order_id)) errors.push(`${prefix}.order_id is required`);
  if (!isNonEmptyString(event.event_type)) errors.push(`${prefix}.event_type is required`);
  if (!isFiniteNumber(event.gmv_vnd) || event.gmv_vnd < 0) {
    errors.push(`${prefix}.gmv_vnd must be >= 0`);
  }
  if (!isIsoDateString(event.created_at)) errors.push(`${prefix}.created_at must be ISO date`);
}

function validateAdCampaign(campaign: MockAdCampaign, errors: string[], index: number): void {
  const prefix = `ad_campaigns[${index}]`;

  if (!isNonEmptyString(campaign.id)) errors.push(`${prefix}.id is required`);
  if (!isNonEmptyString(campaign.campaign_name)) {
    errors.push(`${prefix}.campaign_name is required`);
  }
  if (!isFiniteNumber(campaign.spend_vnd) || campaign.spend_vnd < 0) {
    errors.push(`${prefix}.spend_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.roas) || campaign.roas < 0) {
    errors.push(`${prefix}.roas must be >= 0`);
  }
  if (!isFiniteNumber(campaign.cpc_vnd) || campaign.cpc_vnd < 0) {
    errors.push(`${prefix}.cpc_vnd must be >= 0`);
  }
  if (!isFiniteNumber(campaign.conversions) || campaign.conversions < 0) {
    errors.push(`${prefix}.conversions must be >= 0`);
  }
  if (!isFiniteNumber(campaign.period_days) || campaign.period_days < 1) {
    errors.push(`${prefix}.period_days must be >= 1`);
  }
}

export function validatePersona(persona: SellerPersona): ValidationResult {
  const errors: string[] = [];

  validateSellerProfile(persona.profile, errors);
  persona.tasks.forEach((task, index) => validateTask(task, errors, index));
  persona.orders.forEach((order, index) => validateOrder(order, errors, index));
  persona.returns.forEach((ret, index) => validateReturn(ret, errors, index));
  persona.affiliate_events.forEach((event, index) =>
    validateAffiliateEvent(event, errors, index),
  );
  persona.ad_campaigns.forEach((campaign, index) =>
    validateAdCampaign(campaign, errors, index),
  );

  const piiViolations = collectForbiddenPiiKeys(persona);
  piiViolations.forEach((path) => errors.push(`forbidden PII key at ${path}`));

  return { valid: errors.length === 0, errors };
}
