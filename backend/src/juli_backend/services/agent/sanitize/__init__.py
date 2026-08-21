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
- `errors` (decision 5) — every marketplace failure (`TikTokAPIError`, `TransportGuardError`,
  or a bare transport failure) maps to `{"error": {"category", "message", "retryable"}}`.
  `category` reuses `ExecutionErrorCategory`; `retryable` derives from a curated vendor-code
  allowlist (`{100005, 100006, 36009003}`) plus transport-level failures — an uncatalogued
  vendor code is not retryable. Raw vendor codes, request ids, and endpoint paths go to
  server-side logs only, never into the envelope (#993).
- `chokepoints` (decision 6) — the two fail-closed banned-pattern seams that bracket the
  agent: `guard_inbound_tool_result` replaces a hit with an internal tool error (the
  `errors` envelope shape) before it reaches the conversation; `guard_outbound_agent_output`
  raises `BannedPatternGuardFailure` before agent-authored output streams or persists. Both
  fail closed on a scanning-machinery failure, not just a pattern hit (#994).
  `guard_inbound_tool_result` also strips hidden text from vendor fields (see
  `hidden_text` below) *before* scanning (#1218).
- `hidden_text` (ADR-075 decision 5, #1218) — strips control characters, zero-width/
  invisible Unicode, and bidirectional overrides from vendor-tagged text
  (`strip_hidden_text_from_vendor_fields`) or a bare string
  (`strip_hidden_text`). Vietnamese combining diacritics and ordinary emoji are
  untouched (different Unicode categories). Scoped to `source: "vendor"` text only.

See `docs/adr/070-agent-safe-sanitization-contract.md` and
`docs/adr/075-agent-approval-gate-and-security-prerequisites.md` decision 5. The remaining
golden-file gate is a separate issue (#995).
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
from juli_backend.services.agent.sanitize.chokepoints import (
    BannedPatternGuardFailure,
    BannedPatternHit,
    BannedPatternScanError,
    find_banned_pattern_hits,
    guard_inbound_tool_result,
    guard_outbound_agent_output,
)
from juli_backend.services.agent.sanitize.errors import (
    RETRYABLE_VENDOR_CODES,
    TranslatedError,
    to_error_envelope,
    translate_marketplace_error,
)
from juli_backend.services.agent.sanitize.hidden_text import (
    strip_hidden_text,
    strip_hidden_text_from_vendor_fields,
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
    "RETRYABLE_VENDOR_CODES",
    "BannedPatternEntry",
    "BannedPatternGuardFailure",
    "BannedPatternHit",
    "BannedPatternScanError",
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
    "TranslatedError",
    "VendorText",
    "cap_list",
    "cap_text",
    "estimate_result_tokens",
    "estimate_tokens",
    "find_banned_pattern_hits",
    "from_source",
    "guard_inbound_tool_result",
    "guard_outbound_agent_output",
    "iso_utc_timestamp",
    "load_banned_pattern_entries",
    "load_banned_patterns",
    "numeric_value",
    "sanitize_images",
    "strip_hidden_text",
    "strip_hidden_text_from_vendor_fields",
    "to_error_envelope",
    "to_json_safe",
    "translate_marketplace_error",
]
