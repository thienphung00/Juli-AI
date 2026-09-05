import type { WorkflowRunListItem } from "@juli/contracts";

/**
 * Partitions the polled read model's runs (`GET /v1/demo/runs`,
 * `WorkflowRunListResponse.data`) into the three run-ledger priority
 * sections (PUI-DESIGN.md §4, issue #1318):
 *
 *  1. `waitingOnYou` -- `status === "waiting_approval"`, pinned top.
 *  2. `running` -- `status === "queued" | "running"`.
 *  3. `finished` -- everything else (the four terminal `status` values).
 *
 * Partitioning only, by the server's own `status` field -- never a
 * re-sort. The server already returns newest-first
 * (`ORDER BY created_at DESC`); each section preserves that relative order
 * rather than recomputing one, so "needing the seller sorted to the top"
 * is a SECTION-level fact (waitingOnYou renders first), not a claim about
 * per-run ordering this module invents.
 */
export interface RunLedgerSections {
  waitingOnYou: WorkflowRunListItem[];
  running: WorkflowRunListItem[];
  finished: WorkflowRunListItem[];
}

const WAITING_APPROVAL_STATUS = "waiting_approval";
const RUNNING_STATUSES = new Set(["queued", "running"]);

export function groupRunsIntoLedgerSections(
  runs: readonly WorkflowRunListItem[],
): RunLedgerSections {
  const sections: RunLedgerSections = {
    waitingOnYou: [],
    running: [],
    finished: [],
  };

  for (const run of runs) {
    if (run.status === WAITING_APPROVAL_STATUS) {
      sections.waitingOnYou.push(run);
    } else if (RUNNING_STATUSES.has(run.status)) {
      sections.running.push(run);
    } else {
      sections.finished.push(run);
    }
  }

  return sections;
}
