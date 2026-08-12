"""Machine-shaped values for agent tool results (ADR-070 decision 4).

Three invariants, enforced structurally rather than left as convention:

- **Dates** are absolute ISO-8601 UTC timestamps — never relative strings
  ("2 days ago", "hôm nay"). ``iso_utc_timestamp`` only accepts a
  timezone-aware ``datetime`` (a naive value is ambiguous about its offset,
  which is exactly the kind of implicit assumption that leaks local/relative
  time) and always renders in UTC.
- **Money** is a numeric amount beside an explicit ``currency`` field — never
  a formatted string. ``Money`` type-checks ``amount`` so a formatted value
  like ``"123,45 ₫"`` is rejected at construction, not merely by convention.
- **Rates** are bare numbers under self-describing keys, matching the
  pre-divided convention already used by ``gold_kpi_envelope_serving.py``
  (e.g. ``cancellation_rate``, ``ctor``): the ratio is computed once,
  server-side, so the model never does arithmetic on raw counts, and the key
  name — not a unit suffix on the value — says what the number means.
  ``numeric_value`` is the shared primitive both ``Money.amount`` and rate
  values are validated through.

Display formatting (currency symbols, localized/relative dates) is the copy
layer's job and must never appear in values built through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

Number = int | float | Decimal


def iso_utc_timestamp(value: datetime) -> str:
    """Render an absolute ISO-8601 UTC timestamp.

    Requires a timezone-aware ``datetime`` so the caller states its offset
    explicitly — treating a naive value as "probably UTC" is exactly the kind
    of implicit assumption this contract exists to rule out. A non-UTC aware
    datetime is converted to UTC before formatting, so the output is always
    absolute and always in UTC, never a relative or localized string.
    """
    if value.tzinfo is None:
        raise ValueError(
            "iso_utc_timestamp requires a timezone-aware datetime; got a naive "
            f"value ({value!r}). Attach a tzinfo (e.g. datetime.UTC) at the source "
            "instead of assuming UTC here."
        )
    return value.astimezone(UTC).isoformat()


def numeric_value(value: object, *, label: str) -> Number:
    """Reject anything that isn't a bare number.

    This is the failure mode decision 4 forbids for both money amounts and
    rates: a formatted string (``"123,45 ₫"``, ``"5.23%"``) sneaking into a
    field that must hold a plain number. ``bool`` is explicitly excluded even
    though it is an ``int`` subclass in Python — ``True``/``False`` are never
    a legitimate money or rate value.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise TypeError(f"{label} must be a numeric value, got {type(value).__name__}: {value!r}")
    return value


@dataclass(frozen=True)
class Money:
    """A monetary amount as a bare number beside an explicit currency code.

    Never a formatted string like ``"123,45 ₫"`` — ``amount`` is type-checked
    at construction, and ``currency`` is a required, non-empty code (e.g.
    ``"VND"``, ``"USD"``). Display formatting (the ₫ symbol, thousands
    separators) is the copy layer's job, not this contract's.
    """

    amount: Number
    currency: str

    def __post_init__(self) -> None:
        numeric_value(self.amount, label="Money.amount")
        if not isinstance(self.currency, str) or not self.currency:
            raise ValueError("Money.currency must be a non-empty currency code string")

    def to_dict(self) -> dict[str, Number | str]:
        return {"amount": self.amount, "currency": self.currency}
