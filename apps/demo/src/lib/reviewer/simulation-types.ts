/**
 * The simulated Duyệt → Thực thi response (contract p32-reviewer-access.md §4).
 * Types only, no call site: the network client (`api-client.ts`) and the
 * no-network sample simulation (`sample-simulation.ts`, P32-D) both produce it.
 */

export type SimulationStep = "approve" | "execute";

export interface SimulatedField {
  readonly field: string;
  readonly label: string;
  readonly before: string | null;
  readonly after: string | null;
}

export interface SimulatedRequest {
  readonly method: string;
  readonly path: string;
  readonly operation: string;
  readonly fields: readonly string[];
}

export interface SimulationResult {
  readonly simulated: true;
  readonly step: SimulationStep;
  readonly action_card_id: string;
  readonly label: string;
  readonly steps: readonly { readonly key: string; readonly label: string; readonly done: boolean }[];
  readonly change: {
    readonly executor: string;
    readonly lever: { readonly code: string; readonly label: string };
    readonly product: { readonly title: string | null; readonly tiktok_product_id: string | null };
    readonly request: SimulatedRequest | null;
    readonly fields: readonly SimulatedField[];
    readonly note: string | null;
  };
  readonly enqueued: false;
  readonly tiktok_write: false;
}
