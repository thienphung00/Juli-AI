"""Path-prefix executor domain detection for harness_optimizer."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))

from build_runtime import load_simple_yaml  # noqa: E402
from harness_optimizer import (  # noqa: E402
    expected_executor_from_paths,
    expected_executor_from_review,
)


def _maps() -> dict:
    cfg = load_simple_yaml(REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml")
    return cfg["routing"]["domain_mappings"]


def test_packages_ui_maps_to_ui_ux() -> None:
    assert (
        expected_executor_from_paths(
            ["packages/ui/src/button.tsx", "apps/demo/app/page.tsx"],
            domain_mappings=_maps(),
        )
        == "ui-ux"
    )


def test_infra_scripts_map_to_backend() -> None:
    assert (
        expected_executor_from_paths(
            ["infra/scripts/safe-alembic-upgrade-local.sh"],
            domain_mappings=_maps(),
        )
        == "backend"
    )


def test_database_migrations_map_to_data_platform() -> None:
    assert (
        expected_executor_from_paths(
            ["backend/src/juli_backend/database/migrations/versions/x.py"],
            domain_mappings=_maps(),
        )
        == "data-platform"
    )


def test_analytics_backfill_maps_to_integrations() -> None:
    assert (
        expected_executor_from_paths(
            ["backend/src/juli_backend/services/analytics_backfill/live_partition.py"],
            domain_mappings=_maps(),
        )
        == "integrations"
    )


def test_run_analytics_backfill_script_maps_to_integrations() -> None:
    assert (
        expected_executor_from_paths(
            ["infra/scripts/run-analytics-backfill.sh"],
            domain_mappings=_maps(),
        )
        == "integrations"
    )


def test_integrations_client_maps_to_integrations() -> None:
    assert (
        expected_executor_from_paths(
            ["backend/src/juli_backend/integrations/tiktok/client.py"],
            domain_mappings=_maps(),
        )
        == "integrations"
    )


def test_modules_touched_integration_tokens_map_to_integrations() -> None:
    cfg = load_simple_yaml(REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml")
    assert (
        expected_executor_from_review(
            {"modulesTouched": ["analytics_backfill", "integrations"]},
            implementation={"filesModified": []},
            config=cfg,
        )
        == "integrations"
    )


def test_modules_touched_path_tokens_do_not_default_to_backend() -> None:
    cfg = load_simple_yaml(REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml")
    assert (
        expected_executor_from_review(
            {"modulesTouched": ["packages/ui", "apps/demo"]},
            implementation={"filesModified": []},
            config=cfg,
        )
        == "ui-ux"
    )


def test_webhook_service_path_beats_backend_services_prefix() -> None:
    assert (
        expected_executor_from_paths(
            ["backend/src/juli_backend/services/webhook/handler.py"],
            domain_mappings=_maps(),
        )
        == "integrations"
    )


def test_polling_worker_path_maps_to_integrations() -> None:
    assert (
        expected_executor_from_paths(
            ["backend/src/juli_backend/workers/services/polling/job.py"],
            domain_mappings=_maps(),
        )
        == "integrations"
    )


def test_generic_services_paths_remain_backend() -> None:
    assert (
        expected_executor_from_paths(
            [
                "backend/src/juli_backend/services/scoring/foo.py",
                "backend/src/juli_backend/services/aggregates/bar.py",
            ],
            domain_mappings=_maps(),
        )
        == "backend"
    )
