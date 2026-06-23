"""Doc contract tests for target-v2.md — Issue #143."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_V2_PATH = REPO_ROOT / "docs/architecture/target-v2.md"
EXECUTION_PATH = REPO_ROOT / "EXECUTION.md"
SYSTEM_DESIGN_PATH = REPO_ROOT / "docs/system-design.md"
MAP_PATH = REPO_ROOT / "docs/architecture/map.md"


@pytest.fixture
def target_v2_text() -> str:
    return TARGET_V2_PATH.read_text(encoding="utf-8")


@pytest.fixture
def execution_text() -> str:
    return EXECUTION_PATH.read_text(encoding="utf-8")


@pytest.fixture
def system_design_text() -> str:
    return SYSTEM_DESIGN_PATH.read_text(encoding="utf-8")


@pytest.fixture
def map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8")


def test_target_v2_exists_with_phase2_flow(target_v2_text: str):
    """End-to-end Phase 2 pipeline documented with flow diagram or equivalent."""
    assert (
        "## Phase 2 pipeline" in target_v2_text
        or "## End-to-end flow" in target_v2_text
    )
    for stage in (
        "poll",
        "ETL",
        "feature build",
        "inference",
        "copy layer",
        "executor",
    ):
        assert stage.lower() in target_v2_text.lower(), (
            f"missing pipeline stage: {stage}"
        )


def test_target_v2_phase1_mock_vs_phase2_live(target_v2_text: str):
    """Documents what stays mock in Phase 1 vs goes live in Phase 2."""
    assert "Phase 1" in target_v2_text
    assert "Phase 2" in target_v2_text
    assert "mock" in target_v2_text.lower()
    assert "live" in target_v2_text.lower() or "real" in target_v2_text.lower()


def test_target_v2_references_model_paths_and_schedule(target_v2_text: str):
    """References models/ artifact paths, 08:00 UTC inference, Ollama after inference."""
    assert "models/seller_stage/" in target_v2_text
    assert "models/anomaly/" in target_v2_text
    assert "models/ad_performance/" in target_v2_text
    assert "08:00 UTC" in target_v2_text
    assert "Ollama" in target_v2_text
    assert "06:00" in target_v2_text or "07:00" in target_v2_text


def test_target_v2_documents_health_data_source_contract(target_v2_text: str):
    """health_data_source contract documented; VP/AHR API exposure not assumed."""
    assert "health_data_source" in target_v2_text
    assert "api" in target_v2_text
    assert "proxy" in target_v2_text
    assert "unavailable" in target_v2_text
    assert "VP" in target_v2_text or "AHR" in target_v2_text
    assert (
        "not assume" in target_v2_text.lower()
        or "not exposed" in target_v2_text.lower()
    )


def test_target_v2_anomaly_buyer_behavior_scope(target_v2_text: str):
    """Anomaly ML is buyer-behavior only; policy signals are separate."""
    assert "item_swap" in target_v2_text
    assert "empty_return" in target_v2_text
    assert (
        "ADR-011" in target_v2_text
        or "011-buyer-behavior-anomaly-scope" in target_v2_text
    )
    assert "policy" in target_v2_text.lower()
    assert "affiliate" in target_v2_text.lower() or "Affiliate" in target_v2_text


def test_target_v2_references_inference_signatures_from_142(target_v2_text: str):
    """Cross-references #142 inference signatures and artifact publisher from #141."""
    assert "feature-store-schema.md" in target_v2_text
    assert "predict_seller_stage" in target_v2_text or "seller_stage" in target_v2_text
    assert "predict_anomaly" in target_v2_text or "anomaly" in target_v2_text
    assert "predict_ad_action" in target_v2_text or "ad_performance" in target_v2_text


def test_cross_links_point_to_target_v2(
    execution_text: str, system_design_text: str, map_text: str
):
    """EXECUTION.md, system-design.md, and map.md link to target-v2.md."""
    for doc_text in (execution_text, system_design_text, map_text):
        assert "target-v2.md" in doc_text


def test_target_v2_excludes_forbidden_scope(target_v2_text: str):
    """No Seller Center scraping, buyer PII, Celery, or Kafka in Phase 2 scope."""
    lower = target_v2_text.lower()
    assert "seller center scraping" in lower or "no seller center scraping" in lower
    assert "buyer pii" in lower or "no buyer pii" in lower
    assert "celery" in lower
    assert "kafka" in lower
    assert "forbidden" in lower or "out of scope" in lower
