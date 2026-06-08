"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { MockTask, PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { trackTaskApproved, trackTaskDismissed } from "@/lib/ux-analytics";
import type { TaskDismissReason } from "./dismiss-reasons";
import { isLeakageWorkflowTaskType } from "./leakage-workflow-task";
import {
  filterActiveTasks,
  setTaskDisposition,
} from "./queue";
import {
  loadTaskExecutorSession,
  saveTaskExecutorSession,
} from "./session-store";
import type { TaskExecutorSession, TaskFeedback } from "./types";

const FEEDBACK_MESSAGES = {
  approved: "Đã ghi nhận — chưa thực thi trên TikTok (Phase 1).",
  listProductsApproved:
    "Đã mở quy trình đăng sản phẩm — hoàn thành các bước trong phiên này.",
  leakageApproved:
    "Đã mở quy trình rò rỉ doanh thu — hoàn thành các bước trong phiên này.",
  dismissed: "Đã bỏ qua nhiệm vụ trong phiên này.",
  workflowCompleted: "Đã hoàn tất quy trình trong phiên này.",
} as const;

export function useTaskExecutor(
  tasks: MockTask[],
  options: { personaId: PersonaId },
) {
  const { personaId } = options;
  const [session, setSession] = useState<TaskExecutorSession>(() =>
    loadTaskExecutorSession(),
  );
  const [feedback, setFeedback] = useState<TaskFeedback | null>(null);
  const [listingWorkflowOpen, setListingWorkflowOpen] = useState(false);
  const [leakageWorkflowTaskId, setLeakageWorkflowTaskId] = useState<string | null>(
    null,
  );
  const [dismissModalTaskId, setDismissModalTaskId] = useState<string | null>(null);

  useEffect(() => {
    saveTaskExecutorSession(session);
  }, [session]);

  const activeTasks = useMemo(
    () => filterActiveTasks(tasks, session),
    [tasks, session],
  );

  const clearFeedback = useCallback(() => setFeedback(null), []);

  const closeListingWorkflow = useCallback(() => {
    setListingWorkflowOpen(false);
  }, []);

  const closeLeakageWorkflow = useCallback(() => {
    setLeakageWorkflowTaskId(null);
  }, []);

  const completeLeakageWorkflow = useCallback(() => {
    if (!leakageWorkflowTaskId) return;

    const updatedAt = new Date().toISOString();
    setSession((prev) =>
      setTaskDisposition(prev, leakageWorkflowTaskId, "approved", updatedAt),
    );
    setLeakageWorkflowTaskId(null);
    setFeedback({
      kind: "approved",
      taskId: leakageWorkflowTaskId,
      message: FEEDBACK_MESSAGES.workflowCompleted,
    });
  }, [leakageWorkflowTaskId]);

  const approveTask = useCallback(
    (taskId: string) => {
      const task = tasks.find((item) => item.id === taskId);
      const updatedAt = new Date().toISOString();
      setSession((prev) => setTaskDisposition(prev, taskId, "approved", updatedAt));

      const isListProducts = task?.type === "list_products";
      const isLeakageWorkflow =
        task?.type !== undefined && isLeakageWorkflowTaskType(task.type);

      if (isListProducts) {
        setListingWorkflowOpen(true);
      } else if (isLeakageWorkflow) {
        setLeakageWorkflowTaskId(taskId);
      }

      setFeedback({
        kind: "approved",
        taskId,
        message: isListProducts
          ? FEEDBACK_MESSAGES.listProductsApproved
          : isLeakageWorkflow
            ? FEEDBACK_MESSAGES.leakageApproved
            : FEEDBACK_MESSAGES.approved,
      });
      if (task) {
        trackTaskApproved({
          workflow: task.workflow,
          task_type: task.type,
          persona_id: personaId,
        });
      }
    },
    [tasks, personaId],
  );

  const requestDismissTask = useCallback((taskId: string) => {
    setDismissModalTaskId(taskId);
  }, []);

  const cancelDismissTask = useCallback(() => {
    setDismissModalTaskId(null);
  }, []);

  const confirmDismissTask = useCallback(
    (reason: TaskDismissReason, note?: string) => {
      if (!dismissModalTaskId) return;

      const taskId = dismissModalTaskId;
      const task = tasks.find((item) => item.id === taskId);
      const updatedAt = new Date().toISOString();

      setSession((prev) =>
        setTaskDisposition(prev, taskId, "dismissed", updatedAt, {
          dismissReason: reason,
          ...(note ? { dismissNote: note } : {}),
        }),
      );
      setDismissModalTaskId(null);
      setFeedback({
        kind: "dismissed",
        taskId,
        message: FEEDBACK_MESSAGES.dismissed,
      });
      if (task) {
        trackTaskDismissed({
          workflow: task.workflow,
          task_type: task.type,
          persona_id: personaId,
          dismiss_reason: reason,
          ...(note ? { dismiss_note: note } : {}),
        });
      }
    },
    [dismissModalTaskId, tasks, personaId],
  );

  return {
    session,
    activeTasks,
    feedback,
    clearFeedback,
    approveTask,
    requestDismissTask,
    cancelDismissTask,
    confirmDismissTask,
    listingWorkflowOpen,
    closeListingWorkflow,
    leakageWorkflowTaskId,
    closeLeakageWorkflow,
    completeLeakageWorkflow,
    dismissModalTaskId,
  };
}
