/**
 * "Duyệt N thẻ" (ADR-109 d.6/d.9) and the five-stage stepper state (d.8) — pure
 * apart from the injected approve call.
 *
 * Batch approve calls the ordinary approve route once per card, strictly one
 * after another (never in parallel): each call creates one real
 * `workflow_run`, and the backend's queue runs them in turn. A failed card
 * does not stop the rest; its own error is reported next to it.
 */

import type { WorkflowRunListItem } from "@juli/contracts";

export interface BatchResult {
  readonly cardId: string;
  readonly runId: string | null;
  readonly error: unknown;
}

export async function approveSequentially(
  cardIds: readonly string[],
  approve: (cardId: string) => Promise<{ runId: string }>,
  onProgress?: (done: number, total: number) => void,
): Promise<BatchResult[]> {
  const results: BatchResult[] = [];
  for (const cardId of cardIds) {
    try {
      const { runId } = await approve(cardId);
      results.push({ cardId, runId, error: null });
    } catch (error) {
      results.push({ cardId, runId: null, error });
    }
    onProgress?.(results.length, cardIds.length);
  }
  return results;
}

export type StageState = "done" | "current" | "todo" | "failed";

/** Five stages (Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường) for one card group. */
export function groupStages(approvedCount: number, total: number): StageState[] {
  if (total > 0 && approvedCount >= total) return ["done", "done", "done", "current", "todo"];
  if (approvedCount > 0) return ["done", "done", "current", "todo", "todo"];
  return ["done", "current", "todo", "todo", "todo"];
}

/** Five stages for one run, from the server's own status / stop_reason. */
export function runStages(run: Pick<WorkflowRunListItem, "status" | "stop_reason">): StageState[] {
  switch (run.status) {
    case "waiting_approval":
      return ["done", "done", "current", "todo", "todo"];
    case "queued":
    case "running":
      return ["done", "done", "done", "current", "todo"];
    default:
      if (run.stop_reason === "final_response") return ["done", "done", "done", "done", "current"];
      if (run.stop_reason === "confirmation_declined" || run.stop_reason === "cancelled_by_seller") {
        return ["done", "done", "done", "todo", "todo"];
      }
      if (run.stop_reason === "confirmation_expired") return ["done", "done", "failed", "todo", "todo"];
      return ["done", "done", "done", "failed", "todo"];
  }
}
