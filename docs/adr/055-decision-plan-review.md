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
9. **Un-proposable fields (MVP).** Where no proposal can exist — `create_hero_product_1`'s
   `main_images` and `supporting_file`, which are file uploads — the field is presented as
   a plain **upload** in a visible "needs you" section. The agent does not propose
   candidate imagery and does not generate placeholder assets. This is a stated exception
   to item 2, not a silent blank: `create_hero_product_1` cannot be a one-tap approval,
   and the plan review must say so rather than imply otherwise.

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
- Remaining edge cases still open at time of writing: **FBT intake variants**
  (`prevent_return_8b_fbt`, `process_order_5b`, `replenish_inventory_3b` — same intent,
  different fulfilment constraints, and `Seller-surface copy` bans FBT/FBS badges in
  seller UI) and the **traversal model** (scroll versus sequential). Both will be recorded
  as amendments.
- `create_hero_product_1` is additionally the only workflow whose stages are built inline
  in `reviews.ts` rather than in a `lib/workflows/<name>/` module; it should be brought
  into line when this lands.
