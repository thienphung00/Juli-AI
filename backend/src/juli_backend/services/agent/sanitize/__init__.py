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

__all__ = [
    "BANNED_PATTERNS_JSON_PATH",
    "BannedPatternEntry",
    "load_banned_pattern_entries",
    "load_banned_patterns",
]
