# backend/src/juli_backend/services/agent

## Purpose

Agent-workflow services (ADR-068/069/070). This slice adds the shared
banned-pattern source loader (#990, decision 6), provenance envelopes and
machine-shaped values (#991, decisions 3/4), and hard size caps with
always-signalled truncation (#992, decision 2) — the two fail-closed
chokepoints that consume the banned-pattern guard and error translation are
separate issues (#993-#995).


## Subpackages

- `sanitize` — loads `packages/contracts/seller-copy-banned-patterns.json`, the
  single language-neutral source of banned seller-copy patterns also consumed by
  the TypeScript guard (`packages/contracts/src/seller-copy.ts`). See
  `sanitize/banned_patterns.py`. Also provides `sanitize/provenance.py`
  (source-tagged text envelopes), `sanitize/machine_values.py` (ISO-8601
  timestamps, `Money`, bare-number rates), and `sanitize/caps.py` (list/text/image
  size caps with signalled truncation).

## Public Interface

```python
from juli_backend.services.agent.sanitize import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
    # caps (#992, ADR-070 decision 2)
    FREE_TEXT_CHAR_CAP,
    LIST_ITEM_CAP,
    PER_RESULT_TOKEN_CEILING,
    PER_RESULT_TOKEN_TARGET,
    CappedImages,
    CappedList,
    CappedText,
    ImageDimensions,
    cap_list,
    cap_text,
    estimate_result_tokens,
    estimate_tokens,
    sanitize_images,
)
```

- `load_banned_patterns() -> tuple[re.Pattern[str], ...]` — compiled patterns,
  cached.
- `load_banned_pattern_entries() -> tuple[BannedPatternEntry, ...]` — raw
  `(id, source, flags)` records, file order.
- `BANNED_PATTERNS_JSON_PATH` — resolved path to the shared JSON source.
- `cap_list(items, *, cap=LIST_ITEM_CAP) -> CappedList` — cuts to the top `cap`
  entries in the caller's own order (never re-sorts); `.to_dict()` omits the
  `truncated`/`omitted_count` keys entirely when nothing was cut.
- `cap_text(text, *, cap=FREE_TEXT_CHAR_CAP) -> CappedText` — text at or under
  the cap passes through verbatim, byte-for-byte.
- `sanitize_images(images, *, cap=LIST_ITEM_CAP) -> CappedImages` — reduces raw
  vendor image payloads to `{count, dimensions}`; only `width`/`height` survive
  per image, `count` is always the true total.
- `estimate_tokens(text) -> int` / `estimate_result_tokens(result) -> int` — a
  stdlib-only, deterministic (rounds up) `chars/4` token estimate against
  `PER_RESULT_TOKEN_CEILING` (2000) / `PER_RESULT_TOKEN_TARGET` (800). Not a
  real tokenizer — no tokenizer dependency is declared anywhere in this repo.

## Dependencies

- stdlib only (`json`, `re`, `pathlib`, `dataclasses`, `functools`, `math`,
  `inspect`/`ast` in tests only).
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
- `caps.py`: every cut is deterministic server code (pure slicing — no model
  call, no randomness, no wall-clock branching); the same input always produces
  a byte-identical serialized result, enforced by
  `tests/unit/test_agent_sanitize_caps.py`. A `CappedList`/`CappedText`/
  `CappedImages` cannot be constructed with an inconsistent `truncated`/
  `omitted_count` pair — `__post_init__` raises `ValueError`.
