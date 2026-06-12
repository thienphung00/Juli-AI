"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { MockTask, PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import type { TaskDismissReason } from "@/lib/task-executor/dismiss-reasons";
import { useTaskExecutor } from "@/lib/task-executor/use-task-executor";
import type { TaskFeedback } from "@/lib/task-executor/types";

import {
  getWorkflowExecutionRoute,
  resolveTaskForWorkflow,
} from "./approval-routing";
import {
  getWorkflowDisposition,
  loadOperationsApprovalSession,
  saveOperationsApprovalSession,
  setWorkflowDisposition,
  type OperationsApprovalSession,
} from "./approval-session";
import type { HealthCheckResults } from "./health-check";
import type { WorkflowRecommendation } from "./recommendations";

const NOOP_APPROVAL_MESSAGE =
  "Đã ghi nhận — quy trình này chưa có thực thi trên TikTok (Phase 2).";

export function useOperationsApproval(options: {
  persona: SellerPersona;
  personaId: PersonaId;
  health: HealthCheckResults;
  recommendations: WorkflowRecommendation[];
}) {
  const { persona, personaId, health, recommendations } = options;
  const executorTasks = useMemo(() => persona.tasks, [persona.tasks]);
  const executor = useTaskExecutor(executorTasks, { personaId });

  const [session, setSession] = useState<OperationsApprovalSession>(() =>
    loadOperationsApprovalSession(personaId),
  );
  const [selectedIds, setSelectedIds] = useState<Set<ValidatedWorkflowId>>(() => new Set());
  const [rejectModalWorkflowId, setRejectModalWorkflowId] = useState<ValidatedWorkflowId | null>(
    null,
  );
  const [workflowFeedback, setWorkflowFeedback] = useState<TaskFeedback | null>(null);

  useEffect(() => {
    saveOperationsApprovalSession(session);
  }, [session]);

  useEffect(() => {
    setSession(loadOperationsApprovalSession(personaId));
    setSelectedIds(new Set());
    setRejectModalWorkflowId(null);
    setWorkflowFeedback(null);
  }, [personaId]);

  const pendingRecommendations = useMemo(
    () =>
      recommendations.filter(
        (item) => getWorkflowDisposition(session, item.workflow_id) === "pending",
      ),
    [recommendations, session],
  );

  const toggleSelection = useCallback((workflowId: ValidatedWorkflowId) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(workflowId)) {
        next.delete(workflowId);
      } else {
        next.add(workflowId);
      }
      return next;
    });
  }, []);

  const selectAllPending = useCallback(() => {
    setSelectedIds(new Set(pendingRecommendations.map((item) => item.workflow_id)));
  }, [pendingRecommendations]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const clearWorkflowFeedback = useCallback(() => {
    setWorkflowFeedback(null);
  }, []);

  const routeApprovedWorkflow = useCallback(
    (workflowId: ValidatedWorkflowId): { openedExecutor: boolean; task: MockTask | null } => {
      const route = getWorkflowExecutionRoute(workflowId);

      if (route === "noop") {
        return { openedExecutor: false, task: null };
      }

      const task = resolveTaskForWorkflow(workflowId, persona, health);
      if (!task) {
        return { openedExecutor: false, task: null };
      }

      executor.approveTask(task.id);
      return { openedExecutor: true, task };
    },
    [executor, health, persona],
  );

  const approveWorkflowIds = useCallback(
    (workflowIds: ValidatedWorkflowId[]) => {
      if (workflowIds.length === 0) {
        return;
      }

      let openedExecutor = false;
      let noopCount = 0;
      let lastNoopId: ValidatedWorkflowId | null = null;

      setSession((prev) => {
        let next = prev;
        for (const workflowId of workflowIds) {
          next = setWorkflowDisposition(next, workflowId, "approved");
        }
        return next;
      });

      for (const workflowId of workflowIds) {
        const route = getWorkflowExecutionRoute(workflowId);
        if (route === "noop") {
          noopCount += 1;
          lastNoopId = workflowId;
          continue;
        }

        if (openedExecutor) {
          continue;
        }

        const result = routeApprovedWorkflow(workflowId);
        if (result.openedExecutor) {
          openedExecutor = true;
        }
      }

      setSelectedIds(new Set());

      if (!openedExecutor && noopCount > 0 && lastNoopId) {
        setWorkflowFeedback({
          kind: "approved",
          taskId: lastNoopId,
          message: NOOP_APPROVAL_MESSAGE,
        });
      }
    },
    [routeApprovedWorkflow],
  );

  const approveWorkflow = useCallback(
    (workflowId: ValidatedWorkflowId) => {
      approveWorkflowIds([workflowId]);
    },
    [approveWorkflowIds],
  );

  const approveSelected = useCallback(() => {
    const ordered = pendingRecommendations
      .filter((item) => selectedIds.has(item.workflow_id))
      .map((item) => item.workflow_id);
    approveWorkflowIds(ordered);
  }, [approveWorkflowIds, pendingRecommendations, selectedIds]);

  const approveAllPending = useCallback(() => {
    approveWorkflowIds(pendingRecommendations.map((item) => item.workflow_id));
  }, [approveWorkflowIds, pendingRecommendations]);

  const requestRejectWorkflow = useCallback((workflowId: ValidatedWorkflowId) => {
    setRejectModalWorkflowId(workflowId);
  }, []);

  const cancelRejectWorkflow = useCallback(() => {
    setRejectModalWorkflowId(null);
  }, []);

  const confirmRejectWorkflow = useCallback(
    (reason: TaskDismissReason, note?: string) => {
      if (!rejectModalWorkflowId) {
        return;
      }

      setSession((prev) =>
        setWorkflowDisposition(prev, rejectModalWorkflowId, "rejected", {
          dismissReason: reason,
          ...(note ? { dismissNote: note } : {}),
        }),
      );
      setRejectModalWorkflowId(null);
      setWorkflowFeedback({
        kind: "dismissed",
        taskId: rejectModalWorkflowId,
        message: "Đã từ chối đề xuất trong phiên này.",
      });
    },
    [rejectModalWorkflowId],
  );

  const feedback = executor.feedback ?? workflowFeedback;

  return {
    session,
    pendingRecommendations,
    selectedIds,
    toggleSelection,
    selectAllPending,
    clearSelection,
    approveWorkflow,
    approveSelected,
    approveAllPending,
    requestRejectWorkflow,
    cancelRejectWorkflow,
    confirmRejectWorkflow,
    rejectModalWorkflowId,
    feedback,
    clearFeedback: () => {
      clearWorkflowFeedback();
      executor.clearFeedback();
    },
    executor,
    getDisposition: (workflowId: ValidatedWorkflowId) =>
      getWorkflowDisposition(session, workflowId),
  };
}
