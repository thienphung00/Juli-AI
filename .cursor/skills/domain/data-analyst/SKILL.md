---
name: data-analyst
description: >-
  SQL-based analysis against Juli-AI's Supabase/PostgreSQL schema: seller
  performance queries, cohort and funnel analysis, ad-performance insights,
  statistical hypothesis testing, and insight delivery. Use when writing
  analytical SQL, profiling seller cohorts, or delivering data-driven
  recommendations — not when training models (mle-agent) or designing KPI
  frameworks (business-intelligence).
metadata:
  version: 1.0.0
  category: data-analytics
  updated: 2026-06-19
  tags: [analytics, sql, cohort, funnel, statistics, insights, juli-ai]
---

# Purpose

Use when performing **exploratory or recurring SQL analysis** against Juli-AI's
Supabase/PostgreSQL data — seller performance cohorts, order/return funnels,
ad campaign analysis, or statistical comparisons — and when translating findings
into seller-facing or product recommendations.

| Skill | Role |
|-------|------|
| **data-analyst** (this) | SQL queries, cohort/funnel/retention, stats, insight delivery |
| [`business-intelligence`](../business-intelligence/SKILL.md) | KPI framework design, Home tab display-grade metrics |
| [`analytics-engineer`](../analytics-engineer/SKILL.md) | Schema design, Alembic migrations, Supabase RLS, view/transform modeling |
| [`data-scientist`](../data-scientist.md) | Algorithm selection, T1–T8 vetting, data sufficiency review |

# Authority chain (read before querying)

1. [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) — available sources per phase; forbidden inputs
2. [`docs/data-models/feature-store-schema.md`](../../../../docs/data-models/feature-store-schema.md) — canonical column names for seller/order/ad entities
3. [`docs/data-models/canonical-entities.md`](../../../../docs/data-models/canonical-entities.md) — Return/Order field alignment across phases
4. [`docs/decisions/011-display-grade-analytics-layer.md`](../../../../docs/decisions/011-display-grade-analytics-layer.md) — display vs decision split; analytics results are advisory
5. [`EXECUTION.md`](../../../../EXECUTION.md) — current phase and what data exists
6. [`.cursor/skills/domain/postgres-patterns.md`](../postgres-patterns.md) — query conventions, ORM, parameterization

# Analysis workflow

1. **Frame the business question** — Restate as a testable metric with a clear grain
   (e.g., "7-day order retention rate by seller lifecycle stage"). Confirm the source
   table/view exists for the active phase per `data-sources.md`.
2. **Profile the dataset** — Row counts, null rates on key join columns, date range coverage,
   and label distribution (e.g., `seller_stage`, `return_reason`). Never proceed with
   analysis on empty or suspiciously thin data — flag phase gate.
3. **Write and validate SQL** — Use CTEs. Filter early; aggregate late. Reference column
   names from `feature-store-schema.md` — do not guess or alias differently.
   Follow query conventions in `postgres-patterns.md`.
4. **Analyze** — Apply the appropriate method from the section below.
5. **Deliver the insight** — What / So What / Now What format. Quantify impact with
   tiers and deltas; never expose raw seller financial PII (`core-safety.mdc`).

# SQL patterns for Juli-AI schema

## Seller cohort retention

```sql
-- Seller cohort: % of sellers placing ≥1 order in week N after onboarding
WITH first_orders AS (
    SELECT seller_id,
           date_trunc('week', MIN(created_at)) AS cohort_week
    FROM orders
    GROUP BY seller_id
),
cohort_data AS (
    SELECT f.cohort_week,
           date_trunc('week', o.created_at)         AS order_week,
           COUNT(DISTINCT o.seller_id)               AS active_sellers
    FROM orders o
    JOIN first_orders f ON o.seller_id = f.seller_id
    GROUP BY 1, 2
),
cohort_size AS (
    SELECT cohort_week, COUNT(DISTINCT seller_id) AS total_sellers
    FROM first_orders
    GROUP BY cohort_week
)
SELECT cd.cohort_week,
       EXTRACT(WEEK FROM AGE(cd.order_week, cd.cohort_week)) AS weeks_since,
       cd.active_sellers,
       cs.total_sellers,
       ROUND(cd.active_sellers::numeric / cs.total_sellers * 100, 1) AS retention_pct
FROM cohort_data cd
JOIN cohort_size cs USING (cohort_week)
ORDER BY 1, 2;
```

## Ad performance funnel (display-grade — no raw ROAS values)

```sql
-- Ad campaign funnel: impression → click → order conversion rates by action tier
-- Use tiers (scale/cut/hold), not raw spend/ROAS values in result sets
WITH campaign_metrics AS (
    SELECT
        campaign_id,
        seller_id,
        action_label,                       -- scale | cut | hold (from ad_performance suite)
        SUM(impressions)                    AS total_impressions,
        SUM(clicks)                         AS total_clicks,
        COUNT(DISTINCT order_id)            AS converted_orders,
        CASE
            WHEN SUM(impressions) = 0 THEN NULL
            ELSE ROUND(SUM(clicks)::numeric / SUM(impressions) * 100, 2)
        END AS ctr_pct
    FROM ad_campaign_snapshots
    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY 1, 2, 3
)
SELECT
    action_label,
    COUNT(DISTINCT seller_id)   AS seller_count,
    ROUND(AVG(ctr_pct), 2)      AS avg_ctr_pct,
    SUM(converted_orders)       AS total_orders
FROM campaign_metrics
GROUP BY action_label
ORDER BY action_label;
```

## Seller lifecycle funnel

```sql
-- Funnel: registered → first order → 7-day reorder → 30-day active
WITH stages AS (
    SELECT
        s.seller_id,
        s.created_at                                AS registered_at,
        MIN(o.created_at)                           AS first_order_at,
        MIN(o2.created_at)                          AS reorder_7d_at
    FROM sellers s
    LEFT JOIN orders o
        ON o.seller_id = s.seller_id
    LEFT JOIN orders o2
        ON o2.seller_id = s.seller_id
        AND o2.created_at BETWEEN MIN(o.created_at) + INTERVAL '1 day'
                               AND MIN(o.created_at) + INTERVAL '7 days'
    GROUP BY s.seller_id, s.created_at
)
SELECT
    COUNT(*)                                               AS registered,
    COUNT(first_order_at)                                  AS placed_first_order,
    COUNT(reorder_7d_at)                                   AS reordered_within_7d,
    ROUND(COUNT(first_order_at)::numeric / COUNT(*) * 100, 1)
                                                           AS first_order_pct,
    ROUND(COUNT(reorder_7d_at)::numeric
        / NULLIF(COUNT(first_order_at), 0) * 100, 1)      AS reorder_7d_pct
FROM stages;
```

## Return anomaly profiling

```sql
-- Profile return_reason distribution for anomaly model label review
-- Allowed labels: item_swap, empty_return, other (ADR-011)
SELECT
    return_reason,
    COUNT(*)                                        AS total,
    ROUND(COUNT(*)::numeric / SUM(COUNT(*)) OVER () * 100, 1) AS pct
FROM order_returns
WHERE return_reason IN ('item_swap', 'empty_return', 'other')
GROUP BY return_reason
ORDER BY total DESC;
```

## Weekly KPI trend (tier output — not raw values)

```sql
-- Seller KPI trend for Home tab display signals — output tier labels only
SELECT
    date_trunc('week', created_at)  AS week,
    COUNT(DISTINCT seller_id)       AS active_sellers,
    COUNT(*)                        AS total_orders,
    CASE
        WHEN COUNT(*) >= 500 THEN 'high'
        WHEN COUNT(*) >= 100 THEN 'medium'
        ELSE 'low'
    END                             AS volume_tier
FROM orders
GROUP BY 1
ORDER BY 1 DESC
LIMIT 12;
```

# Statistical methods

Use for **product analytics** (UX engagement, approval flows, A/B-style comparisons)
only. Not for seller financial comparisons — use tiers/deltas instead.

## Group comparison (t-test)

```python
from scipy import stats
import numpy as np

def compare_groups(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> dict:
    """Compare two UX metric groups. Report effect size, not just p-value."""
    stat, p = stats.ttest_ind(a, b)
    pooled_std = np.sqrt((a.std() ** 2 + b.std() ** 2) / 2)
    cohens_d = (a.mean() - b.mean()) / pooled_std if pooled_std > 0 else 0.0
    return {
        "t_statistic": float(stat),
        "p_value": float(p),
        "cohens_d": float(cohens_d),
        "significant": p < alpha,
        "effect_size": "large" if abs(cohens_d) >= 0.8 else "medium" if abs(cohens_d) >= 0.5 else "small",
    }
```

## Proportion test (funnel step comparison)

```python
def compare_proportions(n_a: int, conv_a: int, n_b: int, conv_b: int,
                         alpha: float = 0.05) -> dict:
    p_a = conv_a / n_a
    p_b = conv_b / n_b
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se = (p_pool * (1 - p_pool) * (1/n_a + 1/n_b)) ** 0.5
    z = (p_b - p_a) / se if se > 0 else 0.0
    from scipy import stats
    p_val = 2 * (1 - stats.norm.cdf(abs(z)))
    return {
        "rate_a": round(p_a, 4), "rate_b": round(p_b, 4),
        "lift": round((p_b - p_a) / p_a, 4) if p_a > 0 else None,
        "p_value": round(p_val, 4), "significant": p_val < alpha,
    }
```

# Data constraints

- **Financial PII:** `revenue`, `gmv`, `roas`, `ad_spend`, `cpa`, `cpc`, `ctr`, `aov`
  are financial PII per `core-safety.mdc`. Present as tiers (`high/medium/low`),
  week-over-week deltas (%), or rank ordinals — never raw values in reports, prompts,
  or handoff docs.
- **Buyer PII:** Use masked `buyer_id` only; no name, email, or phone in queries.
  See `data-sources.md` §Forbidden inputs.
- **Phase gate:** Only query data confirmed in `data-sources.md` for the active phase.
  Phase 1 = mock/fixtures. Phase 2.0 = backtest parquet. Phase 2.5 = live TikTok polling.
- **Affiliate scope:** Do not include affiliate/creator signals in any return-fraud
  or anomaly profiling per ADR-011.

# Insight delivery template

```markdown
## [Headline: action-oriented finding — use tier language]

**What:** One-sentence observation with magnitude (%, rank, tier change).
**So What:** Why this matters for TikTok Shop seller workflow (approval, ad spend, lifecycle).
**Now What:** Recommended product or workflow action with expected outcome.
**Confidence:** High (≥30d data, p<0.05) | Medium | Low (sparse / Phase 1 fixture)
**Limitations:** Data gaps, label sparsity, phase constraints.
```

# Handoff

- **SQL transforms** belong in `analytics-engineer` skill → Supabase views, Alembic.
- **KPI framework** belongs in `business-intelligence` skill → Home tab display tiers.
- **ML training** belongs in `mle-agent` skill → feature builders, artifacts.
- **Algorithm selection** belongs in `data-scientist` skill → T1–T8 vetting.

# Scope & limitations

**In scope:** Analytical SQL queries against the Supabase/PostgreSQL schema, cohort and
funnel analysis, return and ad performance profiling, statistical tests for product
metrics, and structured insight delivery.

**Out of scope:** ML model training or feature engineering (mle-agent), KPI framework
and RAG threshold design (business-intelligence), Alembic migrations or RLS
(analytics-engineer), A/B test infrastructure (product analytics tooling outside src/).

**Limitations:** Backtest parquet exists from Phase 2.0 only — no production-volume
trends are available in Phase 1. Statistical tests on financial metrics require
tier-aggregated inputs only; do not run raw-value comparisons.
