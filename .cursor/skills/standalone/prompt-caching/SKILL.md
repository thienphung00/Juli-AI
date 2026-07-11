---
name: prompt-caching
description: >-
  Manages the two-tier workflow prompt cache (parent constant + child unique) for
  implement issue #N through Meta → Executor → Review → Validate. Use when loading,
  validating, injecting, or writing parent-cache and grill-cache artifacts before or
  during agent phases.
---

# Prompt caching

Owns the **workflow prompt cache** for child issue implementation. Keeps epic scope
constant across siblings while each child issue carries a unique load profile.

**Companion skill:** [`grill-with-docs`](../grill-with-docs/SKILL.md) resolves scope
conflicts via one-question-at-a-time alignment. When grilling produces or updates
decisions, write them into the cache using this skill.

## Two-tier model

| Tier | File | Shared? |
|------|------|---------|
| **Parent** | `parent-cache-issue-<P>.json` | Constant for all children of parent PRD #P |
| **Child** | `grill-cache-issue-<n>.json` | Unique per child — load profile, harnessUtility, phase blocks |

Sibling issues load **different** docs, skills, and modules. **Never** copy
`harnessUtility` or `issueLoadProfile` from a sibling grill cache.

Config paths: [`agent-runtime.config.yml`](../../../agent-runtime/config/agent-runtime.config.yml) → `grill_cache`.

## When to load

| Trigger | Action |
|---------|--------|
| `implement issue #N` | Resolve parent #P → load both caches → inject or grill |
| Meta / Executor / Review / Validate | Inject phase blocks + child `harnessUtility` |
| Epic rescope | Refresh parent cache only |
| Child issue body / AC changed | Delta grill + refresh child cache only |

## Session entry (cache hit path)

1. Resolve child #N and parent #P — see [REFERENCE.md](REFERENCE.md#resolve-parent-issue).
2. Load `agent-runtime/artifacts/grill-cache/parent-cache-issue-<P>.json`; fingerprint parent issue + epic handoff.
3. Load `agent-runtime/artifacts/grill-cache/grill-cache-issue-<n>.json`; fingerprint child issue + scope alignment.
4. Apply staleness rules:

| State | Action |
|-------|--------|
| Parent missing | Grill epic scope via `grill-with-docs` → write parent cache |
| Child missing | Grill child scope → write child cache (link `parentIssueId`) |
| Both valid | Cache hit — inject per order below; one confirm question |
| Child stale | Delta grill child only — parent unchanged unless epic rescoped |
| Parent stale | Delta grill epic only — may affect all children |

## Injection order (cache hit)

1. `parent-cache.parentScopeBlock` — epic deferrals, merchants, data-source policy
2. `parent-cache.doNotLoad` — epic-wide exclusions
3. `grill-cache.promptCacheBlock` — child-specific scope
4. `phaseCacheBlocks.<phase>` — active agent phase
5. `issueLoadProfile` — this child's requiredDocs, requiredModules, acceptanceCriteria
6. `harnessUtility` — this child's skills / rules / mcps / tools only
7. Code + `MODULE.md` from `issueLoadProfile.requiredModules`

**Do not inject** sibling child caches. **Do not inherit** sibling `harnessUtility`.

## Phase completion (child cache only)

Each phase appends to **child** `grill-cache-issue-<n>.json`:

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
assign executor without a valid child cache.

## Agent integration

| Agent | Loads | Must not |
|-------|-------|----------|
| **Meta** | parent block + child meta block + child issueLoadProfile | Copy sibling harnessUtility |
| **Executor** | parent block + child executor block + child harnessUtility | Start TDD without valid child cache |
| **Review** | parent block + child review block | Reload full review skill if cached |
| **Validate** | parent block + child validate block | Reload validate skill if cached |

## Artifacts

| File | Schema | Template |
|------|--------|----------|
| `parent-cache-issue-<P>.json` | [`parent-cache-artifact.schema.json`](../../../agent-runtime/docs/schemas/parent-cache-artifact.schema.json) | [`parent-cache-template.json`](../../../agent-runtime/templates/parent-cache-template.json) |
| `grill-cache-issue-<n>.json` | [`grill-cache-artifact.schema.json`](../../../agent-runtime/docs/schemas/grill-cache-artifact.schema.json) | [`grill-cache-issue-template.json`](../../../agent-runtime/templates/grill-cache-issue-template.json) |
| `scope-alignment-issue-<n>.md` | — | [`scope-alignment-issue-template.md`](../../../agent-runtime/templates/scope-alignment-issue-template.md) |

Deep details — authority chain, fingerprint rules, harnessUtility examples, pipeline
diagram: [REFERENCE.md](REFERENCE.md).
