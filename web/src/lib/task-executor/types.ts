import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";

export type TaskDisposition = "approved" | "dismissed";

export interface TaskExecutorRecord {
  disposition: TaskDisposition;
  updatedAt: string;
}

export interface TaskExecutorSession {
  version: 1;
  records: Record<string, TaskExecutorRecord>;
}

export type TaskFeedbackKind = "approved" | "dismissed";

export interface TaskFeedback {
  kind: TaskFeedbackKind;
  taskId: string;
  message: string;
}

export type { MockTask };
