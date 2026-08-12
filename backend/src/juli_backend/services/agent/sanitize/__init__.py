"""Agent output sanitization (ADR-070).

- `banned_patterns` (decision 6) — shared banned-pattern guard. Patterns live in one
  language-neutral JSON source (`packages/contracts/seller-copy-banned-patterns.json`)
  so this Python loader and the TypeScript guard (`packages/contracts/src/seller-copy.ts`)
  can never drift silently (#990).
- `provenance` (decision 3) — server-assigned `source` envelopes (`juli`/`vendor`/
  `seller`) wrapping every piece of free text in a tool result (#991).
- `machine_values` (decision 4) — absolute ISO-8601 UTC timestamps, money as a numeric
  amount + currency field, and rates as bare numbers under self-describing keys (#991).

See `docs/adr/070-agent-safe-sanitization-contract.md`. The two fail-closed chokepoints
that consume the banned-pattern guard, hard caps/truncation, and error translation are
separate issues (#992-#995).
"""Agent output sanitization — shared banned-pattern guard (ADR-070 decision 6).

Patterns live in one language-neutral JSON source
(`packages/contracts/seller-copy-banned-patterns.json`) so this Python loader and the
TypeScript guard (`packages/contracts/src/seller-copy.ts`) can never drift silently.
See `docs/adr/070-agent-safe-sanitization-contract.md` and issue #990. This slice is
the shared pattern source only — the two fail-closed chokepoints that consume it are
separate issues (#991-#995).
"""

from juli_backend.services.agent.sanitize.banned_patterns import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
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
    "PROVENANCE_SOURCES",
    "BannedPatternEntry",
    "JuliText",
    "Money",
    "Number",
    "ProvenanceEnvelope",
    "ProvenanceSource",
    "SellerText",
    "VendorText",
    "from_source",
    "iso_utc_timestamp",
    "load_banned_pattern_entries",
    "load_banned_patterns",
    "numeric_value",
    "to_json_safe",

__all__ = [
    "BANNED_PATTERNS_JSON_PATH",
    "BannedPatternEntry",
    "load_banned_pattern_entries",
    "load_banned_patterns",
]
