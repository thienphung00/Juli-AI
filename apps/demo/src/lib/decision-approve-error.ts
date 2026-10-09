/**
 * The approve route's failure, by status (#1909). Split out of
 * `recommendations-api-client.ts` so `quyet-dinh/approve-errors.ts` — which
 * the signed-out sample Quyết định also renders through — never imports a
 * module holding a fetch call site (ADR-094 d.1, `replay-module-graph.test.ts`).
 */
export class DemoDecisionApproveError extends Error {
  constructor(public readonly status: number) {
    super(`Demo decision approve failed (${status})`);
    this.name = "DemoDecisionApproveError";
  }
}
