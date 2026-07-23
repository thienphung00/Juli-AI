---
name: platform-docs
description: >-
  Scans and generates platform documentation for Seller and Creator identities,
  covering Feature Guide and Policy Center sections, under docs/<vendor>_platform/.
  Use when onboarding marketplace feature knowledge (tools, programs, workflows),
  seller/creator policy rules (account health, limits, eligibility, compliance),
  or preparing decision context for Architect planning, api-docs, focus, to-prd, and review.
catalog:
  pluginIndex: skill-catalog
  loadWhen:
    - seller center help center terms of service
    - account health violation limit eligibility policy
    - seller feature guide creator feature guide platform docs
    - tiktok shop university feature policy creator seller
  cliDocs:
    - context7
---

# Platform Docs

Scan official **Seller** and **Creator** platform documentation — Feature Guides and
Policy Centers — and convert them into a normalized knowledge base under
`docs/<vendor>_platform/`. This complements [`api-docs`](../api-docs/SKILL.md):
**api-docs** owns *how to integrate* (schemas, endpoints, webhooks); **platform-docs**
owns *what the platform offers and enforces* (features, limits, health, eligibility, compliance).

**Canonical pairing:** [`docs/integrations/tiktok_api/`](../../../../docs/integrations/tiktok_api/) (technical) +
[`docs/integrations/tiktok_platform/`](../../../../docs/integrations/tiktok_platform/) (operational + feature).

## Identity × Content matrix

| Identity | Feature Guide | Policy Center |
|----------|--------------|---------------|
| **Seller** | What tools and programs the platform gives sellers | Rules, limits, health, compliance, enforcement |
| **Creator** | What tools and programs creators get (collab, live, affiliate) | Creator obligations, eligibility, prohibited content |

Both dimensions must be extracted and kept in separate subdirectories.

## Boundaries

| Skill | Perspective | Responsibility |
|-------|-------------|----------------|
| **`platform-docs`** | Seller / creator / operator | Features, rules, limits, health, eligibility, enforcement |
| **`api-docs`** | Developer / integrator | Endpoints, schemas, auth, webhooks, rate limits |
| **Architect Agent (Planning)** | Product / feature | Updates canonical docs (`EXECUTION.md`, `system-design.md`, architecture, ADRs) informed by both |
| **`focus`** | Implementation routing | Loads `docs/<vendor>_platform/` + `docs/<vendor>_api/` |

**MUST:** pull official sources only (Seller Center, Creator Center, Help Center, Policy Hub,
TikTok Shop University); produce the file set below; map features and policies → Juli product
guardrails and `data-sources.md` constraints; cross-link `api-docs` when the API exposes
platform fields.

**MUST NOT:** scrape live Seller Center dashboards or account-specific pages; invent
thresholds, penalties, or feature capabilities; write feature PRDs; implement code;
substitute unofficial wiki or community summaries for official docs.

## Source URLs (TikTok Shop)

| Identity | Section | Base URL pattern |
|----------|---------|-----------------|
| Seller | Feature Guide | `https://seller-vn.tiktok.com/university/home?role=seller&menu=feature` |
| Seller | Policy Center | `https://seller-vn.tiktok.com/university/home?role=seller&menu=policy` |
| Creator | Feature Guide | `https://seller-vn.tiktok.com/university/home?role=creator&menu=feature` |
| Creator | Policy Center | `https://seller-vn.tiktok.com/university/home?role=creator&menu=policy` |

Append `&content_id=<id>` when fetching a specific article. Use `WebFetch` on these
published URLs. Do not rely on search engines or scraped mirrors.

## Primary tools

1. **TikTok Shop University** — Feature Guide and Policy Center (use `WebFetch` on the URLs above).
2. **Official Help Center / Seller Center / Creator Center** — supplementary policy articles.
3. **Context7 CLI** — only when Focus/Meta selects it because policy/feature text lives
   inside an official partner **SDK/library** reference (technical), not for University
   HTML articles. Not an MCP.

**Source priority:** TikTok Shop University (official) → Help Center / Partner Center policy
→ official blog / changelog announcements → API policy fields (via `api-docs`) →
community (**only** if no official source; mark `UNVERIFIED`).

## Workflow (summary)

```
Scope (identity + section) → Discover URLs → Extract → Normalize → docs/<vendor>_platform/ → Platform hooks → Handoff
```

### Step 0 — Baseline (required)

Always read before extraction:

- `docs/architecture/data-sources.md` (Forbidden / substitutes / operational rules)
- `docs/architecture/map.md`
- `docs/<vendor>_platform/README.md` (if refresh)
- `docs/<vendor>_api/README.md` (if exists — cross-link technical exposure)
- `EXECUTION.md` (phases + scope)

Record whether this vendor is **new** or a **refresh**, and which identity/section pair
you are covering.

### Steps 1–4 — Extract and file

Follow [REFERENCE.md](REFERENCE.md) for discovery categories, per-rule fields, Juli
guardrail mapping, and the required output file set.

| File | Required? |
|------|-----------|
| `README.md` | Always — top-level index |
| `seller/README.md` | When seller scope is covered |
| `seller/feature-guide.md` | When Seller Feature Guide is in scope |
| `seller/policy.md` | When Seller Policy Center is in scope |
| `seller/account-health.md` | If seller health / violation system exists |
| `seller/operational-limits.md` | If seller order/listing/SLA limits exist |
| `seller/programs-and-eligibility.md` | If affiliate, live, ads, tier programs apply |
| `seller/compliance.md` | If ToS, ISV obligations, prohibited behaviors documented |
| `seller/implementation-hooks.md` | Always (features + policy → alerts, gates, ETL) |
| `creator/README.md` | When creator scope is covered |
| `creator/feature-guide.md` | When Creator Feature Guide is in scope |
| `creator/policy.md` | When Creator Policy Center is in scope |
| `creator/programs-and-eligibility.md` | If creator programs (collab, live, affiliate) apply |
| `creator/compliance.md` | If creator obligations / prohibited content documented |
| `creator/implementation-hooks.md` | Always (→ matching, recommendation, eligibility gates) |
| `cross-cutting.md` | When a topic spans both identities (e.g. affiliate collab) |
| `risks.md` | Always |

Do **not** create parallel filenames (`overview.md`, `tos-summary.md`, `limits-cheatsheet.md`)
— fold into the files above.

### Step 5 — Platform hooks

1. Propose updates to `docs/architecture/data-sources.md` — **Substitutes**, **Operational
   Rules**, and **Forbidden** rows when features or policies constrain product behavior.
2. Cross-link `docs/<vendor>_api/risks.md` and `architecture.md` when platform rules drive
   technical mitigations.
3. Draft ADR candidates when policy or feature constraints force ingestion model or
   feature-scope trade-offs.

### Step 6 — Validate

- [ ] No invented thresholds, penalties, eligibility rules, or feature capabilities
- [ ] Every major claim has `Source:` URL (official page, not scraped dashboard)
- [ ] Uncertainty marked (`UNKNOWN`, `UNVERIFIED`, `DISCREPANCY`, `REGION-VARIANT`)
- [ ] Features and policies mapped to Juli guardrails in `implementation-hooks.md`
- [ ] Forbidden patterns aligned with `data-sources.md` (#8 scraping, #9 Seller Center, #17 PII)
- [ ] Seller and creator subdirectories kept separate; `cross-cutting.md` for shared topics
- [ ] Distinct from `api-docs` — no endpoint inventories here

## Handoff

### → Planning (Architect) / api-docs

```markdown
## Handoff: platform-docs → planning
### Vendor
<name> — docs/<vendor>_platform/
### Scope covered
- Seller Feature Guide: <Yes / No / Partial>
- Seller Policy Center: <Yes / No / Partial>
- Creator Feature Guide: <Yes / No / Partial>
- Creator Policy Center: <Yes / No / Partial>
### Feature surface
- Seller tools: <key features and programs found>
- Creator tools: <key features and programs found>
- Cross-cutting: <shared programs, e.g. affiliate>
### Policy surface
- Account health: <summary or N/A>
- Hard limits: <order volume, listing caps, …>
- Eligibility gates: <programs, regions, tiers>
- ISV / data obligations: <summary>
- Enforcement: <penalties, appeals, recovery>
### Implementation guardrails
- Alerts to surface: <from implementation-hooks.md>
- Features to gate/defer: <MVP vs v1.5 vs Forbidden>
- API fields that expose platform data: <cross-ref api-docs>
### data-sources.md updates
- Substitutes: <proposed rows>
- Operational rules: <proposed bullets>
### ADR candidates
- [ ] ADR-NNN: <title> — <one-line rationale>
### Open questions
- …
```

### → focus (implementation)

Load `docs/<vendor>_platform/README.md`, relevant `seller/` and/or `creator/`
subdirectory files (`feature-guide.md`, `policy.md`, `implementation-hooks.md`,
`operational-limits.md`, `compliance.md`), plus matching `docs/<vendor>_api/` and
`data-sources.md`.

## Additional resources

- Full workflow, templates, mapping tables: [REFERENCE.md](REFERENCE.md)
- Technical counterpart: [`api-docs`](../api-docs/SKILL.md)
