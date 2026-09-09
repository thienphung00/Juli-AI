# ADR-099: The demo computes real readings over synthetic series

**Status:** Proposed
**Date:** 2026-09-08
**Supersedes:** nothing. **Depends on:** ADR-077 (impact measurement), ADR-094 (demo surface splits)

## Context

Impact reading is a core feature, not a nice-to-have. It is the layer that answers *"did the change Juli made actually do anything"*, and it is the reason a seller would trust a second recommendation after the first.

It cannot be measured today, and the reason is structural rather than technical.

**A genuine reading needs a shop with real analytics history that we may mutate.** We have neither half in one place:

| shop | analytics rows | write credential |
|---|---|---|
| Fujiwa Vietnam Store | 8,200 | **none** — capability is `production_read` |
| SANDBOX7657274686031759124 | **0** | `sandbox_write`, 3 products, 3 approved cards |

Fujiwa has the history and cannot be written — there is no write credential for it, and the owner's 2026-08-21 standing decision rules it out regardless. The sandbox can be written and has been (two `update_product_price` executions succeeded on 2026-08-20), but has no analytics series to measure against.

Gate #1339 recorded this on 2026-09-08: Observation 3 **declined**, Observation 4 therefore unreachable, ADR-077's gate left open with that as its reason. That decision stands and this ADR does not reopen it.

**The bind that makes this urgent.** #1226 established in August that a genuine DiD reading requires mutating a real seller's live listing. So the reading waits for a real user. But a demo that ships *without* an impact layer teaches sellers that Juli does not measure its own work — and the layer that arrives later has then never been exercised by anyone.

The two existing `impact_readings` rows in production are the shape of the problem: `kind: preliminary`, `confidence: suppressed`, every numeric `None`, `fallback_reason: insufficient_candidates`. The machinery is correct and has nothing to work on.

### What already exists, and why it makes this easy

`services/impact/` is **already a pure package**. Its own docstring is explicit:

> `control_pool.select_control_pool` receives an **already-fetched** `Sequence[ControlCandidate]` … `reading.py` receives the already-resolved `confounded: bool` and **already-built daily series as plain arguments**.

The I/O — querying siblings, building series from `AnalyticsPerformanceInterval`, detecting a confounding run — deliberately lives in the beat task, outside the package. The seam this ADR needs was cut by ADR-077 and is already load-bearing.

## Decision

### 1. The demo computes real readings. Only the series are synthetic.

The demo feeds synthetic-but-real-shaped daily series into the **same** `reading.py`, `compute.py`, `control_pool.py`, `confidence.py` and `copy.py` that production will use. Every number a demo user sees is genuinely computed: `pre`, `post`, `growth`, `expected`, `incremental`, `impact_pct`, with `T` excluded, confounding honoured, floors applied, and the tier assigned by the real thresholds.

**Rejected: rendering a hardcoded `impact_pct` in the UI.** That creates a second source of truth for what a reading looks like, and ADR-094 decision 5 already names the cost — *"a hand-maintained second source drifts from the first while both suites stay green"*, the defect class behind six W3 post-merge fixes. A fabricated percentage would also be the exact thing #1339 forbids: a number presented as a measurement that measured nothing.

When real users arrive, **one thing changes**: where the series comes from. The algorithm being polished is the algorithm the demo has been exercising all along.

### 2. Synthetic provenance is a column, not a convention.

`impact_readings` gains `series_source`, an enum of `measured | synthetic`, `NOT NULL`, no default.

A synthetic reading must be **structurally incapable** of being mistaken for a measured one. `kind` and `confidence` already exist and are about the *reading*; this is about the *inputs*, which is a different claim. `control_set_json` carries `used_fallback`/`fallback_reason` and is free-form — provenance is too important to live in a JSON blob nobody queries.

**No default**, deliberately: a writer that forgets to declare provenance should fail, not silently record `measured`.

Every aggregate that reports impact — internal dashboards, the outcome chain in W8 (#1655), any future case study — filters on this column. A synthetic reading may never contribute to a claim about what Juli achieved.

### 3. The seeder must satisfy the control pool, not just the formula.

This is the part that makes the difference between a working demo and two more `suppressed` rows.

`control_pool.py` requires, for a reading to reach a real tier:

- **≥ 3 eligible sibling candidates** (`MIN_CANDIDATES`), from which the top **5** by correlation are taken (`TOP_K`)
- each sibling **active ≥ 14 days** before `T` (`MIN_ACTIVE_DAYS`)
- **mean Pearson correlation ≥ 0.2** across the selected set (`MIN_MEAN_CORRELATION`)
- pre-period volume above the **per-metric-family floor** (`VOLUME_FLOORS`)
- no second Juli run on the product inside either window

A seed of one product produces `insufficient_candidates` — which is precisely the two rows already in production. #1312's seeder is extended to produce a cohort, not a product.

### 4. The seed deliberately includes readings that refuse.

**The majority of this algorithm's logic is refusal**: fallbacks, floors, suppression, confounding. A demo that only ever shows confident readings misrepresents the product, not merely the data — and sets an expectation real shops will routinely fail to meet.

The seeded set must therefore include, at minimum:

- one reading that reaches a real tier (`cao` / `trung_binh` / `thap`)
- one `below_floor` — pre-period volume beneath the family floor
- one `suppressed` — a degenerate case such as `pre = 0` or `expected ≤ 0`

A seller who sees Juli decline to claim an effect learns something true about the product, and it is the thing that makes the confident readings worth believing.

### 5. The readiness check runs unchanged, first.

`readiness.py` (#1338) already answers *"is this measurable before the write"*. The demo runs it, and honours it. A demo that promises a reading it cannot produce is a demo that lies about the feature — the same failure as fabricating the number, arriving one step earlier.

## Rationale

*Extracted during the W6→main reconcile to satisfy `check_adr`, which requires a
`## Rationale` heading (#1853). Nothing below is new reasoning — it summarises what
this ADR already argues in the section named, which remains the fuller account.*

From **Context**: impact reading is a core feature — the layer answering *"did
the change Juli made actually do anything"* — and it cannot be measured today for
a **structural** rather than technical reason. A genuine reading needs one shop
that has both real analytics history *and* a write credential we may use, and no
single shop has both halves. Computing real readings over a synthetic series is
what lets the algorithm ship and be exercised before such a shop exists, with
`series_source` keeping the two provenances distinguishable forever after.

## Consequences

**The measurement layer gets exercised before it matters.** Every demo session runs the real control-pool selection, the real floors, the real tiers. Defects of the kind that already bit this package once — a rate metric compared against a count-calibrated floor, which silently disqualified every candidate for two mutation families — surface against synthetic data instead of against the first real seller.

**The bridge is one function, not a rewrite.** Swapping `synthetic_series_for(product)` for the existing `AnalyticsPerformanceInterval` reader is the whole migration. There is no second implementation to retire, because this ADR forbids building one.

**A cost, stated plainly.** Synthetic series are authored, and authored data drifts from reality — a demo tuned to produce pleasing readings will teach us that our thresholds are well-calibrated when they are merely well-matched to our own fixtures. Two mitigations, neither complete: seed from *shapes observed in Fujiwa's real 8,200 rows* rather than invented curves, and treat any threshold change motivated only by demo output as a red flag requiring real data.

**`series_source` is a schema change on a tenant-scoped table**, so it needs a migration, an RLS review, and a backfill decision for the two existing rows. Those two are `measured` — they were computed from real (if insufficient) Fujiwa data.

**This does not close ADR-077's gate**, and must not be read as doing so. Gate #1339's prohibition is unchanged: a `suppressed` reading may not be recorded as a reading, and a synthetic reading may not be recorded as a measurement. This ADR builds the road; the gate still needs a real shop to drive on it.

## Evidence

- `services/impact/__init__.py` — the package's own statement that it receives series as plain arguments, and that I/O belongs to the caller
- `compute.py` — ratio-form DiD, and the three suppression cases (`control_pre == 0`, `pre == 0`, `expected <= 0`)
- `windows.py` — `PRE_WINDOW_DAYS = 14`, `POST_WINDOW_DAYS = {preliminary: 7, final: 14}`, `T` excluded everywhere
- `control_pool.py` — `TOP_K = 5`, `MIN_CANDIDATES = 3`, `MIN_MEAN_CORRELATION = 0.2`, `MIN_ACTIVE_DAYS = 14`
- `confidence.py` — `TierOutcome`, `VOLUME_FLOORS` keyed per `MetricFamily`, and the rate-vs-count scar it exists to prevent
- Deployed database, 2026-09-08: Fujiwa 8,200 analytics rows and no write credential; sandbox 0 rows, `sandbox_write`, 3 products, 3 approved cards
- #1339, 2026-09-08 — Observation 3 declined, Observation 4 unreachable, ADR-077's gate open with its reason
