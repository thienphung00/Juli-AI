# ADR-103: Onboarding is a first-connect read that produces a score, three insights, and one approved card

**Status:** Proposed
**Date:** 2026-09-14
**Deciders:** grill-with-docs (Architect) with the owner
**Supersedes:** [ADR-098](098-stage-keyed-onboarding-layer.md) in full. ADR-098 assumed the connected
seller's first list is *empty* and that onboarding's job is to explain the wait honestly. The owner's
objective (2026-09-14) inverts that: the cold-start read **is** the product demo, and the score and
insights it produces are the first thing the seller sees. ADR-098's stage explainers, setup card and
feature sheet survive as decision 8 below; its d.6 (empty-list step list) is promoted from a waiting
state to the onboarding's opening act; its d.8 (browser-storage seen-state) is reversed.
**Builds on:** [ADR-094](094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md) (two doors),
[ADR-055](055-decision-plan-review.md) (card anatomy), [ADR-087](087-subject-scoped-action-cards-and-card-revisions.md)
(subject-scoped cards), [ADR-077](077-incremental-impact-measurement.md) (impact readings),
`PLAN.md` §14 (identical UX, per-case internals), `v1-workflow-spec.md` S-FR-1.
**Does not decide:** sign-in and the OAuth entry surface (still open, see ADR-098's list, unchanged);
the landing-page update; the copy itself (lands in `dictionary.md` per ADR-028 before implementation).
**Blocked by:** #1948, #1949 — see decision 10.

## Context

**The objective, as the owner stated it (2026-09-14):** a seller connects their shop, sees a
**First Connect Score** and **three insights**, and is walked to **approving and executing their
first card**. The score exists to trigger curiosity and the desire to act — it is a conversion
device, not a standing health claim. The flow is: landing → connect → cold-start read → score →
three insights → onboarding to the first approval → real impact shown.

**The binding constraint the owner set:** the three insights must use metrics the system already
derives, and **Signals → Card → Impact reading must be consistent**. That rules out a bespoke
onboarding metric and forces the insight to be something the rest of the product already produces.

**What already exists.** `services/scoring/` is the pipeline this design needs, already built:
`compute_scoring_signals` emits an `AdvisorySignal` with a `Severity` for 20 KPIs across six
domains; `KPI_WORKFLOW_KEYS` maps KPI → workflow; `rank_workflow_recommendations` ranks them;
`persist_scoring_result` writes `ActionCard` rows; `apply_emission_budget` decides which surface.
`run_action_card_refresh(session, shop_id, poll=True)` already chains poll → score → persist →
surface. Crucially, `run_daily_scoring_for_shop` makes **zero vendor calls** — it reads synced
Postgres only. The entire cold-start latency budget is the poll.

**What is measured, not assumed (Fujiwa Vietnam Store, read-only, 2026-09-14).** Of the 20 KPIs,
only a minority have data, and two of the four planned launch workflows have none at all:

| Source | State |
|---|---|
| `analytics_performance_intervals` | 8,435 rows, autoanalyzed 2026-09-13 — healthy |
| `products` | 116 rows — healthy |
| `orders` | **0 rows**, while the vendor API returns 3,581 in 90d (#1949) |
| `inventory_items` | **0 rows ever**; the fetcher sends `sku_ids`, the endpoint demands `product_ids` (#1948) |
| `returns` | 0 rows ever |

**Why "Shop Performance Score" could not be the name.** SPS *is* TikTok's Shop Performance Score,
it is in the glossary, and `integration-audit-2026-06.md:205` records it as unavailable via Partner
API (Seller Center UI only). A Juli-owned number under that name would sit beside a number the
seller reads in Seller Center that Juli cannot see. `phase-2-tiktok-prd.md` story 14 already forbids
fabricating health scores. **First Connect Score** names a moment rather than a standing claim, and
is therefore outside that prohibition.

## Decisions

1. **An insight *is* an action card.** One insight = one subject-scoped `ActionCard` (ADR-087) =
   one approval = one impact reading. The card's KPI domain is the insight's headline, so the
   seller reads three *areas* (Doanh thu, Tồn kho, Vận hành) while each is already a concrete,
   approvable card. Signals → Card → Impact consistency then holds **by construction** rather than
   through a mapping table someone must maintain. *Rejected:* an insight as a KPI domain (not
   approvable — leaves a gap the seller must cross alone); an insight as a ranked workflow
   recommendation (9 of 11 dead-end at the playbook registry with a 409).

2. **Never surface an insight whose workflow cannot execute.** Under decision 1 a rendered insight
   is a promise that the seller can act. A card for an unregistered playbook renders as approvable
   and 409s — the single worst failure available to this design. The insight set is therefore
   filtered to workflows with a registered playbook, always, with no padding to reach three.

3. **The launch set is four workflows, and it is the eligibility gate.**
   `optimize_product_2`, `process_order_5`, `clear_excess_4`, `replenish_inventory_3` — covering
   three areas and ten KPIs. `LAUNCH_WORKFLOW_KEYS` replaces `get_workflows_for_profile`.

4. **`NEW_SHOP` / `MID_LARGE_SHOP` is deleted.** All shops function identically. The distinction
   had exactly one behavioural consumer (`get_workflows_for_profile` at `recommendations.py:58`);
   no severity threshold branches on it (`thresholds.py` holds one constant, used only by the
   classifier itself), no copy branches on it, and `shop_profile` appears in no model, route,
   migration or contract. `classify_shop_profile` and the `ShopProfile` enum are removed rather
   than left classifying into a distinction nothing reads.

5. **The First Connect Score is a severity share over the launch-backed KPIs Juli could actually
   evaluate.**

   ```
   score = 100 − 100 × (2·critical + warning) / (2 × evaluated)
   evaluated = launch-backed KPIs that returned a real signal
   ```

   It is computed from the same `ScoringSignals` object that produces the insights, so the score
   and the three insights can never disagree. `unavailable` KPIs leave the denominator rather than
   counting as healthy or broken. *Rejected:* scoring on card count — it scales with catalogue size
   rather than shop health (a 500-SKU healthy shop would score worse than a 3-SKU dead one), and
   post-`emission_budget` card count is pinned at `max_active` so it barely varies.

6. **The denominator is disclosed.** The seller is told how many KPIs the score was computed over.
   Only what Juli can actually poll and compute is shown; nothing is implied about the rest.

7. **The score is a one-time snapshot, frozen at first connect.** It does not recompute. Ongoing
   progress is carried by impact readings, which measure the same KPIs the score was built from. A
   score that silently re-floats becomes a standing health claim — the thing the rename avoided.

8. **The five stage explainers, the setup card and the "what Juli does" sheet carry over from
   ADR-098** (its d.2, d.3, d.4) unchanged, and remain the walk from the third insight to the first
   approval. The impact moment remains an act record, not a screen (ADR-098 d.5).

9. **The waiting surface is a live three-step list driven by real job completion** — đọc sản phẩm →
   đọc đơn hàng → tính điểm — over a dimmed preview. A step turns done only when its job finishes;
   never a timer, never a percentage. This is ADR-098 d.6's component, promoted from a seven-day
   wait to the cold-start's opening act, and it is honest at forty seconds as well as at six
   minutes. *Rejected:* a bare progress screen with the score at the end (gives the seller nothing
   to read); revealing the score before the insights (impossible — the score is computed *from*
   the signals).

10. **The cold-start read is `products` + `orders` + `inventory_items`, and it is blocked today.**
    The ten launch-backed KPIs need no analytics fetch (`analytics_weighted_product_ctr` feeds
    `ctr`, an ADS-domain KPI outside the launch set), which is what makes a sub-minute read
    plausible at all. But **#1948 and #1949 must land first**: inventory has never written a row,
    and orders advances its watermark while persisting nothing. Until both land, this design
    renders one insight (Doanh thu, from the 116 synced products), not three. That is a
    prerequisite, not a caveat.

11. **The cold-start read fails loudly.** `maybe_poll_tiktok_data` currently resolves one
    globally-configured merchant and returns `None` for every other shop
    (`refresh.py:42-71`), so a connecting seller would be scored over an empty database with no
    error anywhere. A seller who connected and got nothing is a bug, never a quiet zero.

12. **One per-shop onboarding record, server-side.** It carries bootstrap status, the frozen First
    Connect Score with its computed-at timestamp and its denominator, and which of the five stages
    the seller has met. *This reverses ADR-098 d.8.* Browser storage is per-device, and a one-time
    per-shop snapshot cannot live there: connect on a phone, open on a laptop, and the seller gets
    a second "first connect" with a different score. It also makes ADR-098's stated measure — the
    five stage-met timestamps — actually collectable, which its own d.8 made impossible.

13. **Same layer, both doors** (ADR-098 d.7, unchanged). The demo visitor's replayed scenario and
    the connected seller's own shop are two data sources under identical code.

## Rationale

Decisions 1–2 are the load-bearing pair. The owner's consistency requirement — Signals → Card →
Impact — is satisfiable in exactly one way that a test can enforce: by making the insight the same
object as the card, so no mapping layer exists to drift. Every other definition of "insight"
introduces a translation step between what the seller is shown and what the seller can do, and it
is in that step that a card which 409s on approval becomes possible.

Decision 5 follows from the measured data rather than from taste. Card count was the owner's first
instinct and is the more intuitive metric, but the production numbers show why it fails: 116
products and 3,581 orders would generate candidate cards in proportion to catalogue size, not to
how much trouble the shop is in.

Decisions 10–11 exist because this design was grilled against the live database rather than against
the code's intent. The code path for a four-workflow, three-area onboarding is largely built; the
data beneath three of those four workflows is not there, and both reasons are silent bugs rather
than missing capability.

## Consequences

- **Backend:** `LAUNCH_WORKFLOW_KEYS` replaces `get_workflows_for_profile`; `ShopProfile` and
  `classify_shop_profile` deleted; the First Connect Score computed from `ScoringSignals`; a
  per-shop onboarding record and its read endpoint; a per-shop cold-start read path that consumes
  the connecting shop's own `SELLER_CONNECT` credential and fails loudly.
- **Blocked on:** #1948 (inventory parameter), #1949 (orders watermark). #1950 (silent-sync
  verdicts) is the structural fix that keeps them fixed.
- **UI:** the three-step read list; the score reveal; the three insight cards; ADR-098's explainer
  strips, setup card and feature sheet; the onboarding-record hook.
- **Copy:** `empty.decisions.waiting_data` retired (`dictionary.md:308`); the score, denominator,
  three-step and insight-headline strings enter `dictionary.md` first.
- **Design package:** `Flows/home/onboarding.md` is superseded — as ADR-098 already claimed, but
  its three live inbound pointers (`flows.md:41`, `Screens/home.md:5`, `EXECUTION.md:246`) were
  never updated and must be.
- **`PLAN.md` §14:** the instantiation row ADR-098 quoted but never added lands with this ADR.

## Open questions

- **Thin data (unanswered, now urgent).** With #1948/#1949 outstanding every shop is a thin-data
  shop. `orders_at_sla_risk` is the sharp case: its only guard is `if metrics is None`, which is
  dead code because `compute_all_kpis` always returns an object — so on a shop with zero orders it
  reports `severity="healthy"`, *"no orders past dispatch SLA"*, and a shop that has never sold
  anything scores **100 on one KPI**. Options grilled but not settled: floor the denominator at N
  evaluated KPIs; distinguish `no_source` (permanent) from `awaiting_data` (temporary) in
  `_unavailable_kpi` so the disclosure can say which; both. The `orders_at_sla_risk` guard is a
  genuine bug independent of onboarding.
- **The trial cohort.** Whether the five trial shops are established sellers or new ones decides
  whether the thin-data path is an edge case or the main path.
- **Score reveal.** Whether the number counts up or lands. If it counts up it must be tied to the
  real steps completing, not to a fixed duration.
- **Wave placement**, once #1948/#1949 are scheduled.
