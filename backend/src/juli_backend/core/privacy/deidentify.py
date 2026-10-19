"""De-identification at the LLM boundary (fast track P50-P, D68.2).

D68.2: business and seller data are de-identified before any analysis or
training pipeline; buyer data is anonymised before entering any pipeline; buyer
contact data never reaches the AI provider. Every request Juli sends to OpenAI
passes through this module first (see ``tests/unit/test_p50p_llm_boundary.py``).

- :func:`deidentify_text` replaces e-mail addresses and Vietnamese phone numbers
  with ``[ẩn]``. A string that is a JSON object or array (a tool result) is
  parsed, run through :func:`deidentify_payload` and dumped again.
- :func:`deidentify_payload` walks JSON-like data. A value under a buyer /
  recipient / contact key (the D25.6 key pattern the ops console masks with)
  becomes ``[ẩn]``; a buyer or user **id** becomes a stable HMAC alias (ADR-038
  ``stable_alias``) so the model can still tell records apart. Numbers are never
  touched: prices, quantities and KPIs reach the model exactly.

The regexes here are the single source: ``services/ops/masking.py`` imports them.
"""

from __future__ import annotations

import json
import re
from typing import Any

from juli_backend.services.analytics_kpi_masking.mask import stable_alias

REDACTED = "[ẩn]"

#: Keys whose value is buyer / recipient personal data (D25.6, ops console).
PII_KEY_RE = re.compile(
    r"^(buyer.*|recipient.*|.*_address|address.*|shipping_address|phone.*|.*_phone"
    r"|phone_number|customer_name|customer_email|customer_phone|buyer_message"
    r"|buyer_email|buyer_nickname|user_message|full_name|name_of_buyer|id_number)$",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
#: A sentence-ending period after the number still counts (``... 0912345678.``);
#: a decimal point (``.5``) on either side does not.
PHONE_RE = re.compile(r"(?<!\w)(?<!\d\.)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\w)(?!\.\d)")

#: Seller / user contact keys the ops console shows staff but the provider never needs.
_CONTACT_KEY_RE = re.compile(
    r"^(e-?mail|.*_e-?mail|user_id|.*_user_id|user_ids|.*_user_ids|contact.*)$",
    re.IGNORECASE,
)
_ID_KEY_RE = re.compile(r"(^|_)ids?$", re.IGNORECASE)


def _is_personal_key(key: str) -> bool:
    return bool(PII_KEY_RE.match(key) or _CONTACT_KEY_RE.match(key))


def _scrub_string(value: str) -> str:
    return PHONE_RE.sub(REDACTED, EMAIL_RE.sub(REDACTED, value))


def deidentify_text(value: str) -> str:
    """*value* with e-mails and VN phone numbers replaced; JSON text keyed too."""
    stripped = value.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict | list):
            cleaned = deidentify_payload(parsed)
            if cleaned == parsed:
                return value
            return json.dumps(cleaned, ensure_ascii=False)
    return _scrub_string(value)


def _alias(key: str, value: Any) -> Any:
    if isinstance(value, list):
        return [_alias(key, item) for item in value]
    if value is None or value == "" or isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return _redact_leaves(value)
    kind = "user" if "user" in key.lower() and "buyer" not in key.lower() else "buyer"
    return stable_alias(kind, str(value))


def _redact_leaves(value: Any) -> Any:
    """Every string leaf becomes ``[ẩn]``; numbers, booleans and ``None`` stay."""
    if isinstance(value, dict):
        return {k: _redact_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_leaves(item) for item in value]
    if isinstance(value, str):
        return REDACTED if value else value
    return value


def deidentify_payload(value: Any, *, key: str | None = None) -> Any:
    """A de-identified copy of JSON-like *value* (the input is never mutated)."""
    if key is not None and _is_personal_key(key):
        if _ID_KEY_RE.search(key):
            return _alias(key, value)
        return _redact_leaves(value)
    if isinstance(value, dict):
        return {k: deidentify_payload(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [deidentify_payload(item) for item in value]
    if isinstance(value, str):
        if key is not None and _ID_KEY_RE.search(key):
            return value  # Juli / TikTok ids of shops, orders, products: not personal.
        return deidentify_text(value)
    return value


__all__ = [
    "EMAIL_RE",
    "PHONE_RE",
    "PII_KEY_RE",
    "REDACTED",
    "deidentify_payload",
    "deidentify_text",
]
