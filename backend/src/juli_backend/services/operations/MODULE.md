# Module: operations

## Responsibility

Phase 2 operations pipeline backend services. P2-B5 owns workflow outcome
instrumentation after approved tool execution. W8-C (#1655) adds the read-only
post-hoc chain over that instrumentation.

## Public Interface

- `record_workflow_outcome(session, execution, …) -> WorkflowOutcomeRecordResult` —
  persist `workflow_outcome_metrics` envelope after terminal execution (idempotent)
- `load_workflow_outcome_metrics(session, shop_id, approval_id) -> dict` — internal
  validation read model
- `build_workflow_outcome_metrics(…)` — ADR-013 envelope builder
- `list_impact_readings_honest(session, tool_execution_id) -> list[ImpactReading]` —
  ADR-085 d.8 (#1338): the countable readings only
- `COUNTABLE_CONFIDENCES` / `EXCLUDED_CONFIDENCES` — the single declaration of
  the #1226/#1338 exclusion rule; every surface answering "what was the impact"
  reads these instead of re-declaring the tier list
- `load_outcome_chain(session, workflow_run_id, *, now=None) -> OutcomeChain` —
  the five-link post-hoc chain (#1655), in ONE database call
- `LinkReason` (`pending` | `unavailable` | `missing`), `EmptyLink`, `OutcomeChain`
  and the five link payload types

## API

- `GET /v1/workflow-outcomes/{approval_id}` —
  `backend/src/juli_backend/api/routes/workflow_outcomes.py`
- No route exposes `load_outcome_chain`: it is an operator/query surface, and
  rendering is deliberately out of W8 (PRD #1652).

## API

- `GET /v1/workflow-outcomes/{approval_id}` —
  `backend/src/juli_backend/api/routes/workflow_outcomes.py`

## Dependencies

- `models.models.ToolExecution` — terminal execution records (no execution module import)
- `repositories.repos.WorkflowOutcomeRecordsRepo`
- `services.impact.windows.post_window` — the ONLY declaration of ADR-077 d.2's
  window lengths; `outcome_chain` never re-declares T+7
- `services.agent.status` — `NON_TERMINAL_STATUSES` / `WorkflowRunStatus`, the
  vocabulary `outcome_chain` classifies against (it adds no member to it)

## Invariants

- Execution payload must include a validated six-workflow `workflow_id`
- One outcome record per `(shop_id, execution_id)`
- Realtime cadence reflects execution status; other cadences remain preliminary stubs
- A `suppressed` or `confounded` `ImpactReading` is never counted as an impact
  and never collapsed into the other or into zero — one rule
  (`COUNTABLE_CONFIDENCES`/`EXCLUDED_CONFIDENCES`), never a second copy
- `load_outcome_chain` issues exactly ONE statement; reason classification is
  pure Python over that single result set plus an injectable clock
- An empty link always carries a `LinkReason`, never a bare `null`, and the
  vocabulary has exactly three members
- `workflow_runs.action_card_id IS NULL` reads `unavailable` (honest legacy
  data), never `missing`, and is never backfilled

## Out of scope (this module)

- Live OLAP-derived cadence rollups (P2-B8+)
- Dashboard loader swap
- Workflow-specific executors (P2-B6+)
- Rendering or serving the outcome chain (no route, no response model — W8 defers it)

## Owners

- domain: backend
- code: backend/src/juli_backend/services/operations/

---

## Quality metrics (#1656)

W8-D / P10-4 adds `quality_metrics.py`: three of P10's four questions, each
read-only, each from its OWN source and over its OWN denominator. Kept in a
delimited section because W8-D and W8-E (#1657, business impact) land in
parallel.

### Public interface

- `recommendation_quality(session, shop_id, *, since=None, until=None) -> RecommendationQuality`
  — "was Juli right", over **recommendations with an observed outcome**
- `approval_rate(session, shop_id, *, since=None, until=None) -> ApprovalRate`
  — "did sellers agree", over **cards surfaced**
- `execution_quality(session, shop_id, *, since=None, until=None) -> ExecutionQuality`
  — "did Juli do the job", over **runs started**
- `NoData` — the explicit empty-denominator value returned by every result's
  `ratio`; a type of its own, so it never compares equal to `0`/`0.0`
- `StopReasonCount` — one entry of execution quality's `stop_reason`
  distribution; a `None` stop reason stays `None`
- `APPROVED_STATUSES` / `DISMISSED_STATUSES` / `PENDING_STATUSES` /
  `EXPIRY_STOP_REASON` — the seller-decision mapping, declared once
- `RECOMMENDATIONS_WITH_AN_OBSERVED_OUTCOME` / `CARDS_SURFACED` /
  `RUNS_STARTED` — the three denominators, named

### The seller-decision mapping (stated, not invented)

`action_cards.status` has exactly four values in the tree — `active`,
`approved`, `dismissed`, `executing` (`services/action_cards/persist.py::
IN_FLIGHT_STATUSES` plus the `active` candidate status it upserts):

| Bucket | Read from |
|---|---|
| `approved` (the numerator) | `status in {approved, executing}` |
| `dismissed` (explicit negative) | `status == dismissed` |
| `expired` | run-level `StopReason.CONFIRMATION_EXPIRED` on a run created from the card |
| `pending` | `status == active`, the residual |

**Known vocabulary gap.** There is no `rejected` and no `expired`
`action_cards.status`, and card-level expiry does not exist at all: the only
expiry signal in the tree is `StopReason.CONFIRMATION_EXPIRED` at RUN level.
So approval rate reads exactly ONE fact from `workflow_runs` — whether a run
created from this card carries that stop reason — and nothing else about the
run. Adding a card status is a five-place change owned by another lane, not a
metric's business.

### Invariants

- **No blended figure.** No function, field or return value combines two of
  the three; no two share a denominator. Enforced structurally over `__all__`
  by `tests/unit/test_agent_quality_metrics.py::TestNoBlendedFigure`, not by
  review alone.
- Every result carries its **numerator and denominator**; `ratio` is a
  convenience over them, never a replacement.
- An **empty denominator returns `NoData`**, never `0` or `0%`. Counts are
  summed in Python from row groups so a Postgres NULL-over-zero-rows can never
  be coerced into a `0`.
- **Expiry is never collapsed into a dismissal** — a seller who ran out of
  time did not disagree — and takes precedence over the card's own status,
  which still reads `approved` from the approval that created the run.
- `required_steps_completed` is read as **its own fact** (#1220), never
  derived from or folded into `stop_reason`; `NULL` is "not yet determined",
  counted as neither success nor failure and named as `undetermined`.
- Recommendation quality consumes **`load_outcome_chain`** — one call per
  candidate run, never a second client-side join across the four tables — and
  reuses the chain's own `excluded_readings` so `suppressed`/`confounded`
  readings are never observed outcomes (#1226, #1338), with no second copy of
  the rule.

### Out of scope

- Business impact — that is #1657 (W8-E), and blending it in is the exact
  hiding PRD #1652 refuses
- Trends, thresholds, alerting, SLOs, judgement, rendering, any HTTP route
