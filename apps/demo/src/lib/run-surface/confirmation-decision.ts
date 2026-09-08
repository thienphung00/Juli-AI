/**
 * The Đề xuất option picker's confirm-decision CONTRACT (issue #1317),
 * deliberately split out of `confirmation-client.ts`'s real HTTP
 * implementation (issue #1764).
 *
 * WHY THIS SPLIT EXISTS. `confirmation-client.ts` is the one module in this
 * tree that performs the real POST to the confirmation-decision route
 * (backend v1 demo runs API) -- it owns the network call site and the
 * literal backend route path. The replay door (ADR-094 decision 1) must resolve a
 * decision locally, from the scenario's own captured continuation, and
 * must NEVER import a module that can reach that route -- so `OptionPicker`
 * and its ancestors (`RunStageCanvas`, `RunStagedView`) depend on this
 * neutral file for the decision SHAPE (the types and the rejection error
 * class), never on `confirmation-client.ts` itself.
 * `src/__tests__/replay-module-graph.test.ts` depends on exactly this: its
 * "run route" entry point (`components/replay-run-detail.tsx`) reaches
 * `OptionPicker`, and the assertion that no reachable module contains a
 * network fetch call site or a literal backend route path only holds
 * because none of `OptionPicker`'s imports lead back to
 * `confirmation-client.ts`.
 *
 * `confirmation-client.ts` re-exports every symbol below unchanged, so
 * every existing import of these names from that module keeps working --
 * this file adds a second, narrower entry point, it does not move anyone's
 * import path out from under them.
 */

export type ConfirmationDecisionKind = "approve" | "decline";

export interface ConfirmationDecisionResult {
  readonly decision: ConfirmationDecisionKind;
  readonly status: string;
  readonly celeryTaskId: string;
}

/** Mirrors `services/agent_runs/confirmations.py`'s `ERROR_*` constants --
 *  transcribed, not re-derived, so a code this client does not recognize
 *  still carries its raw string through rather than being coerced into a
 *  known one. */
export type ConfirmationErrorCode =
  | "run_not_awaiting_confirmation"
  | "confirmation_not_found"
  | "confirmation_already_decided"
  | "confirmation_expired"
  | "invalid_decision"
  | "option_id_required"
  | "unknown_option_id"
  | "params_sha_mismatch"
  | "run_state_not_reconstructable"
  | (string & {});

export class ConfirmationRejectedError extends Error {
  constructor(
    public readonly status: number,
    public readonly errorCode: ConfirmationErrorCode | null,
    message: string,
  ) {
    super(message);
    this.name = "ConfirmationRejectedError";
  }
}

export interface SubmitConfirmationDecisionOptions {
  readonly token?: string;
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

/**
 * The shape both doors' confirm handler must satisfy -- the real,
 * network-calling `submitConfirmationDecision` (signed-in door) and the
 * replay door's local continuation-resolving handler (`replay-confirm.ts`)
 * are each assignable to this type, structurally, with neither importing
 * the other's module.
 */
export type ConfirmDecisionFn = (
  runId: string,
  toolCallId: string,
  decision: ConfirmationDecisionKind,
  optionId: string | null,
  options?: SubmitConfirmationDecisionOptions,
) => Promise<ConfirmationDecisionResult>;
