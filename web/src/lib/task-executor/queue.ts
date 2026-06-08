import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";
import type { TaskDismissReason } from "./dismiss-reasons";
import type { TaskDisposition, TaskExecutorSession } from "./types";

export interface SetTaskDispositionOptions {
  dismissReason?: TaskDismissReason;
  dismissNote?: string;
}

export function getTaskDisposition(
  session: TaskExecutorSession,
  taskId: string,
): TaskDisposition | null {
  return session.records[taskId]?.disposition ?? null;
}

/** Tasks still shown in the active queue (not approved or dismissed). */
export function filterActiveTasks(
  tasks: MockTask[],
  session: TaskExecutorSession,
): MockTask[] {
  return tasks.filter((task) => getTaskDisposition(session, task.id) === null);
}

export function setTaskDisposition(
  session: TaskExecutorSession,
  taskId: string,
  disposition: TaskDisposition,
  updatedAt: string,
  options?: SetTaskDispositionOptions,
): TaskExecutorSession {
  const record = {
    disposition,
    updatedAt,
    ...(options?.dismissReason ? { dismissReason: options.dismissReason } : {}),
    ...(options?.dismissNote ? { dismissNote: options.dismissNote } : {}),
  };

  return {
    version: 1,
    records: {
      ...session.records,
      [taskId]: record,
    },
  };
}
