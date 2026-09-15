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
**Blocked by (full chain, corrected 2026-09-15):** data — #1966 (webhook grant), #1948 (inventory parameter), #1949 (poll never scheduled), #1967 (poll loses the shop GUC), #1968 (dedup ledger blocks re-ingest), #1969 (backfill cap / hang / no progress), #1365 (per-shop credentials); entry — #1970 (OAuth-start route, `/v1` proxy), #1971 (consent screen pages), #1972/#1973 (contact capture); execution — **W10-A/B/C (#1624, #1625, #1626)**, without which three of the four launch workflows have no playbook; scoring — #1960, #1961.

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

9. **The waiting surface is layer 0 of `/onboarding` — a live three-step list driven by real job completion** — đọc sản phẩm →
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

## Decisions added 2026-09-15 (owner grill)

14. **Onboarding has its own route, `/onboarding`, with three layers over the read.** Layer 0 is the
    three-step cold-start read (d.9); then **Big Reveal** (the First Connect Score), **3 Insights**,
    and **Next Steps**. *This reverses ADR-098's "adds no surface of its own", which ADR-103
    originally inherited.* That constraint was never required: **S-FR-1 binds workflows** — "No
    **workflow** adds a surface beyond these seven" — and onboarding is not a workflow. What it must
    not add is a *workflow* surface: a second card list, a second plan review, a second approval.

15. **Next Steps is a tutorial that hands off to the real plan review, and `/onboarding` never
    renders an approve control.** The button opens the **top insight**'s actual card at
    `/decisions/recommendations/[id]`, where ADR-098's stage explainer anchors. An embedded live card
    would create a second path to run creation, which **S-FR-2** forbids ("Approve is run creation.
    No other path creates a run."). *Rejected:* a static illustrated walkthrough — ADR-098 already
    rejected teaching from pictures. **`/onboarding` is reachable once per shop**; a return visit
    lands on `/decisions`, enforced by the onboarding record (d.12).

16. **The fifth stage closes on the workflow's own measure, whatever kind it is.** The four launch
    workflows measure differently by design — Optimize Product and Clear Excess produce ADR-077
    impact readings; Process Order produces `shipped ÷ due`; **Replenish produces no impact reading
    at all** (ADR-093 d.4: "ADR-077's reader is not invoked for it"). Closing the stage only on an
    impact reading would mean a seller whose first card is Replenish never completes onboarding. The
    act record carries whichever measure the workflow produces, which keeps the layer
    workflow-agnostic. *Consequence:* time-to-close varies — immediate for Process Order, ~7 days for
    the other three.

17. **Entry is Google first, then TikTok** (ADR-094 d.2 confirmed). Sign-in provisions the `users`
    row (#1906, already landed); an authenticated OAuth-start route mints a state carrying the
    seller's id so the callback binds the shop to the real user rather than falling back to
    `_app_review_user_id()`. The demo host reaches the API through a **same-origin `/v1` proxy**, not
    cross-origin CORS. *Rejected:* TikTok as the identity (discards the Supabase JWT substrate and
    #1906); TikTok-first with a later Google claim (needs a claim mechanism that does not exist, and
    mis-binding a shop is hard to unwind once real sellers exist).

18. **Contact is captured on two channels at two moments.** The verified Google **email** is read
    from the JWT at first sighting — silent, no screen. **Zalo/phone is asked once during layer 0**,
    while the read runs, before the Big Reveal: the seller is already waiting, so the ask spends dead
    time rather than gating the value moment. Copy must be true at that moment — no run exists yet,
    so the run-completion framing belongs later. Today neither channel is captured and a **fabricated
    `+849` number** is written instead (#1972), so this is a correction, not an addition.

19. **Two thresholds, a count-up, and a recorded-not-integrated phone number.** Settling ADR-103's
    three open questions (owner, 2026-09-15).

    **a. The thin-data floor is two thresholds, not one.** "No insights" has two causes that must
    never share a screen: a **healthy shop** (enough evaluated, nothing wrong — a good outcome) and a
    **thin shop** (Juli cannot see enough to say). Therefore: **insights render whenever at least one
    exists** — structural, because Next Steps must have a card to hand off to; **the score renders at
    three or more evaluated launch-backed KPIs**; below three, **no number at all** and a distinct
    state naming what is still missing. That state depends on #1961's `awaiting_data` (temporary,
    disclosed — "4 chỉ số nữa sẽ có khi shop có thêm đơn hàng") versus `no_source` (permanent,
    silent). *Rejected:* a single floor, which cannot distinguish the two causes; always revealing,
    which prints a score computed from one KPI on the one screen that must be credible.

    **b. The score counts up, and lands under reduced motion.** ~700–900 ms, with the three insights
    staggering in behind it. A count-up animates a **known final value** — a transition, like a fade.
    That is categorically different from the fake progress ADR-098 rejected, which lies about
    *state*. Every entry needs its `prefers-reduced-motion` alternative asserted, per W6's motion
    table.

    **c. Contact: email is the channel, phone is a record, and no transport ships at launch.**
    Google's ID token carries `email`, `email_verified` **and `name`**, so `users.email` and
    `users.display_name` both populate silently at first sighting and **the form asks exactly one
    field: phone** — once, at layer 0, skippable (d.18). Phone is **recorded for human 1:1 outreach,
    never integrated**: no Zalo OA, no SMS, no adapter. **No email transport ships at launch** —
    `services/alerts/` is dormant (nothing outside it calls the engine), its `ChannelAdapter`
    Protocol is push-shaped (`send(alert, *, device_token)`), and W9-A already defers push/email/Zalo
    transports. This is affordable because **the fifth stage closes on the in-app act record**
    (d.16, W9-D notification centre), never on a message: email is re-engagement, not the mechanism.
    With five trial sellers a hand-written email *is* the 1:1 support being offered.
    *Consequence, accepted:* a seller who closes the tab learns nothing until they return. The first
    transport is an `EmailAdapter` against the existing Protocol, with `device_token` widened to
    `destination`, when seller count outgrows hand-sending.

20. **One state, one gate: three insights or `/decisions`.** Owner decision, 2026-09-15.
    **Supersedes d.19a in full** — the two thresholds are withdrawn.

    **The gate.** `/onboarding` renders **only** when the shop has **three surfaced insights**.
    Anything less and the seller goes to `/decisions`, which already has an empty state
    (`recommendations-panel.tsx:185-196`), and **the onboarding record is left unspent** so the flow
    fires on a later visit once the shop does have three. The gate is therefore evaluated on every
    entry until it opens once, not once and discarded. Three is exact, not a floor: the emission
    budget's `max_active` is the selector (d.9 of ADR-098's lineage; `apply_emission_budget`), set to
    three, so the CTA's "3" is a literal the gate guarantees rather than a count rendered from data.

    **What this deletes.** The thin-shop screen, the healthy-shop screen, and the
    `awaiting_data` / `no_source` reason-kind split *from the UI critical path* — that split existed
    only to write the thin screen's copy. Three designed, built and tested screens become one; two
    thresholds become one condition. The denominator disclosure (d.6) is unaffected: it is a plain
    count of evaluated KPIs and is accurate whatever they are.

    **Why gating beats branching.** `/onboarding` is a once-per-shop reveal (d.15). A reveal that
    cannot reveal anything worth revealing should not be spent — and a score computed from one or two
    KPIs would be printed on the single screen that has to be credible. Branching solves that with
    three degradations that each have to be designed and defended; gating solves it with one
    comparison and an already-built fallback. *Rejected:* rendering a variable count ("Xem 1 việc cần
    làm"), which keeps one screen but breaks the three-insight promise the landing page makes;
    rendering a score with no insights, which leaves Next Steps with nothing to hand off to (d.15).

    **What the gate waits on — and what it does not.** Three **insights** need
    **#1701** (W9-A/P-SHARED-1, subject-scoped cards) plus the data chain. Three **areas** need
    W10-A/B/C, because an area is a workflow. These are different waits, and this ADR conflated them
    until 2026-09-15 — see the correction below. Pre-W10 the three insights will usually share one
    area, all headlined Doanh thu; the headline is per card, so the render is unchanged and only the
    landing copy differs ("3 việc cần làm" rather than "3 khu vực").

## Corrections to this ADR's own analysis (2026-09-15)

- **`METRIC_MAP` covering only product mutations is by design, not a gap.** ADR-091 reuses ADR-077's
  reader through the price family; ADR-092 and ADR-093 define their own non-revenue measures. The
  real gap was d.8's assumption that every workflow yields an impact reading — corrected by d.16.
- **The launch set's true blocker is the playbook registry, not the data.** `services/agent/playbooks/`
  contains exactly one registered playbook, `optimize_product_2`. d.2 forbids surfacing an insight
  whose workflow cannot execute, so the three-area structure depends on W10-A/B/C landing. The
  original *Blocked by* line named only #1948/#1949 and was wrong.
- **A1 (users-row provisioning) was never missing** — #1906 landed it.
- **Three insights were said to require three playbooks. They do not.** ADR-087 d.2 is *one live card
  per **subject** per workflow* — a concurrency rule that stops two runs writing the same product,
  not a cap on card supply. What was mistaken for the rule is today's pre-P0-2 degradation, which
  keys cards on `(shop, workflow_key)` with **no subject**; #1701 re-keys the active index to
  `(shop_id, workflow_key, subject_type, subject_ref)`, after which Optimize Product alone yields one
  card per product. Three insights therefore gate on **W9-A**, not W10 — a full wave earlier, and the
  largest item that was on this layer's runway.

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
