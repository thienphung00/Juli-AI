# backend/src/juli_backend/services/agent

## Purpose

Agent-workflow services (ADR-068/069/070). This slice (#990, ADR-070 decision 6)
adds only the shared banned-pattern source loader — the two fail-closed chokepoints
that consume it, provenance envelopes, caps, and error translation are separate
issues (#991-#995).

## Subpackages

- `sanitize` — loads `packages/contracts/seller-copy-banned-patterns.json`, the
  single language-neutral source of banned seller-copy patterns also consumed by
  the TypeScript guard (`packages/contracts/src/seller-copy.ts`). See
  `sanitize/banned_patterns.py`.

## Public Interface

```python
from juli_backend.services.agent.sanitize import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
)
```

- `load_banned_patterns() -> tuple[re.Pattern[str], ...]` — compiled patterns,
  cached.
- `load_banned_pattern_entries() -> tuple[BannedPatternEntry, ...]` — raw
  `(id, source, flags)` records, file order.
- `BANNED_PATTERNS_JSON_PATH` — resolved path to the shared JSON source.

## Dependencies

- stdlib only (`json`, `re`, `pathlib`, `dataclasses`, `functools`).
- Reads `packages/contracts/seller-copy-banned-patterns.json` via a
  monorepo-relative path (six parents up from `sanitize/banned_patterns.py`, same
  convention as `juli_backend.core.config.runtime._repo_root`).

## Invariants

- No pattern is added, removed, or altered by this loader — it only compiles what
  the JSON source contains. New patterns must compile under both Python `re` and
  JavaScript `RegExp` — enforced by
  `tests/unit/test_agent_banned_patterns_contract.py`.
- Only the `i` (case-insensitive) JS regex flag is translated; any other flag
  raises `re.error` naming the offending pattern id rather than being silently
  dropped.
