# Scope Alignment — Issue #<N> (child of parent #<P>)

**Parent issue:** #<P> (constant — `parent-cache-issue-<P>.json`)  
**Status:** partial | valid | stale  
**Cache block version:** 1  
**Last validated:** YYYY-MM-DD  
**Companion artifact:** `agent-runtime/artifacts/grill-cache/grill-cache-issue-<N>.json`

## Authority chain (this run)

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice ___ | Phase/slice law |
| 2 | `docs/architecture/system-design.md` § ___ | Subsystem envelope |
| 2 | `parent-cache-issue-<P>` | Epic constant for all children |
| 3 | GitHub issue #<N> | **Child** acceptance criteria (unique) |
| 4 | `docs/handoffs/___` | Task handoff (when not superseded) |

## Conflicts resolved

| Topic | Conflicting sources | Decision |
|-------|---------------------|----------|
| Feature A | handoff: defer · EXECUTION: implement | **Implement A** |
| Feature B | handoff: defer · EXECUTION: defer | **Defer B** |

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

The `promptCacheBlock` in `grill-cache-issue-<N>.json` is the machine-injectable
summary of this file. On cache hit, agents load the JSON block first and skip
re-reading full upstream docs unless fingerprints are stale.
