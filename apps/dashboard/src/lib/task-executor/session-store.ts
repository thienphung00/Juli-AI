import type { TaskExecutorSession } from "./types";

export const TASK_EXECUTOR_SESSION_KEY = "juli_task_executor_session";

export function createEmptySession(): TaskExecutorSession {
  return { version: 1, records: {} };
}

export function loadTaskExecutorSession(): TaskExecutorSession {
  if (typeof window === "undefined") {
    return createEmptySession();
  }

  try {
    const raw = sessionStorage.getItem(TASK_EXECUTOR_SESSION_KEY);
    if (!raw) return createEmptySession();
    const parsed = JSON.parse(raw) as TaskExecutorSession;
    if (parsed?.version !== 1 || typeof parsed.records !== "object") {
      return createEmptySession();
    }
    return parsed;
  } catch {
    return createEmptySession();
  }
}

export function saveTaskExecutorSession(session: TaskExecutorSession): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TASK_EXECUTOR_SESSION_KEY, JSON.stringify(session));
}

export function clearTaskExecutorSession(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(TASK_EXECUTOR_SESSION_KEY);
}
