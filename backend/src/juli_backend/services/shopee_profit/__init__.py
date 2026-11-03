"""Shopee profit calculation: fees, per-order waterfall, floor price, what-if, sources.

Pure -- no database, no I/O, no clock. Money is ``Decimal`` (VND); rates are fractions
(``0.15``), results named ``*_pct`` are percent points rounded to 0.1. Nothing here
predicts: the ``predicted`` layer of a what-if only multiplies a range the caller passes.

- :mod:`.fees` -- versioned Shopee fee formula per order date.
- :mod:`.order_profit` -- order line + SKU cost -> profit waterfall.
- :mod:`.floor` -- absolute / operating floor price, max discount.
- :mod:`.whatif` -- voucher, price-change, ads-budget scenarios (``certain`` vs ``predicted``).
- :mod:`.five_numbers` -- the five numbers (contract section 5) for a before/after pair.
- :mod:`.flows` -- five additive traffic flows from aggregates + residual row.
- :mod:`.sources` -- product x price-lever matrix, additive by construction.
- :mod:`.shop_profit` -- product profit, shop profit, cost coverage, GMV reconciliation.

See ``MODULE.md``.
"""

from __future__ import annotations
