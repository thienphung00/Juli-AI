"""Shop diagnosis report — ADR-108.

Pure package: callers hand in a shop snapshot folder (written by
``scripts/shop_diagnosis_fetch.py``) and receive one
:class:`~juli_backend.services.shop_diagnosis.report.ShopDiagnosis`, from which
the Vietnamese HTML page, the JSON of every number and the seller message are
rendered. Nothing here calls TikTok or a database (import-boundary gate).

One module per step (ADR-108 d.13): :mod:`.channels` (five channels, funnel,
Shop Tab mapping), :mod:`.decomposition` (four-factor split, decision tree),
:mod:`.heroes`, :mod:`.promotions`, :mod:`.timeline`, :mod:`.confidence`,
:mod:`.render`, :mod:`.message`; every threshold lives in :mod:`.config`.
"""

from juli_backend.services.shop_diagnosis.channels import Channel
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.heroes import Ranking
from juli_backend.services.shop_diagnosis.message import build_message
from juli_backend.services.shop_diagnosis.rankings import STREAM_METRICS, Metric
from juli_backend.services.shop_diagnosis.render import render_html
from juli_backend.services.shop_diagnosis.report import ShopDiagnosis, build_report
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, load_snapshot

__all__ = [
    "STREAM_METRICS",
    "Channel",
    "Metric",
    "Ranking",
    "ShopDiagnosis",
    "ShopDiagnosisConfig",
    "Snapshot",
    "build_message",
    "build_report",
    "load_snapshot",
    "render_html",
]
