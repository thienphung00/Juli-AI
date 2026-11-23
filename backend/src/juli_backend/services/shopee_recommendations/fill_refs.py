"""K1 (batch-1123-a2): what a person types after "Đã làm" is an id or a code, never both.

Shopee's numeric id goes in ``*_id`` fields (``voucher_id``, ``combo_id``, ``target.id``). A code
the person typed (a voucher code, with or without the shop prefix Seller Centre shows) goes in
``code`` / ``code_suffix`` / ``voucher_code``; a combo or programme known only by its name goes in
``name``. The Connector matches id first, then code, then name. Pure helpers, no I/O.
"""

from __future__ import annotations

import re
from typing import Any

#: Seller Centre shows a voucher code as the shop's 4-letter prefix + at most 5 typed characters
VOUCHER_PREFIX_LEN = 4
VOUCHER_SUFFIX_MAX = 5
_DIGITS = re.compile(r"^\d{1,20}$")
_CODE = re.compile(r"[^A-Z0-9]")


def split_ref(value: Any) -> tuple[str | None, str | None]:
    """``(numeric id, code)`` of one typed value: digits only -> the id; anything else -> the
    code (upper-cased, A-Z 0-9 only). ``(None, None)`` for an empty value."""
    text = str(value or "").strip()
    if not text:
        return None, None
    if _DIGITS.match(text):
        return text, None
    code = _CODE.sub("", text.upper())
    return None, code or None


def voucher_suffix(code: str) -> str:
    """The part of a full voucher code the person types in the form (the shop prefix removed)."""
    full = _CODE.sub("", code.upper())
    return full[VOUCHER_PREFIX_LEN:] if len(full) > VOUCHER_SUFFIX_MAX else full


def voucher_target(object_id: str | None, code: str | None, name: str | None) -> dict[str, Any]:
    """The read-back / revert target of a voucher: the id when known, else its code, else name."""
    if object_id:
        return {"voucher_id": object_id}
    if code:
        return {"voucher_code": code, "code_suffix": voucher_suffix(code), "code": code}
    return {"name": name} if name else {}


def object_target(
    id_key: str, name_key: str, object_id: str | None, name: str | None
) -> dict[str, Any]:
    """A combo / programme target: ``{<id_key>: id}`` when known, else ``{<name_key>: name}``."""
    if object_id:
        return {id_key: object_id}
    return {name_key: name} if name else {}
