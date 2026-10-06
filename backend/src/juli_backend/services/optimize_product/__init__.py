"""Optimize Product stage diagnosis — ADR-106 decisions 1, 2, 4, 5, 6.

Pure functions only. Nothing in this package reads a database, calls TikTok,
or writes anything: callers (the nightly scoring pass, the catalog scan
script under ``scripts/optimize_product_catalog_scan.py``, tests) hand in
funnel windows and listing evidence and receive ranked
:class:`~juli_backend.services.optimize_product.cards.TestCard` values.

Vocabulary is fixed by ``CONTEXT.md`` (Product funnel identity, Outcome label,
Stage diagnosis, Optimization cycle, Optimize Product throughput). The five
**angles** a card may propose are the enum
:class:`~juli_backend.services.optimize_product.diagnosis.Angle`; a card
carries exactly one.
"""

from juli_backend.services.optimize_product.cards import TestCard, build_cards
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.diagnosis import (
    Angle,
    Branch,
    Diagnosis,
    Gap,
    Label,
    Skip,
    Trigger,
    diagnose_product,
    rank_diagnoses,
)
from juli_backend.services.optimize_product.funnel import (
    FunnelWindow,
    ProductFunnel,
    ShopMedians,
)
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    EvidenceSource,
    ListingSignals,
    derive_local_evidence,
    listing_signals_from_product,
    parse_tiktok_diagnoses,
)

__all__ = [
    "Angle",
    "Branch",
    "Diagnosis",
    "Evidence",
    "EvidenceSource",
    "FunnelWindow",
    "Gap",
    "Label",
    "ListingSignals",
    "ProductFunnel",
    "ShopMedians",
    "Skip",
    "StageDiagnosisConfig",
    "TestCard",
    "Trigger",
    "build_cards",
    "derive_local_evidence",
    "diagnose_product",
    "listing_signals_from_product",
    "parse_tiktok_diagnoses",
    "rank_diagnoses",
]
