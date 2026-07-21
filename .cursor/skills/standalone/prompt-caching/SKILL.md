---
name: prompt-caching
description: >-
  Manages the two-tier workflow prompt cache (parent constant + child unique) for
  implement issue #N through Meta → Executor → Review → Validate. Use when loading,
  validating, injecting, or writing parent-cache and issue-context-cache artifacts
  before or during agent phases.
---

# Prompt caching

Owns the **workflow prompt cache** for child issue implementation. Keeps epic scope
constant across siblings while each child issue carries a unique load profile.

**Companion skill:** [`grill-with-docs`](../grill-with-docs/SKILL.md) resolves scope
conflicts via one-question-at-a-time alignment. When scope alignment produces or updates
decisions, write them into the cache using this skill.

## Two-tier model

| Tier | File | Shared? |
|------|------|---------|
| **Parent** | `parent-cache-issue-<P>.json` | Constant for all children of parent PRD #P |
| **Child** | `issue-context-cache-<n>.json` | Unique per child — load profile, harnessUtility, phase blocks |

Sibling issues load **different** docs, skills, and modules. **Never** copy
`harnessUtility` or `issueLoadProfile` from a sibling issue context cache.

Config paths: [`agent-runtime.config.yml`](../../../agent-runtime/config/agent-runtime.config.yml) → `workflow_prompt_cache`.

## When to load

| Trigger | Action |
|---------|--------|
| `implement issue #N` | Resolve parent #P → load both caches → inject or scope-align |
| Meta / Executor / Review / Validate | Inject phase blocks + child `harnessUtility` |
| Epic rescope | Refresh parent cache only |
| Child issue body / AC changed | Refresh child cache only |

## Session entry (Meta → Executor)

**Do not ask the user to prepare parent cache.** Meta always runs the entrypoint:

```bash
python agent-runtime/scripts/meta_prepare_executor.py --issue <N>
# optional overrides: --parent <P> --slice-id <SLICE> --handoff <path> --force
```

This:

1. Resolves parent #P + sliceId (issue body `## Parent` / `Parent: #P`, `Slice: …`, or
   `workflow_prompt_cache.epicRegistry` in `agent-runtime.config.yml`).
2. **Ensures** parent + child caches via `ensure_workflow_cache` (creates or refreshes
   fingerprints, scope-alignment stub, derived `issueLoadProfile`, single primary
   domain skill in `harnessUtility`).
3. Runs the gate chain: staleness → scope precedence → bootstrap pin → issueLoadProfile.
4. Unlocks Executor only when `readyForExecutor: true` and `cacheStatus == valid`.

Equivalent lower-level commands (debugging):

```bash
python agent-runtime/scripts/validate/run_ensure_workflow_cache.py --issue <N>
python agent-runtime/scripts/validate/check_workflow_cache.py --issue <N> --ensure --require-valid
```


| Result | Action |
|--------|--------|
| Exit 0 + `readyForExecutor` | Inject `injectionPlan`; assign Executor |
| Parent/slice unknown | Pass `--parent` / `--slice-id` or add epicRegistry row; do not start Executor |
| Authority conflict (`halt: true`) | Halt Executor; set `cacheStatus: partial`; refresh conflicting rank |
| issueLoadProfile drift | Update `slice-routing.yml` or `--force` ensure; rerun |
| Stale fingerprints | Re-run `meta_prepare_executor.py` (ensure refreshes fingerprints) |

## Injection order (cache hit)

Stable blocks first, volatile blocks last — maximizes prefix-cache reuse across
Meta → Executor → Review → Validate ticks. Machine-readable source of truth:
[`agent-runtime.config.yml`](../../../agent-runtime/config/agent-runtime.config.yml) → `workflow_prompt_cache.injectionOrder`.

1. `parent-cache.parentScopeBlock` — epic deferrals, merchants, data-source policy
2. `parent-cache.doNotLoad` — epic-wide exclusions
3. `issue-context-cache.harnessUtility` — this child's skills / rules / mcps / tools index
4. `issue-context-cache.issueLoadProfile` — requiredDocs, requiredModules, acceptanceCriteria
5. `issue-context-cache.phaseCacheBlocks.<phase>` — active agent phase only (per tick)
6. `issue-context-cache.promptCacheBlock` — most volatile child scope summary
7. `issueLoadProfile.requiredModules.code-and-module-md` — code + MODULE.md from requiredModules

**Do not inject** sibling child caches. **Do not inherit** sibling `harnessUtility`.
**Do not inject** prior phase blocks — only the active `phaseCacheBlocks.<phase>` for the current tick.

## Phase completion (child cache only)

Each phase appends to **child** `issue-context-cache-<n>.json`:

| Phase | Updates |
|-------|---------|
| Scope alignment | `promptCacheBlock`, `issueLoadProfile`, `phaseCacheBlocks.scope` |
| Meta | `phaseCacheBlocks.meta`, child `harnessUtility` |
| Executor | `phaseCacheBlocks.executor` |
| Review | `phaseCacheBlocks.review` |
| Validate | `phaseCacheBlocks.validate`, `workflowPhase: complete` |

Parent cache updates only when epic-level decisions change — not on every child completion.

## Gate before Executor

Child cache must have `cacheStatus: valid` before Executor TDD starts. Meta must not
assign executor without a valid child cache. Enforced by
`workflow_prompt_cache.requireValidCacheBeforeExecutor: true` and
`agents.meta.pre_executor_command` → `meta_prepare_executor.py`.

## Agent integration

Per-phase ticks inject the stable prefix (items 1–4), then **only** the active
phase block (item 5), then items 6–7. Skip missing blocks; preserve order.

| Agent | Stable prefix (1–4) | Active phase block (5) | Must not |
|-------|---------------------|------------------------|----------|
| **Meta** | parentScopeBlock, doNotLoad, issueLoadProfile | `phaseCacheBlocks.meta` | Copy sibling harnessUtility; inject other phase blocks |
| **Executor** | parentScopeBlock, doNotLoad, harnessUtility, issueLoadProfile | `phaseCacheBlocks.executor` | Start TDD without valid child cache; inject meta/review/validate blocks |
| **Review** | parentScopeBlock, doNotLoad, harnessUtility, issueLoadProfile | `phaseCacheBlocks.review` | Reload full review skill; inject other phase blocks |
| **Validate** | parentScopeBlock, doNotLoad, harnessUtility, issueLoadProfile | `phaseCacheBlocks.validate` | Reload validate skill; inject other phase blocks |

## Artifacts

| File | Schema | Template |
|------|--------|----------|
| `parent-cache-issue-<P>.json` | [`parent-cache-artifact.schema.json`](../../../agent-runtime/docs/schemas/parent-cache-artifact.schema.json) | [`parent-cache-template.json`](../../../agent-runtime/templates/parent-cache-template.json) |
| `issue-context-cache-<n>.json` | [`issue-context-cache-artifact.schema.json`](../../../agent-runtime/docs/schemas/issue-context-cache-artifact.schema.json) | [`issue-context-cache-template.json`](../../../agent-runtime/templates/issue-context-cache-template.json) |
| `scope-alignment-issue-<n>.md` | — | [`scope-alignment-issue-template.md`](../../../agent-runtime/templates/scope-alignment-issue-template.md) |

Deep details — authority chain, fingerprint rules, harnessUtility examples, pipeline
diagram: [REFERENCE.md](REFERENCE.md).
