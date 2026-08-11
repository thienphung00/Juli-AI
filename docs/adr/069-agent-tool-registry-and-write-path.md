# ADR-069: Agent tool registry — decision-point granularity, in-run write path, ToolSpec module

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (boundary, authority,
AUTO/CONFIRM/NEVER policy, WorkflowRunStatus).
**Does not change:** the legacy Celery tool registry
(`services/execution/runner.py`) and the coarse workflow chains
(`run_optimize_product_chain` et al.) — they stay registered and untouched for the
existing `POST /v1/executions` path.
**Scope:** Phases P3+P4 (tool registry + tool schemas) of
[`docs/product/agent-workflow-execution/PLAN.md`](../product/agent-workflow-execution/PLAN.md),
minimal set for `optimize_product_2`.

## Context

The agent loop needs LLM-callable tools. The existing registry is name→callable with no
metadata; the existing Optimize Product implementation is one coarse 6-step chain whose
"optimized" content is TikTok's first suggestion — the LLM would have nothing to reason
about or author. Three decisions were grilled: tool granularity, the write-execution/audit
path, and the registry module design.

## Decision

1. **Decision-point granularity.** Tool boundaries follow one rule: *split where a
   decision point, a policy-class boundary, or a confirmation sits between calls; bundle
   only no-decision, same-class adjacent calls.* Rationale: every tool boundary is a full
   LLM round-trip (latency + tokens), so a boundary with no decision buys a reasoning-free
   turn; but merging across policy classes would break per-write CONFIRM, and merging
   across decisions removes the agent's authority. Bundled tools emit sub-step progress
   events so narration stays 1:1 with the documented playbook steps.

   Applied to Optimize Product (`execution_layer.md` §2) — **6 tools**:

   | Playbook step | Agent tool | Wraps | Class / policy |
   |---|---|---|---|
   | 1 | `get_product_information` | `products.get_details` | READ / AUTO |
   | 2+3 | `get_seo_keywords` | `get_seo_words` + `get_suggestions` (only bundle — no decision between them) | READ / AUTO |
   | 4, 4.5 | `upload_product_image` | screened upload (ADR-055 item 20) → asset URI | WRITE / AUTO (staging only; the listing changes only via Edit, whose CONFIRM diff shows the new image) |
   | 5 | `update_product_listing` | `products.edit` — LLM-authored title/description | WRITE / CONFIRM |
   | 6 | `update_product_price` | `products.update_prices` | WRITE / CONFIRM (independently rejectable from step 5) |
   | 6.5 | `check_product_status` | `products.get_details` status field | READ / AUTO — in-run snapshot |

   Step 6.5's authoritative confirmation is the **product status change webhook (#5)**
   arriving post-run via `WorkflowWebhookSignal`, updating the run's
   `WorkflowOutcomeRecord` — the run never blocks on TikTok re-review.

2. **Writes execute in-run, audited as `ToolExecution` rows.** A CONFIRM resume executes
   the write inside the agent run's Celery task (no nested enqueue): insert
   `ToolExecution` (`QUEUED→RUNNING`), call the guarded resource, update to
   `SUCCEEDED/FAILED` with `outcome_json`, record `WorkflowOutcomeRecord` via the
   existing `outcome_port`. The outbound Redis `RateLimiter` attaches at the tool
   executor, recovering global write-throttling without a queue hop. Two code paths now
   write `tool_executions` (legacy dispatcher + agent executor) — kept consistent by a
   shared helper.

   **Documented revisit trigger (per user direction):** if confirmed-write volume grows
   to where per-write crash isolation, independent Celery retry policies, or a dedicated
   write-worker pool matter, adopt the nested-`enqueue_approved_tool` shape. The tool
   executor is the single seam where enqueue-and-wait slots in; nothing else changes.

3. **Registry module: `services/agent/tools/`.** `registry.py` defines a `ToolSpec`
   dataclass — `name`, `description` (English, model-facing), `input_model` /
   `output_model` (Pydantic; the LLM-facing JSON schema is derived via
   `model_json_schema()` so schema and validation cannot drift), `classification`
   (read|write), `policy` (auto|confirm — NEVER-class operations are unregistered per
   ADR-068), `timeout_seconds` — with explicit registration and domain-grouped handlers
   (`product.py` first). Names are business-semantic English snake_case, never vendor
   endpoint names; seller-visible text is Vietnamese and only ever comes from sanitized
   outputs, not tool metadata. Output models are the sanitized business-semantic shapes
   (phase P5 plugs in there).

4. **Allowlists live in playbooks, not on ToolSpecs.** Each compiled playbook step names
   its permitted tools. Import-time contract tests cross-validate both directions: every
   playbook tool is registered; every registered tool appears in at least one playbook or
   is explicitly marked shared.

## Consequences

- The LLM authors listing content between `get_seo_keywords` and
  `update_product_listing`, replacing the `_first_suggestion_text` heuristic on the agent
  path; the legacy chain keeps that heuristic unchanged.
- `tool_executions` gains a second writer; the shared persistence helper is the guard
  against semantic drift, and `GET /v1/executions`, `WorkflowOutcomeRecord`, and
  `/workflow-outcomes` observe agent writes with zero changes.
- Adding a workflow means writing its playbook (tool names included) and any missing
  tools — never editing existing ToolSpecs.
- Revisit triggers recorded: nested-enqueue upgrade (decision 2); strict 1:1 granularity
  if sub-step events prove insufficient for narration or audit.
