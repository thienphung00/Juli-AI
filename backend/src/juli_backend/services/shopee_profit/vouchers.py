"""Join the voucher export to the Connector's voucher settings (G-14).

The export (``voucher_*.xlsx``) has results (cost, orders) but no voucher id and no code; the
Connector's ``voucher_settings`` has the id, the value and the usage but no results. The export's
start is a date at 00:00 and the settings' start is a clock time, so the stored keys never equal.
The join key is: normalised name + start DATE + discount value. The export carries no numeric
discount value today (``Loại ưu đãi`` is text): when one side's value is unknown the key is name +
start date, and a value on both sides must be equal.

A match must be unique on both sides. If one export row fits several settings rows (twin
vouchers: same name, same day, same value), or several export rows fit one settings row, none of
them is matched: they are counted as ``ambiguous`` and listed as unmatched. Never a guess.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def voucher_name(name: str) -> str:
    """NFKC, case-folded, single spaces."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


@dataclass(frozen=True)
class VoucherExport:
    ref: str  # caller's handle for the row (promotion id, index ...)
    name: str
    starts_on: date
    discount_value: Decimal | None = None


@dataclass(frozen=True)
class VoucherSetting:
    ref: str
    name: str
    starts_on: date
    discount_value: Decimal | None = None


@dataclass(frozen=True)
class VoucherJoin:
    matched: tuple[tuple[str, str], ...]  # (export ref, settings ref)
    unmatched_exports: tuple[str, ...]
    unmatched_settings: tuple[str, ...]
    #: Export rows (not settings) that fit more than one setting, or share a setting.
    ambiguous: int

    @property
    def unmatched(self) -> int:
        return len(self.unmatched_exports) + len(self.unmatched_settings)


def _fits(export: VoucherExport, setting: VoucherSetting) -> bool:
    if voucher_name(export.name) != voucher_name(setting.name):
        return False
    if export.starts_on != setting.starts_on:
        return False
    if export.discount_value is None or setting.discount_value is None:
        return True
    return export.discount_value == setting.discount_value


def join_vouchers(
    exports: Sequence[VoucherExport], settings: Sequence[VoucherSetting]
) -> VoucherJoin:
    candidates: dict[str, list[str]] = {
        e.ref: [s.ref for s in settings if _fits(e, s)] for e in exports
    }
    claimed: dict[str, list[str]] = defaultdict(list)
    for export_ref, found in candidates.items():
        for setting_ref in found:
            claimed[setting_ref].append(export_ref)
    matched: list[tuple[str, str]] = []
    ambiguous = 0
    for export_ref, found in candidates.items():
        if len(found) == 1 and len(claimed[found[0]]) == 1:
            matched.append((export_ref, found[0]))
        elif found:
            ambiguous += 1
    taken_exports = {e for e, _ in matched}
    taken_settings = {s for _, s in matched}
    return VoucherJoin(
        matched=tuple(matched),
        unmatched_exports=tuple(e.ref for e in exports if e.ref not in taken_exports),
        unmatched_settings=tuple(s.ref for s in settings if s.ref not in taken_settings),
        ambiguous=ambiguous,
    )
