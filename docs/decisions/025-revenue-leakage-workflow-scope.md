# ADR 025: Revenue Leakage Executable Workflow Scope

## Status
Accepted

## Context

- Phase 1 shipped Revenue Leakage as an **alert feed** (P1-3, issue #120): ranked
  `MockTask` cards, evidence drawer, approve/dismiss via no-op executor.
- Phase 1.6 validated the **executable workflow pattern** for New Seller Copilot
  (`list_products` → modal state machine → mock execute) per
  [ADR-020](020-new-seller-listing-workflow-scope.md).
- Product requires the same E2E pattern for Revenue Leakage before Phase 2 live
  APIs: evidence → root cause → recommended action → guided execution → success.
- [ADR-011](011-buyer-behavior-anomaly-scope.md) limits **ML anomaly** classes to
  `item_swap` and `empty_return`. P1.7 workflows surface **rules aggregates** and
  **policy signals** in mock fixtures; affiliate cancellation patterns are Phase 2
  policy alerts — not P1.7 executable journeys.
- Current `leakage-persona.ts` task `affiliate_fraud` (`task_leak_002`) conflicts
  with Journey 2 (buyer cancellation cluster) and ADR-011 ML scope.

## Decision

- We will: insert **Phase 1.7** (Weeks 10–11) between Phase 1.6 and Phase 2 as the
  first **executable** Revenue Leakage workflow — modal stepper inside
  `LeakageCopilotPanel`, not new App Router routes. Approve opens
  `LeakageWorkflowPanel`; dismiss requires a reason **across all workflows**
  (shared executor extension).
- We will: implement four mock journeys keyed to `MockTask.type`:
  `return_spike`, `buyer_cancellation_cluster`, `refund_cluster`,
  `return_window_policy` (rename from `policy_update`).
- We will: replace `affiliate_fraud` fixture with `buyer_cancellation_cluster` and
  add cancelled-order mock rows for evidence.
- We will: add **P2-9** (leakage approval queue) and **P2-10** (live leakage
  executors: Products API listing update, TikTok support case draft submit, shop
  settings) alongside existing P2-1…P2-8 slices.
- We will: use client-side fixtures in `web/src/lib/mock-data/leakage-workflow/`
  with schemas aligned to [`canonical-entities.md`](../data-models/canonical-entities.md)
  § Leakage workflow entities. No Postgres, no TikTok API, no Ollama in P1.7.
- We will not: add a fifth task type; run ML inference; store buyer PII; scrape
  Seller Center; submit real TikTok support cases in P1.7.

## Why this architecture

- **Speed:** Reuses P1.6 listing patterns (`state-machine.ts`, modal panel, session
  persistence, `useTaskExecutor` extension) — minimal new UX infrastructure.
- **Cost:** No backend or LLM spend; validates operational UX before P2 executor work.
- **Scalability:** `LeakageWorkflowTask` fixture shape mirrors future inference +
  executor API envelope; P2 swaps loaders, not UI step graph.
- **Reliability:** Deterministic mock execution steps; rules-only root-cause copy;
  masked IDs enforced via existing `assertEvidenceHasNoRawPii`.
- **Operability:** P2-9 approval queue gates live listing/settings mutations
  (blast-radius control, symmetric with P2-7 listing queue).

## Options considered

- **Option A: New `/leakage/*` routes per step** — clearer URLs but breaks copilot
  shell pattern and duplicates P1.6 modal approach. **Rejected.**
- **Option B: Modal workflow in copilot shell (chosen)** — consistent with listing
  workflow; keeps seller in one workflow context.
- **Option C: Keep affiliate_fraud as Journey 2** — conflicts with ADR-011 and user
  journey spec (buyer cancellations). **Rejected** — replace fixture task type.
- **Option D: Leakage-only skip reasons** — faster ship but inconsistent dismiss UX.
  **Rejected** — Product chose global skip-with-reason.

## Consequences

- **Positive:** E2E leakage resolution UX validated before P2; fixture contract
  ready for inference swap; four distinct execution mocks exercise future executor
  categories; global dismiss reasons improve P1 UX instrumentation quality.
- **Negative:** Timeline extends ~1 week (15-week horizon); `affiliate_fraud` demo
  copy removed from leakage persona (affiliate policy alerts land in P2-4).
- **Follow-ups:** P1.7-1…P1.7-5 slices; canonical entity § Leakage workflow;
  optional `return_type` on 1–2 `MockReturn` rows for P2 ML preview (P1.7-1 stretch).

## Rollout / Migration plan

1. **P1.7:** Client-side leakage workflow fixtures + state machine; mock execute per
   task type; session-scoped progress in `task-executor/session-store`.
2. **P2:** Inference output → same `LeakageWorkflowTask` envelope; Ollama rewrites
   copy only; P2-9 queue gates P2-10 live triggers.
3. **P2.4:** Affiliate/policy signals surface as separate alert tasks — not merged
   into buyer-cancellation workflow.
