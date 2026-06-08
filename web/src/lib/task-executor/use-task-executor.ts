"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { MockTask, PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { trackTaskApproved, trackTaskDismissed } from "@/lib/ux-analytics";
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
  dismissed: "Đã bỏ qua nhiệm vụ trong phiên này.",
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

  const approveTask = useCallback(
    (taskId: string) => {
      const task = tasks.find((item) => item.id === taskId);
      const updatedAt = new Date().toISOString();
      setSession((prev) => setTaskDisposition(prev, taskId, "approved", updatedAt));

      const isListProducts = task?.type === "list_products";
      if (isListProducts) {
        setListingWorkflowOpen(true);
      }

      setFeedback({
        kind: "approved",
        taskId,
        message: isListProducts
          ? FEEDBACK_MESSAGES.listProductsApproved
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

  const dismissTask = useCallback(
    (taskId: string) => {
      const task = tasks.find((item) => item.id === taskId);
      const updatedAt = new Date().toISOString();
      setSession((prev) => setTaskDisposition(prev, taskId, "dismissed", updatedAt));
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
        });
      }
    },
    [tasks, personaId],
  );

  return {
    session,
    activeTasks,
    feedback,
    clearFeedback,
    approveTask,
    dismissTask,
    listingWorkflowOpen,
    closeListingWorkflow,
  };
}
