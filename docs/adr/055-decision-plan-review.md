# ADR-055: Decision plan review — sectioned agent-proposed plan replaces the five-stage review

**Status:** Accepted
**Date:** 2026-08-05
**Deciders:** grill-with-docs (Architect)

**Supersedes:** the **Five-stage decision review** (Why → Analytics → Inputs → Preview →
Approve) recorded in CONTEXT **Seller workspace**, for `apps/demo` Decisions.
**Amends:** the CONTEXT note that the five-stage review "does not change the In Progress
sub-tab (deferred redesign)" — that redesign is no longer deferred.
**Does not change:** [ADR-023](023-four-destination-analytics-ownership.md) four-destination
IA; Decisions' exclusive ownership of the recommendation approval gate; Analytics'
ownership of KPIs and charts; **Demo dry-run execution** (Mock actions still never call
Partner write APIs); **Seller-surface copy** authority ([ADR-028](028-vietnamese-copy-dictionary-and-design-context.md)).
**Scope:** `apps/demo` mobile-web only. Native iOS/Android is explicitly out of scope for
this ADR.

## Context

The five-stage review presents every workflow's inputs as one flat form. Measured across
the ten `apps/demo` workflows, that means showing **6–11 fields** in order to collect a
median of **~3.5** genuine seller answers — and after conditionals collapse, the true ask
is frequently **one**. The remaining fields are context the agent already holds:

| Workflow | Agent already knows | Seller must decide |
|----------|--------------------|--------------------|
| prevent-refund | 7 | 2 |
| prevent-cancellation | 5 | 2 |
| prevent-return | 7 | 4 |
| process-order | 3 | 4 |
| clear-excess | 3 | 4 |
| replenish-inventory | 3 | 3 |
| optimize-product | 3 | 2 |
| create-activity / update-activity | 1–2 | 4 |
| delete-activity | 1 | 1 |

Three further defects surfaced while measuring:

- Every seller-facing field ships with an empty-string default. The agent proposes
  **nothing**, so the seller faces blanks rather than a plan to react to.
- The `analytics` stage carries no content — its body is a sentence stating that the Demo
  does not reproduce reports here, plus a link out. It is a stage that exists to say it is
  empty.
- Some fields are **post-execution** but live in the pre-approval form:
  `prevent-return.resellable_quantity` ("sau kiểm tra") and
  `replenish-inventory.received_quantity` ("sau giao"). No seller can answer them at
  approve time.

The target is a **mobile-web** surface, where a persistent assistant panel alongside the
recommendation is not affordable — the reference split-screen patterns (Gorgias, Gemini)
assume desktop width. Juli's users are also less technical than the builder audience that
node-graph tools (n8n) serve; exposing workflow internals would additionally violate
**Seller-surface copy**.

Alternatives considered:

| Option | Outcome |
|--------|---------|
| A — Keep the five-stage form, add per-field help | Cheapest; leaves the information load and the blank-field problem intact; rejected per user direction |
| B — Chat-first: collect inputs conversationally, one message at a time | Most "AI-native"; discards accepted IA, maximises copy-leak risk, and reintroduces multi-step load; rejected |
| C — Node/graph configuration surface (n8n-style) | Built for configurability by technical users; wrong audience; exposes internals; rejected |
| **D — Sectioned agent-proposed plan, progressive disclosure (chosen)** | Cognitive load scales with disagreement, not field count; the agent's reasoning becomes on-demand rather than always-on |

## Decision

1. `apps/demo` Decisions replaces the five-stage review with a **decision plan review**:
   the agent presents a proposed plan the seller traverses **section by section**, in the
   manner of a planning-mode proposal rather than a form.
2. The agent **pre-commits a proposed value for every field**, including fields the seller
   is expected to decide. There is no blank-by-default field and no reserved class of
   fields the agent declines to propose.
3. Each section offers a **list of recommended options**, plus the ability to supply a
   **custom input**, plus the ability to **ask a follow-up before deciding**. Asking is a
   deliberation step available at the point of choice — not a separate surface.
   **MVP/Demo constraint:** there is **no LLM layer**. The plan review is **rule-based**,
   and every string is **pre-authored**. "Ask a follow-up" therefore means revealing
   authored copy, **not** a conversational exchange — nothing can answer a free-form
   question. Copy is kept minimal by design; an LLM-backed ask is out of scope here.
4. Presentation is **progressive disclosure**: sections rest folded, showing the proposed
   outcome only. Reasoning, evidence, and alternatives appear on expansion. The AI
   recommendation explains **when asked**; it does not narrate by default.
5. The optimisation target is **minimal cognitive load and minimal time to value**. A
   seller who agrees with the plan should be able to approve without expanding anything.
6. Approval is followed by an **agent-working acknowledgement → progress → repeat-consent**
   sequence. The seller is asked whether the agent may repeat this workflow in future only
   **after** the work completes, never bundled into the initial approval.
7. Because the surface is mobile-web, the assistant and the recommendation **never occupy
   the screen simultaneously**. The ask affordance lives inside the section it concerns.
8. The section spine is **uniform and replicated** across workflows — **Situation →
   Decision → Details** — so a seller learns one pattern once. Workflows that genuinely
   differ are handled as **named edge cases** (item 10), never by authoring a bespoke
   section set per workflow.
   | Section | Contents | Behaviour |
   |---------|----------|-----------|
   | **Situation** | Agent-known, read-only context — already marked `editable: false` in the field data | Collapsed into the header, not traversed; holds zero decisions. Evidence and the Analytics link live behind its expansion |
   | **Decision** | The branch discriminator and any other decision-grade field | Carries the recommended options. Holds **1–2** items; `process-order` legitimately has two (`order_priority`, `shipping_type`) |
   | **Details** | Branch-gated execution specifics | Only the chosen branch's fields render. Absent entirely when empty (e.g. `delete-activity`) — renders as nothing, never as an empty stub |
9. **Caveat fields.** `risks` and `knownLimits` are distinct and are treated differently.
   `risks` renders **unfolded** as one line in the Decision section — measured across all
   eleven fixtures it is already a single short sentence, so it fits without truncation.
   Two of them do real safety work and must never be folded: `clear_excess_4`
   ("không thể hoàn tác") and `prevent_return_8b` ("chỉ nhập lại kho sau khi có kết quả
   kiểm tra thực tế").
10. **`knownLimits` is decomposed into typed classes.** As one concatenated string the
    classes cannot be rendered differently. They are:
    | Class | Meaning | Count | Demo/MVP treatment |
    |-------|---------|-------|--------------------|
    | **A** Threshold undefined | "Juli won't invent the number" | 11/11 | **Hidden.** True of every workflow, so it carries no discriminating information |
    | **B** FBT unsupported | capability boundary by fulfilment model | 7/11 | **Hidden in Demo.** The Demo has no shop profile and is uniformly **FBS** by construction, so "FBT unsupported" is vacuously true for every Demo seller. The typed field carries forward so **3.5-C** multi-tenant Sign-in can render it as a real applicability check |
    | **C** Feature unavailable | a genuine functional gap | 3/11 | **Shown** inside the reasoning expansion — the promotions trio's "promotion search unavailable" |
    | **D** Reassurance | "Juli won't act without you" | 3/11 | **Moved out of limits** into the Decision section as a trust line. It is a selling point, not a limitation |
11. **The expansion is a reasoning container, not a limits container.** After hiding
    classes A and B, `knownLimits` is empty for five of eleven workflows, so an expansion
    built around it would open onto nothing. `reasoning` is populated for all eleven and
    measures **74–113 characters** — one short sentence in seller language, available
    without an LLM. It is the expansion's primary content; Class C gap notices render
    alongside it when present.
12. **Un-proposable fields (MVP).** Where no proposal can exist — `create_hero_product_1`'s
   `main_images` and `supporting_file`, which are file uploads — the field is presented as
   a plain **upload** in a visible "needs you" section. The agent does not propose
   candidate imagery and does not generate placeholder assets. This is a stated exception
   to item 2, not a silent blank: `create_hero_product_1` cannot be a one-tap approval,
   and the plan review must say so rather than imply otherwise.

13. **Card structure — summarise, do not enumerate.** Sections present a **summary row with
    an edit affordance** rather than a collapsed drawer of raw fields (Monzo pattern):
    `prevent_return_8b`'s seven context fields render as one row
    ("Đơn hàng #ORD-44102 · 5 thông tin khác ›"), not a seven-field expansion. Expanding
    **adds** detail and keeps the summary visible; it never replaces it. Disclosure labels
    are written as **questions** ("Vì sao Juli đề xuất điều này"), not nouns.
14. **Scope cuts for this implementation.** The `risks` display (item 9) and the
    decision-options editing interaction (item 3) are **out of scope for this card**.
    Context fields are kept **minimal**. The card presents Juli's proposal, minimal
    context, the impact metric, and one primary action. Item 9's `risks` treatment stands
    as the design of record for when that work lands; it is deferred, not reversed.
15. **Impact metric.** Every workflow is already tied to one Main KPI via
    `analyticsMetricKey`, mapping onto the [ADR-049](049-demo-analytics-main-kpi-override.md)
    five: **CTOR** (`optimize_product_2`, `create_activity_7a`, `update_activity_7c`,
    `delete_activity_7b`), **GMV** (`prevent_cancellation_8a`, `prevent_return_8b`,
    `prevent_refund_8c`, `replenish_inventory_3`, `create_hero_product_1`), **AOV**
    (`clear_excess_4`), **Cancellation rate** (`process_order_5`). **LIVE hours is tied to
    no workflow.** The impact block is the card's centre of gravity and shows the tied
    KPI's **real current value and trend** from `gold.kpi_envelopes`, plus a **directional
    goal** — never a projected magnitude.
16. **No projected impact magnitude.** `expectedImpactLabel` is `"—"` for 8 of 11
    workflows, and the 3 populated ones are inconsistently typed (two VND amounts, one
    order count). Authoring a projection is barred on independent grounds: ADR-011 and
    `docs/ml/ml_layer.md` make the ML layer **display-grade only**;
    [ADR-032](032-fujiwa-t1-gmv-experiment-scope.md) states *"We will not… claim experiment
    ΔGMV as Juli ROI"*; **Mediated Juli GMV impact** is deferred and uncalibrated; and the
    fixtures' own class-A copy — *"Juli không tự suy diễn con số này"* — is that policy
    already surfacing to sellers. There is no per-workflow revenue model, shipped or
    planned for MVP.
17. **The impact block has one state.** It is **pre-approval only** and does not change
    after approval; the card carries it forward unchanged into In Progress. In Mock mode
    executions are **dry-run**, so no effect exists to observe — any subsequent movement in
    the reference shop's KPI comes from Fujiwa's real trading, and presenting it as the
    seller's achievement would be a fabricated causal claim. Accepted cost: **the card
    never closes the loop**, so a seller cannot see that Juli helped. This is a real
    product weakness, accepted because a fabricated loop is worse than an absent one. The
    loop properly closes at **3.5-C**, where real writes make before/after meaningful.

## Consequences

- The `analytics` stage is removed as a stage; the link to Analytics survives inside the
  relevant section's expansion.
- Post-execution fields move out of the approval flow. They belong to a later moment in
  the execution lifecycle and must not be collected at approve time.
- Branch discriminators (`process-order.shipping_type`, `prevent-return.seller_decision`)
  gate which sections are shown at all, rather than rendering every branch's fields flat.
- Pre-committing judgment-bound fields carries a **rubber-stamping risk** — a seller may
  accept a consequential proposal without considering it. This is an accepted trade-off:
  the mitigation is the ask-before-deciding affordance in item 3, not a blank field.
- The In Progress sub-tab redesign is no longer deferred; items 6 and 7 land there.
- `ReviewInputFieldDescriptor` (`packages/contracts/src/review.ts`) is
  `{key, label, prefillValue, required, editable}` — all strings, no field kind and **no
  option list**. The per-section "list of recommended options" is not expressible in the
  current contract; it must gain a field kind (option list, upload, free text) before this
  design can be built.
- The `ReviewStage` union (`why | analytics | inputs | preview | approve`) no longer
  matches the section spine and is superseded by it.
- The **FBT intake variants** (`prevent_return_8b_fbt`, `process_order_5b`,
  `replenish_inventory_3b`) are **scaffold-only and deliberately non-executable** — tests
  assert their review stages are `[]` and that `startExecution` throws. They are not a
  parallel reviewable path; the constraint reaches sellers through `knownLimits` class B
  instead.
- `sanitizeSellerReviewText` already strips the worst internals from seller copy —
  backticked keys, `Unresolved/Unfilled`, `activity_id`, `webhook`, and FBS/FBT. Residual
  tokens it does **not** catch and which still reach sellers: **"executor"**,
  **"Create Packages"**, **"Deactivate"**, **"parity"**, **"catalog"**, and the English
  **"Activity"** in `update_activity_7c` / `delete_activity_7b` reasoning. These should be
  fixed at the fixture, not by growing the sanitizer.
- **Ratio KPIs are stored pre-divided and cannot be maintained incrementally.**
  `gold.kpi_envelopes` serves each KPI as a series of scalar points (`{v: number}`), with
  CTOR and cancellation rate already divided into percentages. Incremental precompute
  requires `ON CONFLICT`-mergeable aggregates, so ratios must be persisted as
  **numerator/denominator pairs and divided at serve time**. This affects **5 of 11**
  impact blocks (four CTOR, one cancellation rate). It does **not** block this card — a
  pre-divided value renders correctly today — but it blocks ever maintaining those five
  incrementally, and it constrains the [ADR-046](046-cdp-medallion-physical-model.md)
  `payload.kpis` contract.
- **LIVE hours has no workflow tied to it** — the one Main KPI with no Decision behind it.
  Left unmapped; no workflow should be retrofitted onto it to fill the gap.
- The frontend and impact-framing evidence base is **thin by measurement, not by
  omission**: a dedicated research pass returned zero surviving claims for dataviz UX,
  honest-impact framing, and sequencing, while returning strong primary-source evidence for
  the backend and model layers. Items 13–17 are therefore **engineering judgement**, not
  evidence-backed, and should be revisited if that research is run. Specifically unknown:
  whether users read before/after deltas as causal regardless of disclaimer wording.
- The **traversal model** (scroll versus sequential) remains open and will be recorded as
  an amendment.
- `create_hero_product_1` is additionally the only workflow whose stages are built inline
  in `reviews.ts` rather than in a `lib/workflows/<name>/` module; it should be brought
  into line when this lands.
