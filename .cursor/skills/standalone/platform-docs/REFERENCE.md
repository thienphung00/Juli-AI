# Platform Docs — Reference

Detailed workflow for scanning and generating Seller and Creator platform documentation
(Feature Guide + Policy Center) into `docs/<vendor>_platform/`. Load this when executing
a full extraction or refresh.

## Relationship to api-docs

| Dimension | `api-docs` | `platform-docs` |
|-----------|------------|-----------------|
| Audience | Developers, ISV integrators | Sellers, creators, operators, compliance reviewers |
| Typical sources | API reference, OpenAPI, SDK repos | TikTok Shop University, Seller Center, Creator Center, Help Center, ToS |
| Answers | "What endpoint returns order status?" | "What tools do sellers have?" / "What order volume triggers a health penalty?" |
| Drives | Client code, ETL schemas, webhooks | Product guardrails, alerts, feature gates, matching filters, UX copy |
| Overlap | Technical rate limits, scope gates | Business quotas, violation tiers, program eligibility |

When both apply, **extract separately** then cross-link in `implementation-hooks.md`
and `docs/<vendor>_api/risks.md`.

---

## Identity × Content scope

Before extracting anything, declare which cells of the matrix you are covering:

| Identity | Feature Guide | Policy Center |
|----------|:---:|:---:|
| **Seller** | ✓ / ✗ | ✓ / ✗ |
| **Creator** | ✓ / ✗ | ✓ / ✗ |

You may run all four cells in a single pass, or scope to one identity/section at a time.
Record the scope in the handoff block.

---

## Input

One or more of:

- TikTok Shop University URLs (Feature Guide, Policy Center) for the relevant identity
- Seller Center / Creator Center / Partner Center policy pages
- Help Center / Academy articles
- Terms of Service, ISV agreement, data-processing addenda
- Official policy changelog or announcement posts
- Context7 IDs when policy lives inside partner documentation

**TikTok Shop University URL patterns:**

| Identity | Section | URL |
|----------|---------|-----|
| Seller | Feature Guide | `https://seller-vn.tiktok.com/university/home?role=seller&menu=feature` |
| Seller | Policy Center | `https://seller-vn.tiktok.com/university/home?role=seller&menu=policy` |
| Creator | Feature Guide | `https://seller-vn.tiktok.com/university/home?role=creator&menu=feature` |
| Creator | Policy Center | `https://seller-vn.tiktok.com/university/home?role=creator&menu=policy` |

Append `&default_language=en&content_id=<id>` to fetch a specific article. Always use
`WebFetch` on the published URL.

**Repo examples:** TikTok Shop Seller Policy, Shopee Seller Education Hub, Lazada University.

**Before writing anything new**, read:

- `docs/architecture/data-sources.md`
- Existing `docs/<vendor>_platform/` (if refresh)
- Existing `docs/<vendor>_api/` (technical exposure of platform fields)

---

## Step 1 — Discover

### 1a — Seller Feature Guide

Collect features and programs with **source URLs** for every claim:

| Category | Capture |
|----------|---------|
| Listing & product tools | Product creation, listing management, bulk upload, variations |
| Order management | Order processing, fulfillment, returns, dispute handling |
| Marketing & ads | TikTok Ads integration, vouchers, promotions, flash sales |
| Shop analytics | Sales reports, traffic sources, conversion metrics |
| Affiliate programs | How sellers recruit creators, commission structures, collab tools |
| Live commerce (seller) | Live streaming setup, shoppable links, moderation tools |
| Logistics & shipping | Carrier integrations, shipping templates, SLA requirements |
| Finance & settlements | Payment schedules, invoicing, settlement hold periods |
| Seller tiers & programs | Star Seller, Mall, verified programs, tier benefits |
| Regional features | Market-specific tools (VN vs US vs UK vs ID) |

### 1b — Seller Policy Center

| Category | Capture |
|----------|---------|
| Account health | Rating dimensions, score ranges, violation types, recovery paths |
| Operational limits | Order volume caps, listing limits, GMV tiers, fulfillment SLAs |
| Programs & eligibility | Affiliate, live, ads, regional onboarding, tier upgrades |
| Compliance | ToS, prohibited products/content, data retention, buyer privacy |
| Enforcement | Penalties, suspensions, appeals, grace periods, reinstatement |
| Regional variance | Market-specific rules (SEA vs US vs UK) |
| Change cadence | Where official changelogs live; typical notice period |
| Seller UX | What sellers see in Seller Center when a limit or violation hits |

### 1c — Creator Feature Guide

| Category | Capture |
|----------|---------|
| Creator profile & setup | Account creation, verification, linking to shop |
| Product showcase | How creators display / recommend products in videos and live |
| Affiliate collab | How creators join affiliate programs, find products, earn commissions |
| Live commerce (creator) | Live streaming tools, product links, earnings dashboards |
| Creator analytics | Reach, GMV driven, commission reports |
| Creator marketplace | Brand collaboration hub, pitch tools, campaign management |
| Monetization programs | Creator Fund, LIVE Gifting, TikTok Shop affiliate |
| Regional features | Market-specific creator programs |

### 1d — Creator Policy Center

| Category | Capture |
|----------|---------|
| Creator eligibility | Follower thresholds, account age, region requirements |
| Prohibited content | Content rules, branded content disclosure, restricted categories |
| Affiliate obligations | FTC/CMA disclosure, misleading claim rules |
| Account health (creator) | Creator score, violation types, appeal path |
| Enforcement | Demotion, ban, commission withholding, reinstatement |
| Regional variance | Market-specific creator rules |

---

## Step 2 — Extract

### Feature Guide extraction

For **every feature or program** explicitly documented:

| Field | Required |
|-------|----------|
| Feature / program name | Yes |
| Applies to | Seller tier, creator tier, region, program — as documented |
| What it does | Capability description (verbatim or paraphrased from official source) |
| Prerequisites / eligibility | Account requirements, tier, region |
| Limits / quotas | Any documented caps or SLAs attached to the feature |
| Related API / webhook | Link to `api-docs` when the API exposes this feature |
| Regional notes | If documented |
| Source URL | Yes |

### Policy extraction

For **every rule or limit** explicitly documented:

| Field | Required |
|-------|----------|
| Rule name / category | Yes |
| Applies to | Seller/creator tier, region, program — as documented |
| Threshold / condition | Yes (exact values when published; else `UNKNOWN`) |
| Effect on seller / creator | Restriction, penalty, visibility loss, account action |
| Effect on ISV / API access | Scope loss, webhook pause, data masking — if documented |
| Recovery / appeal | If documented |
| Effective date / version | If documented |
| Regional notes | If documented |
| Source URL | Yes |

**Rules:**

- Do **not** infer thresholds or capabilities from anecdotes or forum posts.
- Mark gaps as `UNKNOWN — not in official docs`.
- When sources conflict (e.g. Help Center vs ToS), cite both and flag `DISCREPANCY`.
- Mark market-specific rules `REGION-VARIANT: <market>`.
- Distinguish **seller-facing** from **creator-facing** content when sources split them.

---

## Step 3 — Normalize

Map platform features and policies to **Juli product guardrails** and commerce graph behavior.

### Seller example mapping table

| Platform concept | Juli guardrail | Implementation touchpoint |
|------------------|----------------|---------------------------|
| Account health score | Risk chip on recommendations | `matching/prediction` risk band; dashboard badges |
| Order volume limit (new seller) | Sync + alert threshold | `cron_jobs/services/polling`; alerts module |
| Affiliate program (seller) | Creator match filter | `GET /v1/creators` eligibility gate |
| Seller tier (Star / Mall) | Trust signal in recommendations | Ranking model feature |
| Settlement hold period | `pending` finance signal | `data-sources.md` operational rule |
| Prohibited cross-shop scraping | **Forbidden** | `data-sources.md` #9 |
| Buyer PII restrictions | Masked `buyer_id` only | `data-sources.md` #17 |

### Creator example mapping table

| Platform concept | Juli guardrail | Implementation touchpoint |
|------------------|----------------|---------------------------|
| Creator follower threshold | Eligibility gate on match | `GET /v1/creators` filter; matching model |
| Affiliate commission rate | Match score input | Recommendation ranking; negotiation context |
| Content disclosure rule | UX copy + onboarding guard | Creator-facing copy in recommendation card |
| Creator account health | Risk signal in match filter | Matching model risk band |
| Creator live commerce eligibility | Feature gate | `programs-and-eligibility.md`; feature flag |

Document mappings in `implementation-hooks.md` and per-topic files.

### Phase mapping

Align each feature/rule with the phases in `EXECUTION.md`:

| Phase | Typical use |
|-------|-------------|
| **Phase 1** | Hard limits blocking ingestion or misleading users if ignored |
| **Phase 1.5 / 2** | Proactive checks, recommended actions tied to real data |
| **Later (Phase 2.5+)** | Near-realtime enforcement signals |
| **Forbidden** | Any feature requiring scraping, unofficial streams, or buyer PII |

---

## Step 4 — Generate docs

Write under **`docs/<vendor>_platform/`**:

### Top-level files

| File | Purpose |
|------|---------|
| `README.md` | Index table, identity × section coverage, official portal links |
| `cross-cutting.md` | Topics that span seller + creator (e.g. affiliate collab, live commerce) |
| `risks.md` | Policy change risk, regional drift, documentation gaps |

### `seller/` subdirectory

| File | Purpose |
|------|---------|
| `README.md` | Seller doc index, quick-reference table |
| `feature-guide.md` | Feature and program catalog from Seller Feature Guide |
| `policy.md` | Summary of Seller Policy Center (top-level rules and links) |
| `account-health.md` | Health dimensions, violation catalog, recovery |
| `operational-limits.md` | Order/listing/GMV limits, SLAs, tier breakpoints |
| `programs-and-eligibility.md` | Affiliate, live, ads, onboarding requirements, Star/Mall |
| `compliance.md` | ToS, ISV obligations, data use, prohibited behaviors |
| `implementation-hooks.md` | Feature + policy → alerts, gates, ETL behavior, API cross-refs |

### `creator/` subdirectory

| File | Purpose |
|------|---------|
| `README.md` | Creator doc index, quick-reference table |
| `feature-guide.md` | Feature and program catalog from Creator Feature Guide |
| `policy.md` | Summary of Creator Policy Center |
| `programs-and-eligibility.md` | Affiliate collab, live, Creator Marketplace, monetization |
| `compliance.md` | Content rules, disclosure obligations, prohibited categories |
| `implementation-hooks.md` | Feature + policy → matching filters, eligibility gates, UX copy |

**Content routing** (do not create parallel filenames):

| Would-be file | Fold into |
|---------------|-----------|
| `overview.md` | `README.md` |
| `tos-summary.md` | `compliance.md` |
| `limits-cheatsheet.md` | `operational-limits.md` |
| `guardrails.md` | `implementation-hooks.md` |
| `creator-overview.md` | `creator/README.md` |

### `README.md` quick-reference template

```markdown
# <Vendor> Platform Docs — Documentation Index

| Property | Value |
|----------|-------|
| Seller Feature Guide | <URL> |
| Seller Policy Center | <URL> |
| Creator Feature Guide | <URL> |
| Creator Policy Center | <URL> |
| Regions covered | … |
| Last reviewed | YYYY-MM-DD |
| Paired API docs | [docs/<vendor>_api/](../<vendor>_api/README.md) |

## Coverage

| Identity | Feature Guide | Policy Center |
|----------|:---:|:---:|
| Seller | ✓ / ✗ | ✓ / ✗ |
| Creator | ✓ / ✗ | ✓ / ✗ |

## Documents

| Document | Description |
|----------|-------------|
| [seller/feature-guide.md](seller/feature-guide.md) | Seller tools, programs, capabilities |
| [seller/policy.md](seller/policy.md) | Seller rules summary |
| [seller/implementation-hooks.md](seller/implementation-hooks.md) | → Juli guardrails |
| [creator/feature-guide.md](creator/feature-guide.md) | Creator tools, programs, monetization |
| [creator/policy.md](creator/policy.md) | Creator obligations summary |
| [creator/implementation-hooks.md](creator/implementation-hooks.md) | → matching, eligibility |
| [cross-cutting.md](cross-cutting.md) | Shared affiliate, live commerce topics |
| [risks.md](risks.md) | Platform change risks |
```

### `implementation-hooks.md` template (seller or creator)

```markdown
# Implementation Hooks: <Vendor> — <Seller / Creator>

## Feature gates
| Feature / program | Gate condition | Phase | Source |
|-------------------|---------------|-------|--------|

## Alert candidates (v1.5+)
| Policy rule | Trigger | User-facing message (VI) | Module |
|-------------|---------|--------------------------|--------|

## Matching / recommendation filters
| Platform signal | Filter / rank adjustment | Source |
|----------------|--------------------------|--------|

## ETL / sync behavior
| Platform rule | Sync adjustment | Source |
|---------------|-----------------|--------|

## API cross-references
| Platform feature / rule | API exposure | api-docs link |
|------------------------|--------------|---------------|

## data-sources.md impact
| Row / rule | Proposed change |
|------------|-----------------|
```

---

## Step 5 — Platform hooks

### 5.1 `docs/architecture/data-sources.md`

Update when features or policies constrain product behavior:

- **Substitutes table** — when a product "want" is blocked by policy or unavailable feature
- **Operational Rules** — settlement holds, health-check cadence, eligibility filters
- **Forbidden** — confirm scraping, unofficial streams, buyer PII remain blocked

### 5.2 Cross-link `api-docs`

In `implementation-hooks.md`, link platform features/rules to:

- `docs/<vendor>_api/endpoints.md` fields that expose health, limit, or program signals
- `docs/<vendor>_api/webhooks.md` events (e.g. deauthorization, violation notices)
- `docs/<vendor>_api/risks.md` technical mitigations

### 5.3 ADR candidates

Draft when platform constraints force non-obvious trade-offs:

- Alert-on-policy-violation vs silent degradation
- Regional policy config vs single global ruleset
- Webhook-driven health sync vs daily policy scrape (**scraping forbidden**)
- Seller-only vs creator-inclusive feature gating

---

## Output quality standard

A product engineer or backend engineer should be able to:

- Understand what tools and programs sellers and creators have access to
- Gate features correctly by identity (seller vs creator), tier, region, and program eligibility
- Surface the right alerts and recommended actions without re-reading Help Center
- Avoid Forbidden integrations cited in policy and `data-sources.md`
- Cross-check API-exposed signals against documented seller- and creator-facing rules

Optimize for **decision-ready knowledge**, not legal prose or marketing copy reproduction.

---

## Constraints (non-negotiable)

- Never invent thresholds, penalties, eligibility rules, or feature capabilities.
- Never scrape live Seller Center dashboards or seller/creator-specific account pages.
- Cite official source URLs on every major statement.
- Flag `REGION-VARIANT` and `DISCREPANCY` explicitly.
- Respect `docs/architecture/data-sources.md` Forbidden rows.
- Keep endpoint inventories in `api-docs`, not here.
- Keep seller and creator content in separate subdirectories; share only in `cross-cutting.md`.
