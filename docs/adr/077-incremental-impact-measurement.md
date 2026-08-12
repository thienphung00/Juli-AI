# ADR-077: Incremental impact measurement — control-adjusted pre/post (simplified DiD) with confidence tiers

**Status:** Proposed
**Date:** 2026-08-12
**Deciders:** grill-with-docs (Architect) with user, grounded in a three-track research
sweep (marketplace/seller-tool practice; causal-inference methods and OSS; production
analytics heuristics)

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (outcome closure),
[ADR-069](069-agent-tool-registry-and-write-path.md) (`ToolExecution`,
`WorkflowOutcomeRecord`), [ADR-072](072-agent-prompt-architecture.md) (prompt
versioning — the future A/B seam), [ADR-075](075-agent-approval-gate-and-security-prerequisites.md)
(option-selection data). **Fills:** the placeholder readings in
`build_workflow_outcome_metrics` (#306/ADR-013 envelope) and the undefined
"Incremental impact" link of the outcome chain (user fixes 3+7, 2026-08-11).
**Method adoption (user directive):** adopt existing formulas simplified, never invent
statistics. Primary lineage: canonical 2×2 difference-in-differences in ratio form ≈
the degenerate form of Google CausalImpact (Brodersen et al. 2015,
arXiv:1506.00356) / Abadie synthetic control, per the industry fallback pattern when
no traffic split is possible (Amazon MYE-less sellers, Eppo quasi-experiments,
retail-media "actual minus expected baseline").
**Scope:** Phase P-IM of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md);
Optimize Product first.

## Context

`expected_impact.value` is a pre-run severity score, not a forecast; post-run
measurement was an envelope of `"pending"` readings on a workflow vocabulary that
excluded the 11 agent workflows. TikTok Shop/Shopee/Lazada offer no impact math;
true A/B is impossible on a single listing. Six decisions were grilled; the user
additionally requires SEO and description changes to be separately quantifiable and
the design to be reusable by a future LLM-output A/B experiment.

## Decision

1. **Funnel-first target-metric mapping** (measure where the mutation causally acts;
   all columns exist in `analytics_performance_intervals`, daily grain, per product):

   | Mutation | Primary | Secondary |
   |---|---|---|
   | SEO keywords / title | `impressions` (total-traffic proxy for visibility — honest limitation: search traffic not separable) | `ctr` |
   | Description | `conversion_rate` | `items_sold` |
   | Image | `ctr` | `conversion_rate` |
   | Price | `gmv` | `sku_orders`, gmv÷orders |

   A multi-mutation run reports **per-mutation readings** plus one **run-level
   rollup** on the ActionCard's `expected_impact.metric`. Rejected: revenue-only
   (content changes drown in zero-inflated daily SKU revenue); funnel-only (price
   acts on revenue directly).

2. **The formula — ratio-form DiD.** T = the write's execution date (from
   `ToolExecution`); `pre = mean(metric, T−14…T−1)`; `post` over `T+1…T+7`
   (preliminary) and `T+1…T+14` (final); `growth = mean(controls, post) ÷
   mean(controls, pre)`; `expected = pre × growth`; `incremental = post − expected`;
   `impact_% = incremental ÷ expected`. Rules: day T excluded everywhere; a second
   Juli run on the product inside either window marks the reading `confounded`
   (suppressed); rate metrics use arithmetic means of daily values in v1
   (pooled-rate upgrade documented — raw click counts unavailable); `pre = 0` or
   `expected ≤ 0` suppresses the % form. Impact is honestly lagging: preliminary at
   T+7 exists so the seller isn't staring at "pending" for two weeks.

3. **Control pool — K-nearest-correlated siblings.** Candidates: other products in
   the shop with complete pre-window daily rows; disqualified if touched by any Juli
   run in either window, below the volume floor, or active <14 days. Top **K=5**
   (min 3) by Pearson correlation of the target metric's pre-period series,
   **equal-weighted** into one control series (correlation beats category as the
   criterion — it measures shared shock exposure, which is what DiD needs; Abadie-
   optimized weights rejected for v1: few-donor optimizers overfit pre-period
   noise). Quality bar: mean correlation ≥ 0.2, else — or with <3 candidates — fall
   back to **plain pre/post** capped at Thấp confidence. The chosen control set
   (IDs, correlations, windows) is stored on every reading for audit and placebo
   verification.

4. **Confidence tiers and suppression.** Per-metric pre-period volume floors
   (config): ≥1 order/day for revenue/orders readings, ≥50 impressions/day for
   impressions/CTR, ≥20 visitors/day for conversion; below floor → the reading is
   the designed state "Chưa đủ dữ liệu để ước tính". Tiers (Google Merchant Center
   pattern): **Cao** = full control path ∧ volume ≥ 3× floor ∧ |incremental| > 2×
   noise band; **Trung bình** = full path ∧ ≥ floor ∧ > 1× band; **Thấp** =
   fallback path or signal within band — where the **noise band** is the stddev of
   the daily treated-vs-expected gap during the pre-period (how wrong the
   counterfactual already was when nothing had happened). Declared plainly a
   heuristic z-analogue; real credible intervals are the `tfcausalimpact`
   graduation path. Copy rules: every number hedged **"ước tính"**, never causal
   language; inline method disclaimer ("so với các sản phẩm tương tự trong shop");
   negative impact rendered as honestly as positive.

5. **Compute path, storage, surfacing.** A daily **impact-reader beat task**
   scheduled after the analytics backfill top-up scans terminal runs whose T+7/T+14
   has elapsed with unwritten readings and computes them. Source of truth:
   **`impact_readings`** table — `run_id, tool_execution_id, metric, kind
   (preliminary|final), pre, post, expected, incremental, impact_pct, confidence
   (cao|trung_binh|thap|suppressed|confounded), control_set_json, computed_at`,
   unique on `(tool_execution_id, metric, kind)` (idempotent reader) — because the
   four-metric business-impact aggregation and the eval pipeline need cross-run
   queries, not JSON parsing. The legacy envelope stays display-compatible: filled
   from the table (preliminary → `weekly` slot, final → `monthly`; `realtime` keeps
   its execution-status meaning), and `WORKFLOW_OUTCOME_SUCCESS_CRITERIA` gains
   `optimize_product_2` per decision 1 (closing the vocabulary gap). UI: Hoàn tất
   stage and finished-run ledger card show "Đang theo dõi kết quả — ước tính sau 7
   ngày" until the preliminary lands, then the reading + tier, upgraded in place at
   final; no SSE involved.

6. **Tests and phase gate.** Synthetic-uplift recovery (known injected uplift
   recovered; zero-uplift twin recovers ≈0); **shock cancellation** — the design's
   thesis as a test: a shop-wide ×1.5 post-window shock reads ≈0 control-adjusted
   while naive pre/post reads +50%; placebo battery (untouched products, fabricated
   T → readings ≈0, Cao never awarded in fixtures); the suppression/fallback matrix
   (below-floor, <3 controls, <0.2 correlation, confounded, pre=0) all reachable
   and asserted; reader idempotency + elapse-boundary logic; envelope-shape
   compatibility through the existing outcome route; real-shaped golden fixtures
   captured from the reference shop. **Gate:** all green + one real end-to-end
   reading for a sandbox run (backdated T) + the criteria entry present + a reading
   visible in the demo UI (finished-run golden scenario) + the business-impact row
   computable from `impact_readings` by query.

## Future A/B experiment reuse (user requirement, recorded seam)

Comparing LLM-output variants (content quality → impact) reuses this design nearly
whole: **treatment label** = ADR-072's `prompt_sha256`/version already stamped on
every run (arms = sibling prompt files); **dependent variable** = `impact_readings`
grouped by prompt version — and because each reading is control-adjusted
incremental impact, arms compare uplift-vs-own-counterfactual, cleaner than raw
outcomes; **early quality signal** = `run_confirmations` option selections per
variant (available before impact windows elapse); **content attribution** = the
per-mutation rows keep SEO vs description effects separate. Genuinely new work when
that day comes: a random assignment mechanism at the `compose(workflow_key,
version)` seam (stratified by product volume) and proper two-sample inference +
power analysis — the tier heuristic explicitly does not scale to inter-arm
comparison.

## Consequences

- `expected_impact.value` (severity score) and incremental impact (measured delta)
  are now different numbers with different names and schemas — fix 7's separation
  is structural.
- Readings arrive 7/14 days after a run; the demo's finished-run golden scenario
  includes a pre-computed reading so the surface is demonstrable without waiting.
- The method is honest about its ceiling: heuristic confidence, total-impressions
  proxy for SEO visibility, arithmetic-mean rates — each with a named upgrade path
  (tfcausalimpact intervals, traffic-source split if TikTok exposes it, pooled
  rates with raw counts).
