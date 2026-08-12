"""Agent output sanitization (ADR-070).

- `banned_patterns` (decision 6) — shared banned-pattern guard. Patterns live in one
  language-neutral JSON source (`packages/contracts/seller-copy-banned-patterns.json`)
  so this Python loader and the TypeScript guard (`packages/contracts/src/seller-copy.ts`)
  can never drift silently (#990).
- `provenance` (decision 3) — server-assigned `source` envelopes (`juli`/`vendor`/
  `seller`) wrapping every piece of free text in a tool result (#991).
- `machine_values` (decision 4) — absolute ISO-8601 UTC timestamps, money as a numeric
  amount + currency field, and rates as bare numbers under self-describing keys (#991).
- `caps` (decision 2) — hard per-result size caps with always-signalled truncation:
  lists cut to their top 20 entries in caller order, free text cut at ~1,500 characters
  (verbatim below the cap), images reduced to `{count, dimensions}` with no raw nested
  vendor payload. Every cut emits `{"truncated": true, "omitted_count": n}`; a result
  needing no cut emits no marker at all (#992).

See `docs/adr/070-agent-safe-sanitization-contract.md`. The two fail-closed chokepoints
that consume the banned-pattern guard and error translation are separate issues
(#993-#995).
"""

from juli_backend.services.agent.sanitize.banned_patterns import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
)
from juli_backend.services.agent.sanitize.caps import (
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
from juli_backend.services.agent.sanitize.machine_values import (
    Money,
    Number,
    iso_utc_timestamp,
    numeric_value,
)
from juli_backend.services.agent.sanitize.provenance import (
    PROVENANCE_SOURCES,
    JuliText,
    ProvenanceEnvelope,
    ProvenanceSource,
    SellerText,
    VendorText,
    from_source,
    to_json_safe,
)

__all__ = [
    "BANNED_PATTERNS_JSON_PATH",
    "FREE_TEXT_CHAR_CAP",
    "LIST_ITEM_CAP",
    "PER_RESULT_TOKEN_CEILING",
    "PER_RESULT_TOKEN_TARGET",
    "PROVENANCE_SOURCES",
    "BannedPatternEntry",
    "CappedImages",
    "CappedList",
    "CappedText",
    "ImageDimensions",
    "JuliText",
    "Money",
    "Number",
    "ProvenanceEnvelope",
    "ProvenanceSource",
    "SellerText",
    "VendorText",
    "cap_list",
    "cap_text",
    "estimate_result_tokens",
    "estimate_tokens",
    "from_source",
    "iso_utc_timestamp",
    "load_banned_pattern_entries",
    "load_banned_patterns",
    "numeric_value",
    "sanitize_images",
    "to_json_safe",
]
