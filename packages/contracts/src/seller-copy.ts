/**
 * Banned patterns in seller-facing copy across Demo UI.
 * Enforced repo-wide to maintain consistency.
 *
 * The pattern list itself lives in one language-neutral source,
 * `packages/contracts/seller-copy-banned-patterns.json` (ADR-070 decision 6, #990),
 * so this TypeScript guard and the Python agent guard
 * (`backend/src/juli_backend/services/agent/sanitize`) can never silently drift.
 * `tests/unit/test_agent_banned_patterns_contract.py` compiles every entry under
 * both regex dialects. This module only builds `RegExp` objects from that source —
 * it must not add, remove, or alter any pattern.
 *
 * CRITICAL: The list forbids:
 * - Internal implementation details (tool_name, workflow_key, FBS/FBT internal IDs)
 * - False security claims (virus, antivirus, malware, "an toàn")
 *   Screening rejects files outside a format allowlist, caps their size, and
 *   re-encodes images so appended payloads do not survive. That is a boundary
 *   check, not a threat scan — nothing here inspects for malware, and PDFs are
 *   forwarded as supplied because they cannot be re-encoded. Affirmative safety
 *   language ("tệp an toàn", "kiểm tra an toàn") therefore stays forbidden: it
 *   would promise the seller a guarantee no layer actually makes.
 */
import sellerCopyBannedPatternsSource from "../seller-copy-banned-patterns.json";

export const SELLER_COPY_BANNED_PATTERNS: readonly RegExp[] =
  sellerCopyBannedPatternsSource.patterns.map(
    (entry) => new RegExp(entry.source, entry.flags),
  );
