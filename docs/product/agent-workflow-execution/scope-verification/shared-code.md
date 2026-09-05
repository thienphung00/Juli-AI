# v1 workflow spec — shared-code scope verification (read-only scout)

Verdict up front: **§6 item 1 is ~15% built, items 2, 3 and 4 are 0% built.** Nothing named
in §6 exists as a producer today except `suppressed_reason` (which predates ADR-087 and means
something else). Every one of the four v1 workflows blocks on at least two absent mechanisms.

---

## 1. `workflow_key` on runs / playbook resolution / reaper policy

| Spec assumption | Exists? | Gap | Smallest producer | Blocks |
|---|---|---|---|---|
| `workflow_runs.workflow_key` column | **ABSENT.** Model `models.py:573-614` has no such column; latest migration is `049_*` (+`053_*`); the only `workflow_key` columns are `action_cards` (014), `decision_emission_ledger` (027), `demo_execution_records` (028) | A run cannot say which workflow it is | Additive migration + `Mapped[str]` on `WorkflowRun`, written by `approval.py` from `card.workflow_key` | all 4 |
| `approval.py` resolves the playbook from the card | **WRONG BY DESIGN today.** `approval.py:173-187`: "Every run this transaction creates runs that one playbook, **regardless of the approved card's own `workflow_key`**" — it hardcodes `OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key` | Approving a `clear_excess_4` card runs the Optimize Product prompt | `PLAYBOOKS_BY_KEY` registry in `playbooks/__init__.py` (today it exports one constant, `playbooks/__init__.py:32-38`) + lookup in `approval.py` | all 4 |
| Reaper reads a per-workflow termination policy | **Partially.** `workers/tasks/reaper.py:114` `_DEFAULT_TERMINATION_POLICY = OPTIMIZE_PRODUCT_TERMINATION_POLICY`; `reap_workflow_runs(..., policy=)` is injectable (`reaper.py:478-506`) but nothing at call site passes a per-run policy | One global 4 h / 300 s pair for every workflow | Resolve policy per run from the run's `workflow_key` inside `_reap_*`; the injection seam already exists | Clear Excess, Replenish |

`TerminationPolicy` (`playbooks/base.py:38-63`) already carries `wall_clock_timeout_s`,
`approval_timeout_h`, `required_steps`, `terminal_tools` — it is the right home for a
`waiting_external` timeout field; no new type is needed.

## 2. Polymorphic bound subject / ADR-087

| Spec assumption | Exists? | Gap | Smallest producer | Blocks |
|---|---|---|---|---|
| `product_id` nullable | **NO** — `models.py:577` `nullable=False`, FK `products.id`. `approval.py:226-229` derives it at approval from `get_highest_revenue_product`, and raises `NoProductsForShop` rather than insert NULL (`approval.py:118-121`) | Process Order (subject = dispatch window) cannot create a run at all | Migration: `product_id` nullable + `subject_type`/`subject_ref` columns; rewrite the index | Process Order (hard block) |
| Active-run index on `(shop, workflow_key, subject)` | **ABSENT** — index is `uq_workflow_runs_active_shop_product` on `(shop_id, product_id)` where status in queued/running/waiting_approval (`models.py:619-625`) | Two different workflows on the same product collide as `concurrency_conflict`. Optimize Product + Clear Excess on one SKU is structurally impossible | Same migration | Optimize Product ∩ Clear Excess ∩ Replenish |
| ADR-087 subject-scoped cards merged | **NO — ADR-087 is `Status: Proposed`** (`docs/adr/087-*.md:3`). Zero hits for `subject_type`, `subject_id`, `supersedes_card_id` anywhere in `backend/src` or `tests`. `action_cards` identity is still `UniqueConstraint(shop_id, workflow_key)` = `uq_action_cards_shop_workflow` (`models.py:958-962`) | S-FR-10 ("subject-scoped, one active card per subject per workflow, revisions only on a basis change") describes a schema that does not exist | Migration adding `subject_type`/`subject_id`/`revision`/`supersedes_card_id` + swap the unique constraint | all 4 (S-FR-10) |
| `suppressed_reason` with a named reason | **EXISTS but different concept** — `models.py:928`, migration 027, vocabulary is `active_cap` / `cooldown` / `weekly_novelty_cap` (`services/action_cards/emission_budget.py:31-50`) — an emission-budget field, not ADR-087 suppression | Spec's "suppression with a named reason" will silently reuse the wrong vocabulary | Extend the vocabulary deliberately, or a distinct column | S-FR-10 |

## 3. Tool dispatcher

| Spec assumption | Exists? | Gap | Smallest producer | Blocks |
|---|---|---|---|---|
| Domain-registered dispatcher | **ABSENT.** `runner/tool_executor.py:261-317` is a literal if/elif over three module-level dicts: `TERMINAL_TOOL_HANDLERS`, `PRODUCT_READ_TOOL_HANDLERS`, `PRODUCT_WRITE_TOOL_HANDLERS`, all imported from `tools/product.py`/`product_write.py`/`terminal.py`. The class is `ProductToolExecutor` and hard-binds `self._product_id` into every `ProductToolContext` (`:262-269`) | An order/inventory tool has nowhere to live. `ToolExecutor` **is** already a Protocol (`tool_executor.py:143-158`) — that is the seam | A `DOMAIN_HANDLERS: dict[str, Mapping[str, Handler]]` + a domain field on `ToolSpec` (or on the playbook step), and a subject-generic `ToolContext` | Clear Excess, Process Order, Replenish |
| `ToolSpec` carries policy/classification | **YES** — `tools/registry.py:57-95`: `name, description, input_model, output_model, classification (READ/WRITE), policy (AUTO/CONFIRM), timeout_seconds`. `ToolRegistry` (`:108-125`) is explicit-registration, no decorators | No `domain` field; no per-tool reaper/consent kind | one additive frozen-dataclass field | item 3 |
| Registering a new WRITE-CONFIRM tool reaches `runner/core.py` | Path is: `ToolSpec` → `register_product_write_tools` → handler in `PRODUCT_WRITE_TOOL_HANDLERS` → playbook step (`playbooks/optimize_product.py:76-155`, validated at import by `validate_playbook_tools`, `base.py:155-172`) → `_build_registry()` (`optimize_product.py:142-151`) → prompt (`prompts/composer.py:103-118` `_WORKFLOW_BINDINGS`). **Every one of the five is optimize-product-specific.** | Five parallel edits per new tool, all named `product_*` | — | all 4 |

## 4. Run states / resume

| Spec assumption | Exists? | Gap |
|---|---|---|
| `waiting_external` state | **ABSENT — zero hits repo-wide.** `WorkflowRunStatus` has exactly 7 members (`services/agent/status.py`), pinned by a DB CHECK (`models.py:627-631`) **and** by `STOP_REASON_TO_STATUS` totality tests (`tests/unit/test_workflow_run_status_mapping.py`) **and** by `WORKFLOW_RUN_STATUSES` in `packages/contracts/src/agent-events.ts:92` | Adding it is a 4-place change: enum, CHECK constraint migration, TS union, mapping test. Blocks **Clear Excess (CE-FR-6) and Replenish (RI-FR-4)** |
| `stop_reason` vocabulary | 16 members incl. `concluded_without_changes`, `required_steps_unfulfilled`. **None** of the spec's end-state causes exist: no `goal_met`, `expired_stock_remaining`, `seller_modified`, `nothing_clean`, `shipped_subset`, `price_lever_locked`, `no_diagnosis_codes` | ~20 new causes across the 4 workflows. `String(32)` is the ceiling — `expired_stock_remaining` (23) and `not_received_by_needed_date` (27) fit; check any longer name |
| Per-workflow reaper policy | See item 1 — injection seam exists, resolution does not | S-NFR-6 ("a suspended run has its own reaper policy, never `waiting_approval`'s") is unimplementable until both land |
| `resume_agent_workflow` triggers | **Exactly one caller**: `api/routes/agent_runs.py:266` via `_enqueue_resume_agent_workflow(run_id, approved=bool)` (`:107-110`). No webhook path, no beat path, no timer path | A webhook-driven or expiry-driven resume has **no producer at all**. Blocks Clear Excess (goal-met resume) and Replenish (both reports) |

## 5. Confirmation kinds

`run_confirmations` (`models.py:689-738`, migration 039): `workflow_run_id, tool_call_id,
options (JSON), status, selected_option_id, expires_at`. **`params_sha` is not a column** — it
lives inside each `options[]` entry. **There is no `kind` column.** The wire shape is
`ConfirmationDecisionRequest {decision, option_id}` only (`agent_runs.py:205-207`).

**No path exists where params are seller-supplied.** `services/agent_runs/confirmations.py:230`
computes `expected_params_sha = compute_params_sha(pending_state["arguments"])` — the model's
own stored tool-call arguments — and rejects on mismatch (`:231`, `ERROR_PARAMS_SHA_MISMATCH`).
A seller-supplied value would have to be hashed *before* the run holds it, which inverts the
current direction. **No "report" concept exists anywhere** (only `pending_image_bytes`, a
seller-supplied *file* staged in run context, `tools/product.py:117`). §6 item 3 is
0% built and blocks **Replenish RI-FR-4, which is v1's only Replenish write**.

## 6. Card producers

Scoring → `persist_scoring_result` → `ActionCardsRepo.upsert` (`services/action_cards/persist.py:139-224`)
→ `apply_emission_budget` (`emission_budget.py:139`). Manual path: `POST /v1/action-cards/refresh`
(`api/routes/action_cards.py:90-125`) → cooldown gate → `enqueue_action_card_refresh` →
`juli_backend.refresh_action_cards` Celery task (`workers/tasks/action_card_refresh.py:50`).
**There is no scheduled card producer** — `refresh_action_cards` does not appear in
`beat_schedule` (`workers/celery_app.py:40-92`); the only trigger is a seller tap. §6 item 4
("scheduled card producers per window / per risk signal") is **0% built** and blocks
**Process Order PO-FR-2 (two scheduled runs a day)** and **Replenish RI-FR-1**.
The `workflow_key` list is `MID_LARGE_WORKFLOW_KEYS` / `NEW_SHOP_WORKFLOW_KEYS`
(`services/scoring/kpi_catalog.py:57-81`) — all 11 keys, including `clear_excess_4`,
`replenish_inventory_3`, `process_order_5`, already present with Vietnamese display names.
**A card cannot be emitted for a non-product subject**: the card row has no subject at all,
and the subject is invented at approval from `get_highest_revenue_product` (`approval.py:229`).

## 7. Notifications

`services/alerts/` exists: `FcmAdapter` (`channels/fcm.py:20`), `ZaloOaAdapter`,
`deliver_alert` (`delivery.py`), `evaluate_rules` (`engine.py`). **It has zero callers outside
its own package** (grep for `deliver_alert`/`evaluate_rules`/`FcmAdapter(` outside
`services/alerts` returns nothing) and `FcmAdapter._deliver` is a **stub that logs
`fcm_send_stub`** (`channels/fcm.py:65-80`). There is **no device-token store** — no column, no
route; `device_token` is only a function parameter. iOS registers for remote notifications and
routes them (`ios/App/Notifications/JuliAIAppDelegate.swift:12-19`,
`AppNotificationRouter.handleNotification`) but **never sends the APNs token to the backend**.
No email/SendGrid/Resend/APNs anywhere. **PO-FR-8 ("one push 2 h before the earliest deadline")
and CE-FR-6 ("notifies") have no producer and no transport.**

## 8. Webhooks

`PHASE2_CATALOG` (`services/tiktok/webhook_catalog.py:35+`) maps catalog ids →
`workflow_keys`. Of the eight asked about: **#1 ORDER_STATUS_CHANGE** (`:36`, confirmed),
**#3 RECIPIENT_ADDRESS_UPDATE** (`:50`, confirmed), **#4 PACKAGE_UPDATE** (`:57`, confirmed),
**#11 CANCELLATION_STATUS_CHANGE** (`:86`, `confirmed=False`),
**#27 INVENTORY_STATUS_CHANGE** (`:118`, `confirmed=False`),
**#39 ACTIVITY_STATUS_CHANGE** (`:134`, confirmed), **#68 INVENTORY_CHANGED** (`:179`,
confirmed) are all present. **#63 is absent from the catalog** (jumps 58 → 64).
Handling stops at persistence: `DurableWebhookHandler.on_catalog_event`
(`services/tiktok/webhook_handlers.py:42-75`) writes a `workflow_webhook_signals` row with
`intent` ∈ {`pause_automation`, `re_auth_required`, `workflow_gate`}. **No agent-run code reads
that table** — the only other references are RLS/tenant-scope lists (`tenant_scoped_tables.py:39`,
`045_rls_policies.py:62`) and the migration. Consumer-without-producer, inverted: the signal
producer ships, the consumer does not. **CE-FR-6's "on inventory webhook available ≤ goal"
has a durable row and nothing that reads it.**

## 9. Deadline / scheduling / ADR-089

`beat_schedule` (`celery_app.py:40-92`) has 6 entries: `mock-analytics-hourly-reconcile`,
`cdp-batch-staggered-reconcile`, `analytics-backfill-topup` (2:00), `daily-impact-reader`
(3:00), `reap-abandoned-workflow-runs` (*/5), `credential-refresh-beat` (*/30).
**No per-shop scheduled task, no card-producing task, no dispatch-window task.**
ADR-089 `with_shop_scope` status per beat task: reaper ✅ (`reaper.py:398,452`),
credential_refresh_beat ✅ (`:139`), analytics_backfill_topup ✅ (`:131`),
mock_analytics_reconcile ✅ (`:224`), impact_reader ✅ (via `workers/impact_reader/pipeline.py:253`),
**cdp_batch_reconcile ✗ (0 hits)**, **action_card_refresh ✗ (0 hits)** — so the one existing
card producer is the one task with no tenant scope, and S-NFR-8 applies to it directly.

## 10. Contract tests and the pinned gates

Three no-LLM contract tests (kept per ADR-068 d.6, `PLAN.md:7`), all present and all
source-inspection assertions on forbidden import names:
- `tests/unit/test_rules_copy_layer_contract.py:46-52` — `FORBIDDEN_LLM_IMPORT_PREFIXES =
  ("anthropic","ollama","openai","langchain","dspy")` asserted against AST import names of
  `services/scoring/copy_layer.py`.
- `tests/unit/test_recommendations.py:329-338` — `TestRuleBasedNoLlmDependency`; asserts
  `("openai","litellm","anthropic","langchain")` absent from
  `inspect.getsource(ai.recommendations.engine)`.
- `apps/dashboard/src/__tests__/test_listing_rules_engine.test.ts:152-160` — asserts
  `src/lib/workflows/new-seller/listing/index.ts` matches neither `/fetch\s*\(/` nor
  `/openai|anthropic|ollama/i`.

Gate tests pinned to `optimize_product_2` (all import `WORKFLOW_KEY` from
`playbooks/optimize_product.py:57`):
- `test_agent_prompt_snapshot_gate.py:79-160` — `compose(WORKFLOW_KEY, 1|2|3)` byte-for-byte
  against committed goldens.
- `test_agent_prompt_budget_gate.py:132-146` — `compose(WORKFLOW_KEY, production_version(...))`
  ≤ a named ceiling, plus an exact recorded 2,967-proxy-token measurement (`:21`).
- `test_agent_prompt_playbook_consistency_gate.py:175-275` — every tool-shaped token in the
  composed prompt is in the playbook; `test_the_real_registry_and_the_one_real_playbook_agree_on_six_tools`.

Shared prompt sections (§6 item 1) do **not** exist: `prompts/` holds only `composer.py` and
`optimize_product/{v1,v2,v3}.md`; `_WORKFLOW_BINDINGS` (`composer.py:103-118`) has one entry.

---

## Ranked: the 8 gaps most likely to be "discovered during implementation"

1. **`approval.py` runs Optimize Product for every card, by design** (`approval.py:173-187`).
   The first Clear Excess gate walk will approve a `clear_excess_4` card and watch the
   Optimize Product prompt execute. Fix before any second workflow, not with it.
2. **`product_id NOT NULL` + `NoProductsForShop`** (`models.py:577`, `approval.py:118-121,229`).
   Process Order has no product; approval raises 409 before any code you write runs.
3. **`resume_agent_workflow` has exactly one caller** (`agent_runs.py:266`). Both suspended
   workflows need a second, non-human trigger that nothing today provides.
4. **No notification transport at all** — FCM is a `fcm_send_stub`, no device-token store, iOS
   never uploads its token. PO-FR-8 and CE-FR-6 are unshippable, and this is a 3-layer change
   (schema, backend producer, iOS registration call) that will read as "one push" in the PRD.
5. **`workflow_webhook_signals` has no reader.** CE-FR-6 will be scoped as "handle the webhook"
   when the webhook is already handled — the missing half is signal → run resume.
6. **Adding `waiting_external` touches 5 pinned places** (enum, CHECK migration, TS union,
   `STOP_REASON_TO_STATUS` totality test, `NON_TERMINAL_STATUSES`). The mapping test asserts
   totality *in both directions*, so a status with no `stop_reason` targeting it fails.
7. **No scheduled card producer exists** and `action_card_refresh` is the one beat-adjacent
   task with **no `with_shop_scope`** — so item 4 is "write a beat task" *plus* an ADR-089 fix.
8. **The three-dict dispatcher plus `ProductToolContext(product_id=...)`** (`tool_executor.py:262`)
   — a non-product tool has no context object to receive, so item 1's "domain-registered
   dispatcher" is really "generalise the context", a wider change than the bullet suggests.

## Spec statements that are wrong or misleading about the code

- **S-FR-10 "Cards through the standard path only (ADR-087)"** presents ADR-087 as landed.
  It is `Status: Proposed` and **none** of its schema exists. As written, "the standard path"
  is today's `(shop_id, workflow_key)` unique constraint, which cannot express one card per
  subject — the requirement is self-contradictory against current code.
- **CE-NFR-1** says `waiting_external` "and the intervention guard landed as shared code" —
  neither exists; "landed" reads as done. Same for **RI-NFR-1**'s "landed as shared code".
- **S-NFR-6** "a suspended run has its own reaper policy, never `waiting_approval`'s" — the
  reaper has exactly one policy object today (`reaper.py:114`) and it is Optimize Product's.
- **§6 item 1** "de-pinned gate tests" is **two** tests in `PLAN.md:777`; there are **three**
  gate tests importing `WORKFLOW_KEY` (snapshot, budget, playbook-consistency). Budget also
  pins an exact token count, which any shared-section extraction will change.
- **§1 header table** cites ADR-093 for Replenish; it exists **only in the `v1-spec` worktree**
  (`.worktrees/v1-spec/docs/adr/093-replenish-inventory-design.md`), not on `main`. Anything
  reading ADRs from `main` will 404 on it.
- **PO-FR-8 "One push"** and **CE-FR-6 "notifies"** describe a capability with no transport;
  neither NFR section lists it as a precondition, so it will not be scoped.
- **Webhook #63** is not in `PHASE2_CATALOG`; the catalog jumps 58 → 64.
