"""Doc contract tests for feature-store-schema and system-design — Issue #142."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.modules.ml.artifacts.schema import feature_schema_hash
from src.modules.ml.dataset.schema import ADS_COLUMNS
from src.modules.ml.features.schema import (
    AD_FEATURE_COLUMNS,
    ANOMALY_FEATURE_COLUMNS,
    SELLER_STAGE_FEATURE_COLUMNS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_STORE_PATH = REPO_ROOT / "docs/data-models/feature-store-schema.md"
SYSTEM_DESIGN_PATH = REPO_ROOT / "docs/system-design.md"


@pytest.fixture
def feature_store_text() -> str:
    return FEATURE_STORE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def system_design_text() -> str:
    return SYSTEM_DESIGN_PATH.read_text(encoding="utf-8")


def test_feature_store_documents_all_three_feature_groups(feature_store_text: str):
    """Seller-stage, anomaly Group A, and ad feature groups documented with exact field names."""
    for column in SELLER_STAGE_FEATURE_COLUMNS:
        assert column in feature_store_text, f"missing seller-stage feature: {column}"
    for column in ANOMALY_FEATURE_COLUMNS:
        assert column in feature_store_text, f"missing anomaly feature: {column}"
    for column in AD_FEATURE_COLUMNS:
        assert column in feature_store_text, f"missing ad feature: {column}"

    assert "## Group A — Anomaly Detector Features" in feature_store_text
    assert "## Group D — Seller Stage Classifier Features" in feature_store_text
    assert "## Group E — Ad Performance Features" in feature_store_text


def test_inference_signatures_document_input_and_output_fields(feature_store_text: str):
    """Each suite has input schema, output schema, and model version pointer."""
    for suite in ("seller_stage", "anomaly", "ad_performance"):
        assert f'"model": "{suite}"' in feature_store_text, f"missing inference block: {suite}"

    assert '"stage"' in feature_store_text
    assert '"confidence"' in feature_store_text
    assert '"anomaly_class"' in feature_store_text
    assert '"feature_summary"' in feature_store_text
    assert '"is_anomaly"' in feature_store_text
    assert '"action"' in feature_store_text
    assert '"predicted_roas"' in feature_store_text
    assert "models/seller_stage/" in feature_store_text
    assert "models/anomaly/" in feature_store_text
    assert "models/ad_performance/" in feature_store_text


def test_feature_schema_hashes_match_artifact_metadata_contract(feature_store_text: str):
    """Documented schema hashes match feature_schema_hash() from #141 artifact publisher."""
    for suite in ("seller_stage", "anomaly", "ad_performance"):
        expected = feature_schema_hash(suite)  # type: ignore[arg-type]
        assert expected in feature_store_text, f"missing schema hash for {suite}: {expected}"


def test_system_design_ml_targets_have_no_tbd_placeholders(system_design_text: str):
    """system-design.md § ML models promotion targets filled — no _TBD_."""
    ml_section = system_design_text.split("### 3. ML models", 1)[1].split("### 4.", 1)[0]
    assert "_TBD_" not in ml_section
    assert re.search(r"precision\s*≥\s*\*?\*?0\.5", ml_section)
    assert "recall" in ml_section
    assert re.search(r"MAPE\s*≤\s*\*?\*?50", ml_section)
    assert "feature-store-schema.md" in ml_section


def test_system_design_cross_links_inference_signatures(system_design_text: str):
    """system-design.md cross-links inference signatures from feature-store-schema.md."""
    assert "feature-store-schema.md" in system_design_text
    assert "Inference signatures" in system_design_text or "inference signature" in system_design_text.lower()


def test_anomaly_group_references_adr_008_scope(feature_store_text: str):
    """Group A feature descriptions reflect ADR-008 buyer-behavior anomaly scope."""
    group_a = feature_store_text.split("## Group A", 1)[1].split("## Group B", 1)[0]
    assert "008-buyer-behavior-anomaly-scope" in group_a
    assert "affiliate" in group_a.lower() or "Affiliate" in group_a


def test_ad_features_align_with_ads_parquet_layout(feature_store_text: str):
    """Ad feature source columns align with ads.parquet contract (no P1.5 → P2 drift)."""
    parquet_source_columns = {"spend_vnd", "impressions", "clicks", "conversions", "roas", "cpc_vnd"}
    for column in parquet_source_columns:
        assert column in ADS_COLUMNS
        assert column in feature_store_text

    for column in AD_FEATURE_COLUMNS:
        assert column in feature_store_text


def test_return_schema_fields_referenced_in_anomaly_features(feature_store_text: str):
    """Anomaly features reference Return schema contract fields (return_type, buyer_id)."""
    assert "return_type" in feature_store_text
    assert "buyer_id" in feature_store_text
    assert "Return.shop_id" in feature_store_text or "Return.buyer_id" in feature_store_text
