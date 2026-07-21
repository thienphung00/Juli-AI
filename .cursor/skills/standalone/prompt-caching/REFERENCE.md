# Prompt caching — reference

## Resolve parent issue

Child issue #N is never the cache anchor. Resolve parent #P first:

1. Epic handoff `PRD: [#P]` (e.g. `phase-2-tiktok-implementation.md` → #278)
2. Child issue body: `Parent: #P`, `Part of #P`, tracking link
3. `gh issue view <n> --json body,title` + label `epic:P`
4. `.agent-state/issue-<n>.checkpoint.yml` → `parent_prd`
5. If parent unknown → ask user once before scope alignment

## Workflow pipeline

```
implement issue #N (child)
  → resolve parent #P
  → load parent-cache-issue-P.json
  → load issue-context-cache-N.json
  → inject stable → volatile (see Injection order below)
  → Meta → Executor → Review → Validate (each appends its phaseCacheBlocks to child cache)
  → append N to parent.childIssueIds; refresh parent if epic scope changed
```

## Injection order (stable → volatile)

Prefix-cache efficiency requires stable blocks before volatile ones. Config source of truth:
`agent-runtime/config/agent-runtime.config.yml` → `workflow_prompt_cache.injectionOrder`.

| # | Block | Stability |
|---|-------|-----------|
| 1 | `parent-cache.parentScopeBlock` | Epic constant |
| 2 | `parent-cache.doNotLoad` | Epic constant |
| 3 | `issue-context-cache.harnessUtility` | Stable after Meta |
| 4 | `issue-context-cache.issueLoadProfile` | Stable after scope alignment |
| 5 | `issue-context-cache.phaseCacheBlocks.<phase>` | Volatile per tick — active phase only |
| 6 | `issue-context-cache.promptCacheBlock` | Most volatile child summary |
| 7 | `issueLoadProfile.requiredModules.code-and-module-md` | Code + MODULE.md |

Per-phase ticks inject items 1–4 (skip missing), then **only** the active phase block
from item 5 — not the full phase history. Items 6–7 follow.

## What differs per child issue

| Child | Parent #278 constant | Unique to child |
|-------|---------------------|-----------------|
| #297 Layer 1 reads | T8 deferred, Fujiwa read-only | `endpoints.md`, polling MODULE |
| #299 ETL | same parent block | `services/etl/`, data-platform skill |
| #301 sandbox writes | same parent block | sandbox merchant, write validation, tiktok integration |

## Writing caches

### Parent (`parent-cache-issue-<P>.json`)

- `parentScopeBlock` from PRD + handoff confirmed decisions
- Epic `doNotLoad`; fingerprint parent issue + handoff + EXECUTION.md
- `bootstrapRef` pins harness bootstrap source (`branch`, `commitSha`, `copiedAt`) — see Bootstrap pinning below
- `childIssueIds` append on each child completion

### Child (`issue-context-cache-<n>.json`)

- `parentIssueId`, `parentCachePath` (required)
- `issueLoadProfile` derived from `parentLinkage.sliceId` + **this** issue's AC
  — not siblings and not hand-written first
- `harnessUtility` built during Meta for **this** issue only
- `upstreamFingerprints` for **child** issue body — separate from parent

## Derived issueLoadProfile

`issueLoadProfile` is derived-first. Scope alignment and Meta use:

1. `parentLinkage.sliceId`
2. Focus slice routing table
3. Child GitHub issue acceptance criteria

Human scope alignment fills only gaps: conflicts, edge modules, or open questions. It must not
silently replace the derived required docs/modules with hand-curated lists.

Implementation:

- Config rules: `agent-runtime/config/slice-routing.yml`
- Focus table: [`focus/SKILL.md`](../focus/SKILL.md#step-4a-derive-child-issueloadprofile)
- Derivation code: `agent-runtime/scripts/ci/issue_load_profile.py`
- Gate: `agent-runtime/scripts/validate/check_issue_load_profile.py`

Gate behavior:

| Drift | Result |
|-------|--------|
| Cached `requiredDocs` / `requiredModules` omits derived path | FAIL |
| Cached profile adds undeclared required or optional path | FAIL |
| Cached acceptance criteria differs from child issue AC | FAIL |
| New slice lacks a derivation row | FAIL until Focus + slice-routing.yml are updated |

`loadWhenNeeded` is the declared optional set. If scope alignment discovers a real edge
module, add it to slice-routing.yml before relying on it in cache.

## Authority chain

Precedence (highest wins on conflict):

1. `EXECUTION.md` slice
2. `parent-cache-issue-<P>` (epic constant)
3. **Child** GitHub issue #N acceptance criteria
4. Epic handoff (when not superseded by EXECUTION.md)
5. Legacy — excluded until confirmed

### Authority resolution

Gate script (authoritative):
`agent-runtime/scripts/validate/check_scope_precedence.py`.

Run **after** the staleness gate passes. Compares cached `authorityChain` in
`issue-context-cache-<N>.json` to the live chain derived from upstream sources.

| Precedence rule | Behavior |
|-----------------|----------|
| Child issue AC vs handoff (child-specific behavior) | Child issue AC wins |
| Parent/epic vs child (deferrals) | Parent/epic wins |
| Same rank, ambiguous tie | One HITL confirm question → write cache |

**On mismatch** (gate exits non-zero):

1. **Halt Executor** — do not start TDD until resolved.
2. Set child `cacheStatus: partial`.
3. Refresh **conflicting rank only** (not full re-scope unless multiple ranks stale).
4. Record outcome in `resolvedDecisions[]` on the child cache.

| Conflicting rank | Source | `resolution` |
|------------------|--------|--------------|
| 1 | `EXECUTION.md` | `refresh_epic_cache` |
| 2 | `parent-cache-issue-<P>` | `refresh_epic_cache` |
| 3 | `GitHub issue #<N>` | `refresh_issue_cache` |
| 4 | Epic handoff | `refresh_epic_cache` |
| Same rank, ambiguous | — | `hitl_confirm` |

Gate JSON output includes `halt`, `resolution`, `conflictingRank`, and `conflicts[]`
with actionable messages. Implementation:
`agent-runtime/scripts/ci/scope_precedence.py`.

## harnessUtility rule

Populated per child during Meta routing. Same parent block; different child caches:

```json
// #301 — backend integration only
{ "skills": [{ "path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "Sandbox writes" }] }

// #299 — different child, different load
{ "skills": [
    { "path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "ETL services" },
    { "path": ".cursor/skills/domain/data-platform/SKILL.md", "purpose": "Upsert migrations" }
  ]}
```

## Context freshness

Gate script (authoritative): `agent-runtime/scripts/validate/check_workflow_cache_staleness.py`.

| Context | Staleness signal | Action |
|---------|-------------------|--------|
| Child issue context cache | Child issue body or scope-alignment fingerprint mismatch | Refresh issue cache only |
| Parent cache | Parent issue, epic handoff, or EXECUTION slice fingerprint mismatch | Refresh epic cache; may affect all children |
| EXECUTION.md / system-design | Rescope PR merged | Reload slices; refresh fingerprints on next scope alignment |

## Fingerprint algorithm

Recompute on session entry; compare to cached `upstreamFingerprints`. Implementation:
`agent-runtime/scripts/ci/upstream_fingerprints.py`.

| Source | Path key in artifact | Algorithm |
|--------|----------------------|-----------|
| GitHub issue body | `GitHub issue #<n>` | SHA-256 of `gh issue view <n> --json body -q .body`, first 16 hex chars |
| Repo file (handoff, scope alignment) | repo-relative path | Git blob SHA (`git hash-object`; SHA-1 over `blob <size>\0<bytes>`) |
| EXECUTION.md with known slice | `EXECUTION.md` | Git blob SHA of the **`##` section containing `**<sliceId>**`** — not whole file when `sliceId` or `parentLinkage.sliceId` is set |
| EXECUTION.md without slice | `EXECUTION.md` | Git blob SHA of whole file |

### Parent cache fingerprints

1. `GitHub issue #<P>` — parent/PRD issue body
2. `<handoffPath>` — epic handoff doc (e.g. `docs/handoffs/phase-2-tiktok-implementation.md`)
3. `EXECUTION.md` — slice section when `sliceId` set on parent cache or child `parentLinkage.sliceId`

### Child cache fingerprints

1. `GitHub issue #<N>` — child issue body
2. `<scopeAlignmentPath>` — `agent-runtime/artifacts/workflow-cache/scope-alignment-issue-<N>.md`

On mismatch the gate exits non-zero, sets logical stale state, and prints the refresh path
(child-only vs parent-only) per the table above. Refresh fingerprints when scope alignment completes.

## Bootstrap pinning

Prevent quiet drift between sibling harness runs by pinning bootstrap source to an **immutable
commit SHA**, not a floating branch head. Config: `agent-runtime.config.yml` → `workflow_prompt_cache.bootstrap`.

| Pin | Scope |
|-----|-------|
| `parent-cache.bootstrapRef` | Harness machinery shared by all children of parent #P |
| Benchmark `COMMON_SHA` (#301) | Measurement baseline only — **separate** from bootstrap pinning |

### bootstrapRef fields (parent cache)

| Field | Purpose |
|-------|---------|
| `branch` | Source branch name (informational) |
| `commitSha` | Immutable 40-char git SHA skills/schemas/templates were copied from |
| `copiedAt` | ISO timestamp when pin was set or last verified |
| `architectNote` | Required when bumping `commitSha` after branch HEAD advanced |

### Workflow

1. **Initial bootstrap** — cherry-pick or copy skills, schemas, templates from a **pinned SHA**
   (not branch HEAD). Record `bootstrapRef` on parent cache.
2. **Sibling runs** — all children under the same parent inherit the same `bootstrapRef`.
   Child `harnessUtility.skills[].path` must exist at the pinned SHA.
3. **Re-bootstrap after stale detection** — verify `bootstrapRef.commitSha` unchanged, or
   explicitly bump `commitSha` + `copiedAt` with an Architect note explaining why.
4. **Gate** — `agent-runtime/scripts/validate/check_harness_bootstrap_pin.py --issue <N>`:
   - Branch HEAD for `bootstrapRef.branch` must equal `bootstrapRef.commitSha`
   - All child `harnessUtility` skill paths must exist at the pinned SHA
   - Branch HEAD advance without SHA bump → fail

Implementation: `agent-runtime/scripts/ci/harness_bootstrap_pin.py`.

## Cache block fields (child)

| Field | Purpose |
|-------|---------|
| `promptCacheBlock` | Machine-injectable child scope summary (mirrors `phaseCacheBlocks.scope`) |
| `phaseCacheBlocks.scope` | Scope alignment phase output |
| `phaseCacheBlocks.meta` | Meta routing decisions |
| `phaseCacheBlocks.executor` | Executor TDD context |
| `phaseCacheBlocks.review` | Review checklist focus |
| `phaseCacheBlocks.validate` | Validate gate focus |
| `issueLoadProfile` | requiredDocs, requiredModules, acceptanceCriteria, executorDomain |
| `harnessUtility` | skills, rulesTier2, mcps, tools for this child only |
| `cacheStatus` | `valid` \| `stale` \| `partial` |
| `workflowPhase` | Last completed phase |

## Gate orchestrator

Run all session-entry gates in order:

```bash
python agent-runtime/scripts/validate/check_workflow_cache.py --issue <N>
```

Sequence: staleness → scope precedence → harness bootstrap pin → issue load profile.

## Related docs

- [`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md) — phase model
- [`agent-runtime/docs/agent-runtime-artifacts.md`](../../../agent-runtime/docs/agent-runtime-artifacts.md) — artifact taxonomy
- [`agent-runtime/artifacts/README.md`](../../../agent-runtime/artifacts/README.md) — path conventions
