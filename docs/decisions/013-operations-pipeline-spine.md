# ADR 013: Operations pipeline spine

## Status
Accepted

**Supersedes:** Closed "six validated workflows" catalog and Copilot-surface grouping.  
**Workflow taxonomy:** [`execution_layer.md`](../execution_layer.md).

## Context

Juli AI is an AI Operations System: collect operational data, evaluate shop health,
classify shop profile, recommend ranked workflows, explain via copy layer, gate on user
approval, route to execution, and track outcomes — with strict traceability.

## Decision

### Pipeline stages

```
Data Collection (unified_operational_data_model)
  → Health Check (health_check_results)
  → Shop Profile Classification (shop_profile)
  → Workflow Recommendation & Ranking (workflow_recommendations)
  → LLM Reasoning (reasoning_summary — Haiku + rules fallback in Phase 2 MVP)
  → User Approval (approved_workflows)
  → Execution (workflow_results)
  → Outcome Tracking (workflow_outcome_metrics)
```

### Shop profiles

- `NEW_SHOP` — probation / graduation focus; listing + shop-metric rules.
- `MID_LARGE_SHOP` — growth + loss-prevention rules.

T8 router selects rule set per profile ([ADR-011](011-display-grade-analytics-layer.md)).

### Architecture constraints

1. Data traceability: every collected datum → ≥1 workflow.
2. Metric traceability: every health indicator → ≥1 workflow decision.
3. Recommendation traceability: every recommendation → ≥1 workflow in execution-layer taxonomy.
4. Explainability: Why + Expected Impact on every recommendation.
5. Copy layer never invents workflows or claims capabilities beyond the taxonomy.

### Account health

SPS and VP/AHR may not be exposed via Partner API. Phase 2 MVP degrades explicitly per
`health_data_source: api | proxy | unavailable`.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Phase 2 MVP swaps mock loaders for live data/inference without changing stage envelopes.
- Scoped inventory signals (level, velocity, lead time) power Stockout Prevention only —
  signals, not inventory management software.
