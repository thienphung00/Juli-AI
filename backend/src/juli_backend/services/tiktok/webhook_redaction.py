"""Best-effort PII redaction for webhook raw audit storage (#392).

Recursively walks parsed JSON and redacts values whose keys match a denylist
(case-insensitive substring). Malformed JSON yields ``None`` (do not store body).
Redacted output is truncated at ``RAW_BODY_MAX_BYTES``.
"""

from __future__ import annotations

import json
from typing import Any

RAW_BODY_MAX_BYTES = 32 * 1024
REDACTED_VALUE = "[REDACTED]"
TRUNCATION_SUFFIX = "…[TRUNCATED]"

# Case-insensitive substring match against object keys.
_PII_KEY_SUBSTRINGS: tuple[str, ...] = (
    "name",
    "phone",
    "tel",
    "mobile",
    "email",
    "address",
    "district",
    "city",
    "street",
    "zip",
    "postal",
    "recipient",
)


def _key_matches_denylist(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _PII_KEY_SUBSTRINGS)


def _scrub_leaves(value: Any) -> Any:
    """Replace every scalar leaf with ``[REDACTED]`` while keeping containers."""
    if isinstance(value, dict):
        return {key: _scrub_leaves(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_scrub_leaves(item) for item in value]
    return REDACTED_VALUE


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, child in value.items():
            if isinstance(key, str) and _key_matches_denylist(key):
                # Preserve structure under object-valued denylist keys (useful for #382).
                out[key] = (
                    _scrub_leaves(child)
                    if isinstance(child, (dict, list))
                    else REDACTED_VALUE
                )
            else:
                out[key] = _redact_value(child)
        return out
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _truncate(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= RAW_BODY_MAX_BYTES:
        return text
    budget = RAW_BODY_MAX_BYTES - len(TRUNCATION_SUFFIX.encode("utf-8"))
    if budget <= 0:
        return TRUNCATION_SUFFIX[:RAW_BODY_MAX_BYTES]
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    return truncated + TRUNCATION_SUFFIX


def redact_webhook_body(body: bytes) -> str | None:
    """Return redacted JSON text, or ``None`` when *body* is not valid JSON."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    redacted = _redact_value(parsed)
    return _truncate(json.dumps(redacted, ensure_ascii=False, separators=(",", ":")))
