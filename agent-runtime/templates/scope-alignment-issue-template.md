# Scope Alignment — Issue #<N> (child of parent #<P>)

**Parent issue:** #<P> (constant — `parent-cache-issue-<P>.json`)  
**Status:** partial | valid | stale  
**Cache block version:** 1  
**Last validated:** YYYY-MM-DD  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-<N>.json`

## Authority chain (this run)

Precedence: `EXECUTION.md` → parent cache → child issue AC → handoff.

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice ___ | Phase/slice law |
| 2 | `parent-cache-issue-<P>` | Epic constant for all children |
| 3 | GitHub issue #<N> | **Child** acceptance criteria (unique) |
| 4 | `docs/handoffs/___` | Task handoff (when not superseded) |

On session entry, `check_scope_precedence.py` compares this table to cached
`authorityChain`. Mismatch → halt Executor, `cacheStatus: partial`, refresh
conflicting rank only.

## Conflicts resolved

Record every resolved conflict here **and** in child cache `resolvedDecisions[]`.

| Topic | Conflicting sources | Decision | Winner rule |
|-------|---------------------|----------|-------------|
| Feature A | handoff: defer · EXECUTION: implement | **Implement A** | EXECUTION (rank 1) |
| Child behavior | handoff: mock · issue #N AC: Postgres | **Postgres** | Child AC (rank 3) |
| Epic deferral | issue #N: build T8 · parent cache: defer T8 | **Defer T8** | Parent/epic (rank 2) |
| Ambiguous tie | same rank, unclear | _(HITL confirm)_ | Ask once → write cache |

## In scope (this issue)

-

## Out of scope (explicit deferrals)

-

## DO NOT load (deprecated for this run)

- `docs/handoffs/archive/`
- `docs/product/features/`
-

## Open questions

- (empty when valid)

## Prompt cache note

The `promptCacheBlock` in `issue-context-cache-<N>.json` is the machine-injectable
summary of this file. On cache hit, agents load the JSON block first and skip
re-reading full upstream docs unless fingerprints are stale.
