import {
  deriveLifecycleFromTimeline,
  type ExecutionRecord,
  type ExecutionTimelineStep,
} from "@juli/contracts";

import {
  buildReviewInputDefaultsForWorkflow,
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
} from "./reviews";
import {
  CREATE_ACTIVITY_TOOL_NAME,
  CREATE_ACTIVITY_WORKFLOW_KEY,
  createCreateActivityTimeline,
} from "./workflows/create-activity";
import {
  CREATE_HERO_PRODUCT_TOOL_NAME,
  createHeroProductTimeline,
} from "./workflows/create-hero-product";
import {
  CLEAR_EXCESS_TOOL_NAME,
  CLEAR_EXCESS_WORKFLOW_KEY,
  createClearExcessTimeline,
} from "./workflows/clear-excess";
import {
  DELETE_ACTIVITY_TOOL_NAME,
  DELETE_ACTIVITY_WORKFLOW_KEY,
  createDeleteActivityTimeline,
} from "./workflows/delete-activity";
import {
  createProcessOrderTimeline,
  PROCESS_ORDER_TOOL_NAME,
  PROCESS_ORDER_WORKFLOW_KEY,
} from "./workflows/process-order";
import {
  createReplenishInventoryTimeline,
  REPLENISH_INVENTORY_TOOL_NAME,
  REPLENISH_INVENTORY_WORKFLOW_KEY,
} from "./workflows/replenish-inventory";
import {
  createUpdateActivityTimeline,
  UPDATE_ACTIVITY_TOOL_NAME,
  UPDATE_ACTIVITY_WORKFLOW_KEY,
} from "./workflows/update-activity";
import {
  createPreventCancellationTimeline,
  PREVENT_CANCELLATION_TOOL_NAME,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
} from "./workflows/prevent-cancellation";
import {
  createPreventRefundTimeline,
  PREVENT_REFUND_TOOL_NAME,
  PREVENT_REFUND_WORKFLOW_KEY,
} from "./workflows/prevent-refund";
import {
  createPreventReturnTimeline,
  PREVENT_RETURN_TOOL_NAME,
  PREVENT_RETURN_WORKFLOW_KEY,
} from "./workflows/prevent-return";

export { CREATE_HERO_PRODUCT_WORKFLOW_KEY };
export {
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
} from "./reviews";
export {
  createPreventCancellationTimeline,
  PREVENT_CANCELLATION_TOOL_NAME,
} from "./workflows/prevent-cancellation";
export {
  createPreventRefundTimeline,
  PREVENT_REFUND_TOOL_NAME,
} from "./workflows/prevent-refund";
export {
  createPreventReturnTimeline,
  PREVENT_RETURN_TOOL_NAME,
} from "./workflows/prevent-return";

export { CREATE_HERO_PRODUCT_TOOL_NAME, createHeroProductTimeline };

const executionCounters = new Map<string, number>();

/**
 * Ten workflows, deliberately not eleven (#1320 part 2, ADR-094). Optimize
 * Product is not a key here: its approval reaches the staged run view
 * directly (the replay's captured golden scenario, or a real signed-in run)
 * instead of a localStorage-persisted mock `ExecutionRecord`. Calling
 * `startExecution("optimize_product_2")` throws the same "Unsupported
 * workflow key" every unknown key already throws — see
 * `lib/__tests__/executions.test.ts` and
 * `lib/__tests__/executions-module-graph.test.ts` (the latter walks this
 * module's reachable closure and asserts it never re-acquires the deleted
 * `execution.ts` module's former timeline/execution builders, so the wiring
 * cannot be reintroduced quietly).
 */
const SUPPORTED_WORKFLOWS: Record<
  string,
  {
    toolName: string;
    createTimeline: () => ExecutionTimelineStep[];
  }
> = {
  [CREATE_HERO_PRODUCT_WORKFLOW_KEY]: {
    toolName: CREATE_HERO_PRODUCT_TOOL_NAME,
    createTimeline: createHeroProductTimeline,
  },
  [REPLENISH_INVENTORY_WORKFLOW_KEY]: {
    toolName: REPLENISH_INVENTORY_TOOL_NAME,
    createTimeline: createReplenishInventoryTimeline,
  },
  [CLEAR_EXCESS_WORKFLOW_KEY]: {
    toolName: CLEAR_EXCESS_TOOL_NAME,
    createTimeline: createClearExcessTimeline,
  },
  [PROCESS_ORDER_WORKFLOW_KEY]: {
    toolName: PROCESS_ORDER_TOOL_NAME,
    createTimeline: createProcessOrderTimeline,
  },
  [CREATE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: CREATE_ACTIVITY_TOOL_NAME,
    createTimeline: createCreateActivityTimeline,
  },
  [UPDATE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: UPDATE_ACTIVITY_TOOL_NAME,
    createTimeline: createUpdateActivityTimeline,
  },
  [DELETE_ACTIVITY_WORKFLOW_KEY]: {
    toolName: DELETE_ACTIVITY_TOOL_NAME,
    createTimeline: createDeleteActivityTimeline,
  },
  [PREVENT_CANCELLATION_WORKFLOW_KEY]: {
    toolName: PREVENT_CANCELLATION_TOOL_NAME,
    createTimeline: createPreventCancellationTimeline,
  },
  [PREVENT_RETURN_WORKFLOW_KEY]: {
    toolName: PREVENT_RETURN_TOOL_NAME,
    createTimeline: createPreventReturnTimeline,
  },
  [PREVENT_REFUND_WORKFLOW_KEY]: {
    toolName: PREVENT_REFUND_TOOL_NAME,
    createTimeline: createPreventRefundTimeline,
  },
};

export function resetExecutionCountersForTests(): void {
  executionCounters.clear();
}

function nextExecutionId(workflowKey: string): string {
  const next = (executionCounters.get(workflowKey) ?? 0) + 1;
  executionCounters.set(workflowKey, next);
  return `exec-${workflowKey}-${next}`;
}

function seedInitialTimeline(
  timeline: ExecutionTimelineStep[],
): ExecutionTimelineStep[] {
  return timeline.map((step, index) =>
    index === 0
      ? { ...step, status: "running" }
      : { ...step, status: "pending" },
  );
}

export function startExecution(
  workflowKey: string,
  approvedInputs?: Record<string, string>,
): {
  executionId: string;
  record: ExecutionRecord;
} {
  const config = SUPPORTED_WORKFLOWS[workflowKey];

  if (!config) {
    throw new Error(`Unsupported workflow key: ${workflowKey}`);
  }

  const executionId = nextExecutionId(workflowKey);
  const now = "2026-07-16T04:12:00.000Z";
  const timeline = seedInitialTimeline(config.createTimeline());
  const lifecycleStatus = deriveLifecycleFromTimeline(timeline);

  const record: ExecutionRecord = {
    executionId,
    workflowKey,
    toolName: config.toolName,
    lifecycleStatus,
    startedAt: now,
    updatedAt: now,
    timeline,
    approvedInputs: {
      ...buildReviewInputDefaultsForWorkflow(workflowKey),
      ...(approvedInputs ?? {}),
    },
  };

  return { executionId, record };
}

export function getWorkflowTimeline(
  workflowKey: string,
): ExecutionTimelineStep[] {
  const config = SUPPORTED_WORKFLOWS[workflowKey];

  if (!config) {
    return [];
  }

  return config.createTimeline();
}
