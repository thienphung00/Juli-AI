"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";
import { trackTaskExecutorAction } from "@/lib/analytics";
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
  dismissed: "Đã bỏ qua nhiệm vụ trong phiên này.",
} as const;

export function useTaskExecutor(tasks: MockTask[]) {
  const [session, setSession] = useState<TaskExecutorSession>(() =>
    loadTaskExecutorSession(),
  );
  const [feedback, setFeedback] = useState<TaskFeedback | null>(null);

  useEffect(() => {
    saveTaskExecutorSession(session);
  }, [session]);

  const activeTasks = useMemo(
    () => filterActiveTasks(tasks, session),
    [tasks, session],
  );

  const clearFeedback = useCallback(() => setFeedback(null), []);

  const approveTask = useCallback((taskId: string) => {
    const updatedAt = new Date().toISOString();
    setSession((prev) => setTaskDisposition(prev, taskId, "approved", updatedAt));
    setFeedback({
      kind: "approved",
      taskId,
      message: FEEDBACK_MESSAGES.approved,
    });
    trackTaskExecutorAction({ taskId, action: "approve" });
  }, []);

  const dismissTask = useCallback((taskId: string) => {
    const updatedAt = new Date().toISOString();
    setSession((prev) => setTaskDisposition(prev, taskId, "dismissed", updatedAt));
    setFeedback({
      kind: "dismissed",
      taskId,
      message: FEEDBACK_MESSAGES.dismissed,
    });
    trackTaskExecutorAction({ taskId, action: "dismiss" });
  }, []);

  return {
    session,
    activeTasks,
    feedback,
    clearFeedback,
    approveTask,
    dismissTask,
  };
}
