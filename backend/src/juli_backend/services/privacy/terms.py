"""The legal-text date and the D60 numbers the privacy API works with (P50-B).

``LEGAL_TERMS_DATE`` is the date of the D60 ``/terms`` + ``/privacy`` text. The demo
holds the same value in ``apps/demo/src/lib/privacy/legal.ts``; bump both when the
legal text changes (contract ``fasttrack/contracts/p50-privacy.md``).
"""

from __future__ import annotations

from datetime import date, timedelta

LEGAL_TERMS_DATE = date(2026, 10, 18)

#: D60.10: after a deletion request the seller has 30 days to export, then deletion.
DELETION_GRACE = timedelta(days=30)

#: Rows per exported table and shop. The export is a synchronous download; a shop
#: past this limit gets ``truncated: true`` on that table (DEBT: async export).
EXPORT_ROW_LIMIT = 5000

__all__ = ["DELETION_GRACE", "EXPORT_ROW_LIMIT", "LEGAL_TERMS_DATE"]
