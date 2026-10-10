"""Buyer-PII masking for every ops response (D25.6).

Staff see shop data, never buyer data. The ops router serialises every response
through :func:`mask_pii`:

- a value under a buyer/recipient key (``buyer_*``, ``recipient*``, ``address``,
  ``phone*``, ``customer_name`` …) is replaced by ``"•••"``;
- any string that contains a phone number is masked;
- any e-mail address outside the staff domain is shortened to ``abcdef…@…``
  (staff addresses ``@app-juli.com`` stay readable: they are the auditors).
"""

from __future__ import annotations

import re
from typing import Any

MASK = "•••"
STAFF_DOMAIN = "app-juli.com"

_PII_KEY = re.compile(
    r"^(buyer.*|recipient.*|.*_address|address.*|shipping_address|phone.*|.*_phone"
    r"|phone_number|customer_name|customer_email|customer_phone|buyer_message"
    r"|buyer_email|buyer_nickname|user_message|full_name|name_of_buyer|id_number)$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_PHONE = re.compile(r"(?<![\w.])(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?![\w.])")


def mask_email(match: re.Match[str]) -> str:
    local, domain = match.group(1), match.group(2)
    if domain.lower() == STAFF_DOMAIN:
        return match.group(0)
    return f"{local[:6]}…@…"


def mask_text(value: str) -> str:
    masked = _EMAIL.sub(mask_email, value)
    return _PHONE.sub(MASK, masked)


#: Keys whose values are identifiers / links Juli minted, never personal data,
#: and must reach the client byte for byte.
UNMASKED_KEYS = frozenset({"accept_url", "id", "shop_id", "run_id", "tiktok_shop_id", "token"})


def mask_pii(value: Any, *, key: str | None = None) -> Any:
    """Return *value* with buyer PII masked (recursively)."""
    if key in UNMASKED_KEYS and isinstance(value, str):
        return value
    if key is not None and _PII_KEY.match(key) and value not in (None, "", [], {}):
        return MASK
    if isinstance(value, dict):
        return {k: mask_pii(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if isinstance(value, str):
        return mask_text(value)
    return value
