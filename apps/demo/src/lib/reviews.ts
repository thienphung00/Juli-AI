import type { ReviewStageContent } from "@juli/contracts";

import {
  buildCreateActivityReviewInputDefaults,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  getCreateActivityReviewStages,
} from "./workflows/create-activity";
import {
  buildClearExcessReviewInputDefaults,
  CLEAR_EXCESS_WORKFLOW_KEY,
  getClearExcessReviewStages,
} from "./workflows/clear-excess";
import {
  buildCreateHeroProductReviewInputDefaults,
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  getCreateHeroProductReviewStages,
} from "./workflows/create-hero-product";
import {
  buildDeleteActivityReviewInputDefaults,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  getDeleteActivityReviewStages,
} from "./workflows/delete-activity";
import {
  buildOptimizeProductReviewInputDefaults,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  getOptimizeProductReviewStages,
} from "./workflows/optimize-product";
import {
  buildProcessOrderReviewInputDefaults,
  getProcessOrderReviewStages,
  PROCESS_ORDER_WORKFLOW_KEY,
} from "./workflows/process-order";
import {
  buildReplenishInventoryReviewInputDefaults,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  getReplenishInventoryReviewStages,
} from "./workflows/replenish-inventory";
import {
  buildUpdateActivityReviewInputDefaults,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  getUpdateActivityReviewStages,
} from "./workflows/update-activity";
import {
  buildPreventCancellationReviewInputDefaults,
  getPreventCancellationReviewStages,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
} from "./workflows/prevent-cancellation";
import {
  buildPreventRefundReviewInputDefaults,
  getPreventRefundReviewStages,
  PREVENT_REFUND_WORKFLOW_KEY,
} from "./workflows/prevent-refund";
import {
  buildPreventReturnReviewInputDefaults,
  getPreventReturnReviewStages,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
} from "./workflows/prevent-return";

export { CREATE_HERO_PRODUCT_WORKFLOW_KEY };

export {
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
};

export const APPROVABLE_WORKFLOW_KEYS = [
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
  CLEAR_EXCESS_WORKFLOW_KEY,
  PROCESS_ORDER_WORKFLOW_KEY,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
] as const;

export function isReviewExecutableWorkflow(workflowKey: string): boolean {
  return (APPROVABLE_WORKFLOW_KEYS as readonly string[]).includes(workflowKey);
}

export const defaultAnalyticsMetricKey = "gmv-tiktok";

export function buildReviewInputDefaults(): Record<string, string> {
  return buildCreateHeroProductReviewInputDefaults();
}

export function buildReviewInputDefaultsForWorkflow(
  workflowKey: string,
  computedReorderQuantity?: number | null,
): Record<string, string> {
  switch (workflowKey) {
    case CREATE_HERO_PRODUCT_WORKFLOW_KEY:
      return buildReviewInputDefaults();
    case OPTIMIZE_PRODUCT_WORKFLOW_KEY:
      return buildOptimizeProductReviewInputDefaults();
    case REPLENISH_INVENTORY_WORKFLOW_KEY:
      return buildReplenishInventoryReviewInputDefaults(computedReorderQuantity);
    case CLEAR_EXCESS_WORKFLOW_KEY:
      return buildClearExcessReviewInputDefaults();
    case PROCESS_ORDER_WORKFLOW_KEY:
      return buildProcessOrderReviewInputDefaults();
    case CREATE_ACTIVITY_WORKFLOW_KEY:
      return buildCreateActivityReviewInputDefaults();
    case UPDATE_ACTIVITY_WORKFLOW_KEY:
      return buildUpdateActivityReviewInputDefaults();
    case DELETE_ACTIVITY_WORKFLOW_KEY:
      return buildDeleteActivityReviewInputDefaults();
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return buildPreventCancellationReviewInputDefaults();
    case PREVENT_RETURN_WORKFLOW_KEY:
      return buildPreventReturnReviewInputDefaults();
    case PREVENT_REFUND_WORKFLOW_KEY:
      return buildPreventRefundReviewInputDefaults();
    default:
      return {};
  }
}

export function getWorkflowReviewStages(
  workflowKey: string,
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent[] {
  switch (workflowKey) {
    case OPTIMIZE_PRODUCT_WORKFLOW_KEY:
      return getOptimizeProductReviewStages(analyticsMetricKey);
    case REPLENISH_INVENTORY_WORKFLOW_KEY:
      return getReplenishInventoryReviewStages(analyticsMetricKey);
    case CLEAR_EXCESS_WORKFLOW_KEY:
      return getClearExcessReviewStages(analyticsMetricKey);
    case PROCESS_ORDER_WORKFLOW_KEY:
      return getProcessOrderReviewStages(analyticsMetricKey);
    case CREATE_ACTIVITY_WORKFLOW_KEY:
      return getCreateActivityReviewStages(analyticsMetricKey);
    case UPDATE_ACTIVITY_WORKFLOW_KEY:
      return getUpdateActivityReviewStages(analyticsMetricKey);
    case DELETE_ACTIVITY_WORKFLOW_KEY:
      return getDeleteActivityReviewStages(analyticsMetricKey);
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return getPreventCancellationReviewStages(analyticsMetricKey);
    case PREVENT_RETURN_WORKFLOW_KEY:
      return getPreventReturnReviewStages(analyticsMetricKey);
    case PREVENT_REFUND_WORKFLOW_KEY:
      return getPreventRefundReviewStages(analyticsMetricKey);
    case CREATE_HERO_PRODUCT_WORKFLOW_KEY:
      return getCreateHeroProductReviewStages(analyticsMetricKey);
    default:
      return [];
  }
}

export function getReviewStage(
  workflowKey: string,
  stage: ReviewStageContent["stage"],
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent | undefined {
  return getWorkflowReviewStages(workflowKey, analyticsMetricKey).find(
    (entry) => entry.stage === stage,
  );
}
