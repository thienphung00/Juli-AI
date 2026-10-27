"""An exception as a label safe to persist (owner decision D16; ADR-116 §4).

An exception's message is not ours to store: a pydantic ``ValidationError``
echoes the input it rejected, an HTTP error can carry a vendor body, a database
error can carry bound values -- any of which may be a buyer's name, address or
message. Every ``last_error`` column, Celery result and log field that records a
failure stores :func:`error_label` instead: the class name and, when the
exception carries one, the vendor's numeric code (``TikTokAPIError code=105001``).
That is the shape ``services/order_costs`` already wrote; the other writers now
share it, and ``services/privacy/payload_cleanup`` rewrites older rows into it.
"""

from __future__ import annotations

import re

#: A label as :func:`error_label` writes it, optionally behind a ``phase: `` prefix.
SAFE_ERROR_LABEL = re.compile(
    r"^(?:[a-z_]{1,40}: )?[A-Za-z_][A-Za-z0-9_]{0,99}(?: code=-?\d{1,20})?$"
)
_REPR_CLASS = re.compile(r"^(?:(?P<prefix>[a-z_]{1,40}): )?(?P<cls>[A-Za-z_][A-Za-z0-9_.]{0,99})")
_REPR_CODE = re.compile(r"\bcode=(?P<code>-?\d{1,20})\b")


def error_label(exc: BaseException) -> str:
    """Class and vendor code only -- a message can echo request or response data."""
    code = getattr(exc, "code", None)
    suffix = f" code={code}" if isinstance(code, int) and not isinstance(code, bool) else ""
    return f"{type(exc).__name__}{suffix}"


def relabel_stored_error(stored: str | None) -> str | None:
    """A ``last_error`` written by an older release, reduced to :func:`error_label`'s shape.

    Older rows hold ``repr(exc)`` (``TikTokAPIError(code=105001, message=...)``), a
    ``phase: repr`` pair, or a truncated message. The class (the leading identifier)
    and a numeric ``code=`` survive; everything else is dropped. Already-safe values
    are returned unchanged, so the clean-up is idempotent.
    """
    if stored is None or stored == "":
        return stored
    if SAFE_ERROR_LABEL.match(stored):
        return stored
    head = _REPR_CLASS.match(stored)
    cls = head.group("cls").rsplit(".", 1)[-1] if head else "Error"
    prefix = f"{head.group('prefix')}: " if head and head.group("prefix") else ""
    code = _REPR_CODE.search(stored)
    suffix = f" code={code.group('code')}" if code else ""
    return f"{prefix}{cls}{suffix}"
