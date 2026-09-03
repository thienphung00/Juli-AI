# ADR-090: Optimize Product realignment — discount-only reprice, diagnosis first, one lever per run

**Status:** Proposed
**Date:** 2026-09-03
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [`execution_layer.md`](../product/execution_layer.md) §2 steps 5–6;
[ADR-069](069-agent-tool-registry-and-write-path.md) (the Optimize Product tool set) and
[ADR-072](072-agent-prompt-architecture.md) (its prompt, → v4).
**Does not change:** [ADR-068](068-agent-workflow-execution-boundary.md) decision 1's authority
split, [ADR-075](075-agent-approval-gate-and-security-prerequisites.md) decision 2's approval
gate and decision request, [ADR-082](082-agent-run-product-binding.md)'s bound product,
[ADR-087](087-subject-scoped-action-cards-and-card-revisions.md)'s card revisions,
[ADR-088](088-consent-pause-is-a-runner-guarantee.md)'s runner-guaranteed pause.
**Scope:** W9-A, [`PLAN.md` §14](../product/agent-workflow-execution/PLAN.md) design-order item 1.

## Context

**Juli's one working playbook writes the wrong field.** `playbooks/optimize_product.py` step 6
is `update_product_price` → `POST /product/202309/products/{id}/prices/update`, the base price.
The seller-journey report
([`seller-journeys/product.md`](../product/agent-workflow-execution/seller-journeys/product.md)
§B, §D) establishes that TikTok does not reprice that way: Price Diagnostics tiers each SKU and
reprices through **Chiết Khấu Sản Phẩm** (Product Discount, SKU-level) or **Voucher Nhà Bán
Hàng** (product-level), 30-day default, held ≥ 1 day to earn the traffic benefit. §D grades
Optimize step 6 **WRONG**. Worse than misaligned: listing policy names *"điều chỉnh hoặc thay
đổi giá đột ngột trong một khoảng thời gian ngắn"* — sudden short-window base-price change — as
a harmful behaviour, qualitatively, with no published numeric cap (grep-confirmed). Juli's only
shipped price lever is the one the platform discourages.

**TikTok already computes the diagnosis Juli re-derives.** §B lists four first-party listing
tools — Product Optimizer with diagnostic tags, the title optimizer with search-volume scores,
14 card-diagnostic recommendations, and Price Diagnostics. §D grades the playbook's six steps a
**GAP** on exactly this. The Partner API exposes two of them:
`GET /product/202405/products/diagnoses` (Product Information Issue Diagnosis) and
`POST /product/202411/products/diagnose_optimize` (Diagnose and Optimize Product), both under
scope `seller.product.optimize`. **Neither has been captured live** — they are catalog entries
in `tiktok_corpora/partner-catalog.json`, not rows in
[`contract-collection.md`](../integrations/tiktok_api/contract-collection.md), and nothing
confirms the app holds that scope. So the agent today re-derives a verdict that can contradict
the one already on the seller's screen.

**Platform locks are structurally invisible.** A Product Discount is unavailable while the SKU
sits in a campaign or Flash Deal. Juli cannot enumerate those: `Search Activities` is not
available (`execution_layer.md:289-292` — investigated, absent from the Promotion API Testing
Tool), so `GET /promotion/202309/activities/{activity_id}` reads only activities whose id Juli
already tracks, i.e. ones Juli created. A precheck can be honest about the collisions it can
see, and cannot be omniscient.

**Two more constraints from §B/§E, unguarded today.** Editing title, category, images and
description together is the fingerprint of prohibited listing repurposing (listing-guide
§3.1.7/§3.1.8); title ≥ 25 characters is grandfathered but enforced on the next edit.

## Decisions

1. **Reprice via Product Discount only.** The agent's price lever becomes a
   `create_product_discount` WRITE tool — a Promotion API activity at product/SKU level, 30-day
   default window, discount band 1–90 %, floored by the T9 fee-adjusted margin config
   ([ADR-066](066-t9-fee-adjusted-price-rule.md)). **No base-price write exists in the Optimize
   Product tool set**: `update_price` is removed from the playbook and `update_product_price`
   leaves its allowlist. The lever the platform itself uses is the lever Juli uses; keeping a
   base-price path would mean the agent's cheapest route to a price move is the one policy
   names harmful, and structural removal (ADR-068 d.4's NEVER class) is the only guard that
   survives a prompt revision. *Rejected:* a base-price fallback behind CONFIRM when the SKU is
   locked — it re-opens the harmful path exactly when the agent is most motivated to take it.

2. **Lock detection is fail-safe, not omniscient.** The precheck refuses a discount that
   collides with an activity Juli can see, and Juli can see only what it created. **The
   vendor's rejection of the discount create is the authoritative lock signal.** On rejection
   the run continues with a content lever if one has a diagnosis code behind it, and otherwise
   ends `completed` per decision 7. Designing as if the precheck were complete would encode a
   guarantee the API cannot supply; treating the vendor error as the real gate puts the
   authority where the information is. *Consequence:* the `proposed_change` shown at CONFIRM
   must state that a Product Discount counts toward the 14-day low a later flash sale has to
   beat — the seller consents to a constraint on their next promotion, not only to a price.
   *Rejected:* polling every product's activities into a local lock table — no endpoint to poll.

3. **Diagnosis first.** Playbook step order becomes **diagnosis read → SEO words → suggestions
   → one lever**. A field with no returned diagnosis code is never edited. The POST variant
   (`diagnose_optimize`) is used as a **pre-submit check on the proposed rewrite**, so the
   `proposed_change` can name which codes the change clears. The agent may say "TikTok flags…"
   only where a code was actually returned; Price Diagnostics tiers and the 14 card-diagnostic
   recommendations are **never claimed** — no API exposes them. Listing-quality tier is US-only;
   for VN the value is the codes plus the suggestions. Reading first is what stops Juli and
   Seller Center disagreeing in front of the seller, and it is the only source that makes "why
   this field" checkable rather than asserted. **First W9-A slice:** confirm the app holds
   `seller.product.optimize`, capture both endpoints on the sandbox into
   `contract-collection.md`, record the VN code list. If the scope is missing, the workflow
   degrades to Juli's own scoring with copy worded accordingly — never to borrowed authority.
   *Rejected:* keeping the SEO → suggestions → edit chain with the diagnosis as enrichment.

4. **One lever per run.** A run proposes exactly one change — one content field (title,
   description, or images) backed by a diagnosis code, **or** one Product Discount — and ends
   after that write. Four independent constraints land on the same number:
   [ADR-077](077-incremental-impact-measurement.md)'s DiD attributes impact to one mutation at a
   time; the listing-repurposing prohibition forbids the four-field bundle outright and a
   two-field bundle walks toward it; TikTok's ≥ 1-day price hold makes a second same-run price
   act meaningless; and a single named change is what a consent pause can legibly describe.
   Title edits additionally enforce ≥ 25 characters. This retires `required_steps =
   ("update_product_listing", "update_product_price")` — "did the job" becomes *one* confirmed
   write or an honest conclusion. *Rejected:* up to two content fields plus an optional discount.

5. **Single proposal.** The decision request carries one option (N = 1, the case
   [ADR-075](075-agent-approval-gate-and-security-prerequisites.md) decision 2 already covers);
   no per-lever option cap is introduced. `runner/confirmation.py`'s `_SINGLE_OPTION_ID = "1"`
   stays the only option id this workflow mints. Multi-option needs two things W9-A does not
   have: an honest comparison line per option — text variants have none for VN, where "better
   title" is not a number — and W6's option picker, which is not built. Shipping N > 1 now means
   minting ids the UI cannot render behind rationales the agent cannot ground. *Rejected:* a
   hybrid (three depths for the discount lever only, one for content) and three-from-day-one.
   Clear Excess is where N > 1 first earns its keep (`PLAN.md` design-order item 2).

6. **No repeat consent; a lapse emits a card revision through the standard path.** Optimize
   Product is **barred from Repeat consent in this version**. Every run needs a fresh approval,
   and the shipped copy carries an explicit confirm-first statement. A Product Discount is a
   30-day margin commitment that expires and reverts; pre-approving it means pre-approving a
   price the seller has not seen, in a workflow whose entire safety story is that consent
   attaches to a concrete named change. When the window ends — activity status change webhook
   (#39) → a Basis-snapshot change, the price returning to list — a **successor Action Card
   revision** is emitted through the [ADR-087](087-subject-scoped-action-cards-and-card-revisions.md)
   path. **The no-duplicate guarantee is three rules:**
   (a) emission happens *only* through the standard path, so ADR-087 decision 2's partial unique
   index — one active card per `(shop, workflow_key, subject)` — makes a duplicate structurally
   impossible rather than merely unlikely;
   (b) if an active card already exists for that product, record `suppressed_reason` and emit
   nothing;
   (c) the trigger is the **basis change**, never the impact reading — ADR-087 decision 6
   rejects outcome-triggered revisions while `impact_readings` is empty; the reading informs
   copy only.
   *Rejected:* a silent lapse with the next scoring pass re-carding the product — kept as the
   **interim** only until the event layer exists, admissible precisely because the standard
   emission path is identical either way, so nothing is built twice. Also rejected: pre-approved
   renewal.

   > This **narrows [ADR-055](055-decision-plan-review.md) d.19**, which lists `optimize_product_2`
   > as Repeat-consent *Eligible*. That eligibility was assessed against a listing-content edit;
   > the lever is now a priced, expiring promotion, and `PLAN.md`'s autonomy ladder already says
   > price setting never leaves level 0.

7. **Honest end states.** A run that changes nothing ends `completed` with
   `concluded_without_changes` ([ADR-088](088-consent-pause-is-a-runner-guarantee.md) decision 2)
   **plus a cause discriminator**:

   | Cause | Meaning |
   |---|---|
   | `no_diagnosis_codes` | The diagnosis read returned nothing to act on |
   | `price_lever_locked` | The vendor rejected the discount create (decision 2) and no content lever had a code |
   | `scope_unavailable` | `seller.product.optimize` is absent — should be prevented at card emission; if reached, degrade per decision 3 and say so |
   | `declined` | The seller declined the single option |

   Each cause carries its own seller message through the
   [ADR-070](070-agent-safe-sanitization-contract.md) banned-pattern guard — one generic "nothing
   to do" would make four different facts indistinguishable, which is the failure ADR-088
   diagnosed on `final_response`. A vendor error on the diagnosis read that survives retry stays
   a real failure on the existing terminal path. No-change runs produce no impact reading and
   count separately from failures in run quality (`CONTEXT.md`'s four-metric separation).
   *Rejected:* ending any non-writing run `failed`.

## Consequences

- **Playbook tool-set delta.** Remove `update_price` (step 6). Add `get_product_diagnosis`
  (READ/AUTO, the `202405` GET), `check_listing_rewrite` (READ/AUTO, the `202411` POST used as a
  pre-submit check), and `create_product_discount` (WRITE/CONFIRM). `update_product_listing`
  narrows to one field per call. `update_product_price` is deregistered for this workflow —
  NEVER by construction, not by policy string.
- **`TerminationPolicy` changes shape.** `required_steps` drops from two writes to "one
  confirmed write or a terminal tool call"; the ADR-088 terminal tool gains a cause argument.
- **Prompt v4** (ADR-072 — a new file, never an edit to v3): diagnosis-first ordering, discount
  vocabulary in place of price vocabulary, the one-lever rule, the confirm-first statement, and
  the 14-day-low disclosure. `prompt_sha256` moves, so golden scenarios re-capture.
- **`execution_layer.md` §2 correction.** Step 6 becomes the Promotion API discount path; step 5
  gains the title-length and bundle prerequisites. Docs fast-track lane (W9-A/R-7).
- **A sanitizer adapter for the diagnosis surface** under the ADR-070 contract: codes and
  suggestion text arrive as `vendor`-source free text — data, never instructions — capped and
  truncation-signalled.
- **Two gate tests** de-pin from `optimize_product_2` (W9-A/T-3) and re-pin to the new shape, so
  the template W9-B extracts is the realigned one.
- **Contract-collection captures**: both diagnosis endpoints and one `create_product_discount`,
  on the sandbox — whose listing must also be Product-Discount-capable (a real base price, no
  active campaign or flash sale). Owner action in Seller Center, not code.
- **Copy additions**: four cause messages, the confirm-first statement, the 14-day-low
  disclosure, and the degraded wording for a missing scope. All pass the banned-pattern guard.
- **What P15 then hardens** (W9-B): the per-workflow config template — prompt + allowlist +
  output schema — extracted from a path whose pricing mechanism is correct, so the ten W10
  workflows inherit the realignment rather than the misalignment.
- **Risk.** The two diagnosis endpoints are uncaptured. If the scope is absent, decision 3's
  degraded mode ships and decisions 4–7 hold unchanged — the one-lever rule and the end-state
  vocabulary do not depend on the diagnosis being first-party. The unverified fact is
  deliberately isolated to one decision.
