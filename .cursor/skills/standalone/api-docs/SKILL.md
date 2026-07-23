---
name: api-docs
description: >-
  Converts official vendor API documentation into implementation-ready reference
  docs under docs/<vendor>_api/. Use when onboarding a new external API, refreshing
  stale integration docs, or preparing source-of-truth material for Architect planning,
  focus, to-prd, to-issues, Executor implementation, and review.
catalog:
  pluginIndex: skill-catalog
  loadWhen:
    - library framework api reference
    - official sdk openapi changelog
  cliDocs:
    - context7
---

# API Docs

Convert **official** vendor API documentation into a normalized, implementation-ready
knowledge base under `docs/<vendor>_api/`. This is **not** a summary — it is
source-of-truth material that downstream skills load without re-reading vendor sites.

**Canonical example:** [`docs/integrations/tiktok_api/README.md`](../../../../docs/integrations/tiktok_api/README.md)

## Boundaries

| Skill | Responsibility |
|-------|----------------|
| **`api-docs`** | Extract, normalize, and file vendor API reference under `docs/<vendor>_api/` |
| **`platform-docs`** | Seller/creator platform docs under `docs/<vendor>_platform/` (features, limits, health, eligibility) |
| **Architect Agent (Planning)** | Interview, scope features, update `EXECUTION.md`, `system-design.md`, `docs/architecture/`, `docs/adr/` |
| **`to-prd` / `to-issues`** | Turn feature context into PRDs and GitHub issues |
| **`focus`** | Route which docs to load for implementation |

**MUST:** pull official sources only; produce the file set below; map vendor entities → Juli commerce graph; propose a `data-sources.md` row; suggest ADR candidates when auth/runtime boundaries are non-obvious.

**MUST NOT:** write feature PRDs; create GitHub issues; implement clients/webhooks/sync jobs; invent endpoints, fields, or behaviors.

## Primary tools

1. Official vendor API / SDK / OpenAPI pages (`WebFetch` when URLs are known).
2. **Context7 CLI** (`npx ctx7@latest`) — **only when Focus/Meta selects it** for
   SDK/library references during this technical extraction. Follow
   [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc) and
   skill-catalog `catalog.cliDocs`. **Not an MCP.**

**Source priority:** official API docs → official SDK docs → OpenAPI/JSON Schema → official GitHub + changelogs → community (**only** if no official source; mark `UNVERIFIED`).

## Workflow (summary)

```
Input URLs → Discover → Extract → Normalize → docs/<vendor>_api/ → Platform hooks → Handoff
```

### Step 0 — Baseline (required)

Always read before extraction:

- `docs/architecture/data-sources.md`
- `docs/architecture/map.md`
- `docs/<vendor>_api/README.md` (if refresh)
- `EXECUTION.md` (phases + scope)

Record whether this vendor is **new** or a **refresh**.

### Steps 1–4 — Extract and file

Follow [REFERENCE.md](REFERENCE.md) for discovery categories, per-endpoint fields, Juli entity mapping, and the required output file set.

| File | Required? |
|------|-----------|
| `README.md` | Always |
| `authentication.md` | Always |
| `endpoints.md` | Always |
| `webhooks.md` | If webhooks exist |
| `rate-limits.md` | Always |
| `architecture.md` | Always (must reference real `src/` paths) |
| `multi-tenant.md` | If multi-shop |
| `risks.md` | Always |
| `tech-stack.md` | Always |
| `mvp-roadmap.md` | If net-new vendor |
| `context-plan.md` | Optional |

Do **not** create parallel filenames (`overview.md`, `domain-model.md`, etc.) — fold into the files above.

### Step 5 — Platform hooks

1. Propose or update a row in `docs/architecture/data-sources.md` (status per legend: MVP / v1.5 / v2.0 / Out / Forbidden).
2. Draft ADR candidates in `docs/adr/NNN-<slug>.md` when auth boundaries, ingestion model, or forbidden substitutes are non-obvious; update `docs/adr/README.md`.

### Step 6 — Validate

- [ ] No invented endpoints or undocumented fields
- [ ] Every major claim has `Source:` URL
- [ ] Uncertainty marked (`UNKNOWN`, `UNVERIFIED`, `DISCREPANCY`)
- [ ] Vendor → Juli entity mapping documented
- [ ] `architecture.md` references real `src/` module paths
- [ ] `data-sources.md` row drafted with correct status
- [ ] Forbidden patterns flagged (no scraping, unofficial streams, buyer PII)

## Handoff

### → Planning (Architect Agent)

```markdown
## Handoff: api-docs → planning
### Vendor
<name> — docs/<vendor>_api/
### Data source row
<# from data-sources.md or proposed row>
### Integration surface
- Auth: <summary>
- Key resources: <list>
- Webhooks: <yes/no + events>
- Rate limits: <summary>
- Known gaps: <from risks.md>
### Suggested feature boundaries
- In scope for MVP: …
- Defer to v1.5/v2.0: …
- Forbidden: …
### ADR candidates
- [ ] ADR-NNN: <title> — <one-line rationale>
### Open questions
- …
```

### → focus (implementation)

Point implementers at `docs/<vendor>_api/README.md`, `authentication.md`, `endpoints.md`, `webhooks.md` (if applicable), `rate-limits.md`, `architecture.md`, plus `docs/architecture/data-sources.md`, `docs/architecture/map.md`, and affected `MODULE.md` files.

## Additional resources

- Full workflow, templates, and mapping tables: [REFERENCE.md](REFERENCE.md)
- Platform docs counterpart: [`platform-docs`](../platform-docs/SKILL.md)
- TikTok reference layout: [`docs/integrations/tiktok_api/`](../../../../docs/integrations/tiktok_api/)
