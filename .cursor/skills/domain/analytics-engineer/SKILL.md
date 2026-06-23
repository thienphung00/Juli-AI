---
name: analytics-engineer
description: >-
  Data modeling, schema design, Alembic migrations, Supabase views, and
  Row Level Security for Juli-AI's PostgreSQL backend. Use when designing
  entity schemas, writing Alembic migration files, building Supabase views
  or materialized views as transform layers, configuring per-seller RLS
  policies, or maintaining the feature-store schema. Not for SQL analysis
  (data-analyst), ML training (mle-agent), or KPI framework design (business-intelligence).
metadata:
  version: 1.0.0
  category: data-analytics
  updated: 2026-06-19
  tags: [analytics-engineering, schema, alembic, supabase, rls, transforms, juli-ai]
---

# Purpose

Use when **building or modifying the data layer** that backs Juli-AI's analytics:
entity schemas, Alembic migrations, Supabase views/materialized views,
multi-tenant Row Level Security, and feature-store schema maintenance.

| Skill | Role |
|-------|------|
| **analytics-engineer** (this) | Schema design, Alembic migrations, Supabase views, RLS, feature schema |
| [`data-analyst`](../data-analyst/SKILL.md) | SQL analysis against the schema built here |
| [`business-intelligence`](../business-intelligence/SKILL.md) | KPI signals that consume views/signals produced here |
| [`data-scientist`](../data-scientist.md) | Feature schema vetting; technique-to-column mapping |
| [`mle-agent`](../mle-agent.md) | Feature builder implementation in `src/modules/ml/features/` |

# Authority chain (read before editing schema)

1. [`docs/data-models/feature-store-schema.md`](../../../../docs/data-models/feature-store-schema.md) — **canonical column names** for all ML feature groups A–D; renaming is a breaking change
2. [`docs/data-models/canonical-entities.md`](../../../../docs/data-models/canonical-entities.md) — Return/Order field alignment across P1→P2; source of truth for entity field names
3. [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) — allowed vs forbidden data sources per phase; scraping is forbidden
4. [`docs/decisions/011-display-grade-analytics-layer.md`](../../../../docs/decisions/011-display-grade-analytics-layer.md) — analytics views are advisory; never mix decision-grade execution logic into views
5. [`.cursor/skills/domain/postgres-patterns.md`](../postgres-patterns.md) — query conventions, ORM, parameterization rules
6. [`EXECUTION.md`](../../../../EXECUTION.md) — current phase; Phase 1 = fixtures, Phase 2.5 = live TikTok data

# Repo layout

```
src/
  db/                         # Supabase client init, connection helpers
  models/                     # SQLAlchemy ORM model definitions
    sellers.py
    orders.py
    returns.py
    campaigns.py
  modules/ml/features/        # Feature builder functions (schema-locked)
    build_anomaly_features.py
    build_seller_stage_features.py
    build_ad_features.py
    time_windows.py

alembic/
  env.py
  versions/                   # Migration files — one concern per file
    YYYYMMDD_HHMMSS_<slug>.py

supabase/
  migrations/                 # Supabase CLI-compatible SQL migrations (RLS, policies)
  seed.sql                    # Development seed data

docs/data-models/
  feature-store-schema.md     # Feature group authority — edit WITH this skill active
  canonical-entities.md       # Entity field alignment
```

# Alembic migration rules

1. **One concern per migration** — schema change, RLS policy, index, or constraint separately.
2. **No secrets or connection strings** in migration files (`core-safety.mdc`).
3. **Never drop columns with data** without a two-step deprecate-then-drop pattern.
4. **Rename = breaking change for ML** — validate `feature_schema_hash` consumers before renaming
   any column in feature groups A–D (see `feature-store-schema.md`).
5. **Idempotent** — use `IF NOT EXISTS` / `IF EXISTS` guards; migrations may run twice in CI.

## Migration file template

```python
# alembic/versions/20260619_120000_add_seller_lifecycle_stage.py
"""add seller_lifecycle_stage to sellers table

Revision ID: abc123def456
Revises: prev_revision_id
Create Date: 2026-06-19 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column(
        "sellers",
        sa.Column(
            "lifecycle_stage",
            sa.String(32),
            nullable=True,
            comment="Classifier output: new | leakage | growth (T8 suite)",
        ),
    )
    op.create_index(
        "ix_sellers_lifecycle_stage",
        "sellers",
        ["lifecycle_stage"],
    )

def downgrade() -> None:
    op.drop_index("ix_sellers_lifecycle_stage", table_name="sellers")
    op.drop_column("sellers", "lifecycle_stage")
```

# Supabase view patterns

## Seller analytics mart view (display-grade signals only)

```sql
-- supabase/migrations/20260619_create_seller_analytics_view.sql
-- Read-only mart view backing Home tab signals — no raw financial values exposed
CREATE OR REPLACE VIEW seller_analytics AS
SELECT
    s.id                                                AS seller_id,
    s.lifecycle_stage,
    COUNT(o.id)                                         AS order_count_30d,
    COUNT(r.id)                                         AS return_count_30d,
    CASE
        WHEN COUNT(o.id) >= 100 THEN 'high'
        WHEN COUNT(o.id) >= 20  THEN 'medium'
        ELSE 'low'
    END                                                 AS volume_tier,
    CASE
        WHEN COUNT(r.id)::float / NULLIF(COUNT(o.id), 0) >= 0.10 THEN 'high'
        WHEN COUNT(r.id)::float / NULLIF(COUNT(o.id), 0) >= 0.05 THEN 'medium'
        ELSE 'low'
    END                                                 AS return_risk_tier,
    MAX(o.created_at)                                   AS last_order_at
FROM sellers s
LEFT JOIN orders o
    ON o.seller_id = s.id
    AND o.created_at >= NOW() - INTERVAL '30 days'
LEFT JOIN order_returns r
    ON r.seller_id = s.id
    AND r.created_at >= NOW() - INTERVAL '30 days'
GROUP BY s.id, s.lifecycle_stage;
```

## Materialized view for batch signals (Phase 2+)

```sql
-- Refresh after 08:00 UTC batch; do not keep live
CREATE MATERIALIZED VIEW seller_kpi_snapshot AS
SELECT
    seller_id,
    date_trunc('week', NOW())   AS snapshot_week,
    volume_tier,
    return_risk_tier,
    lifecycle_stage
FROM seller_analytics;

-- Refresh command (called from Celery batch job in Phase 2):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY seller_kpi_snapshot;
```

# Row Level Security (multi-tenant seller isolation)

Every table containing seller data **must** have RLS enabled. Sellers can only access
their own rows. Service-role operations (backend batch, ML training) bypass RLS.

```sql
-- supabase/migrations/20260619_rls_sellers.sql

-- Enable RLS on all seller-scoped tables
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_returns ENABLE ROW LEVEL SECURITY;
ALTER TABLE ad_campaign_snapshots ENABLE ROW LEVEL SECURITY;

-- Sellers read/write their own rows via JWT claim
CREATE POLICY "seller_own_orders" ON orders
    FOR ALL
    USING (seller_id = (current_setting('request.jwt.claims', true)::json ->> 'seller_id')::uuid);

CREATE POLICY "seller_own_returns" ON order_returns
    FOR ALL
    USING (seller_id = (current_setting('request.jwt.claims', true)::json ->> 'seller_id')::uuid);

-- Service role bypasses RLS for batch/ML jobs (never expose service key to client)
-- Supabase service-role key must only appear in server-side env (core-safety.mdc)
```

## RLS test pattern

```python
# tests/db/test_rls.py — verify cross-seller isolation
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_seller_cannot_read_other_seller_orders(client: AsyncClient, seller_a_token, seller_b_order_id):
    """Seller A must not be able to read Seller B's orders."""
    resp = await client.get(
        f"/api/v1/orders/{seller_b_order_id}",
        headers={"Authorization": f"Bearer {seller_a_token}"},
    )
    assert resp.status_code == 404  # RLS makes the row invisible, not 403
```

# Feature store schema maintenance

The `feature-store-schema.md` is the canonical source of truth for all ML feature columns.
When adding or renaming columns:

1. **Update `feature-store-schema.md` first** (this skill) — add the column to the correct group (A–D).
2. **Update SQLAlchemy model** in `src/models/`.
3. **Write Alembic migration**.
4. **Update feature builder** in `src/modules/ml/features/` (mle-agent skill).
5. **Bump `feature_schema_hash`** in any affected artifact `metadata.json`
   — a mismatch at inference load time is a hard error.

## Feature groups (abbreviated)

| Group | Entity | Example columns |
|-------|--------|-----------------|
| A | Seller | `seller_id`, `lifecycle_stage`, `days_since_first_order` |
| B | Order/Return | `return_reason`, `item_swap_flag`, `order_amount_tier` |
| C | Ad campaign | `action_label`, `budget_tier`, `campaign_age_days` |
| D | Time windows | `orders_30d`, `returns_7d`, `revenue_delta_wow_tier` |

Column names in groups B–D that contain financial values must use **tier suffixes**
(`_tier`, `_delta_pct`, `_rank`) — never the raw float value in a column accessible
to the LLM copy layer.

# Dimensional model conventions

Juli-AI does not use dbt. The equivalent layering in Supabase/SQLAlchemy:

| dbt Layer | Juli-AI equivalent | Location |
|-----------|--------------------|----------|
| Staging | SQLAlchemy models + Alembic migrations | `src/models/` |
| Intermediate | Supabase SQL views | `supabase/migrations/*_view.sql` |
| Mart | Materialized views + API serializers | `supabase/migrations/*_mat.sql` + `src/api/` |

## Naming conventions

```
Tables:    snake_case, plural nouns — orders, sellers, order_returns
Views:     <entity>_analytics, <entity>_kpi_snapshot
Indexes:   ix_<table>_<column(s)>
Policies:  <entity>_own_<table> (RLS)
Migrations: YYYYMMDD_HHMMSS_<verb>_<subject>.py
```

# Troubleshooting

| Problem | Likely cause | Resolution |
|---------|-------------|------------|
| `feature_schema_hash` mismatch at model load | Column renamed or added without updating hash | Re-run `publish_model` after migration; see `mle-agent-REFERENCE.md` |
| RLS returning 404 instead of data | JWT `seller_id` claim missing or wrong type | Verify Supabase auth config passes `seller_id` as UUID in JWT claims |
| Migration fails with "relation already exists" | Migration not idempotent | Add `IF NOT EXISTS` guard; check whether migration ran in prior env |
| Cross-seller data leak in test | RLS policy references wrong claim key | Test with `seller_cannot_read_other_seller_orders` pattern above |
| Materialized view stale after batch | Celery refresh job failed or ran before batch | Check Celery beat schedule; ensure `REFRESH MATERIALIZED VIEW CONCURRENTLY` runs after 08:00 UTC batch completes |

# Integration points

- **Data Analyst** — Queries run against views built here. Schema changes require
  data-analyst to verify SQL still returns expected shapes.
- **Business Intelligence** — Materialized views are the data source for Home tab KPI
  signal components. View schema changes cascade to signal JSON contracts.
- **MLE Agent** — Feature builders in `src/modules/ml/features/` depend on column names
  locked in `feature-store-schema.md`. Schema changes here must be coordinated.
- **Data Scientist** — Feature group additions must pass T1–T8 vetting before columns
  are added to the feature store schema.

# Success criteria

- Every Alembic migration is idempotent and has a working `downgrade()`.
- All seller-scoped tables have RLS enabled with a `seller_own_*` policy.
- Feature column additions update `feature-store-schema.md` + SQLAlchemy model + Alembic migration atomically.
- No raw financial values (`revenue`, `roas`, `ad_spend`, etc.) appear in view result sets or API serializers without tier transformation.
- RLS isolation is verified by a cross-seller test before each schema release.

# Scope & limitations

**In scope:** SQLAlchemy model definitions, Alembic migration authoring, Supabase view
and materialized view design, RLS policy configuration, feature-store schema evolution,
and dimensional modeling conventions for Juli-AI's PostgreSQL backend.

**Out of scope:** Ad-hoc SQL analysis (data-analyst), ML feature builder implementation
(mle-agent), KPI framework and Home tab design (business-intelligence), algorithm
selection (data-scientist), API route or service logic (`python-patterns` rule).

**Limitations:** Juli-AI does not use dbt. Transformation layers are expressed as
Supabase SQL views and materialized views — slim CI state-diffing is not available
without dbt's manifest. Use `schema_diff` via Supabase CLI or `supabase db diff`
for schema drift detection between environments.
