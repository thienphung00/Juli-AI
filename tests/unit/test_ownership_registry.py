"""Ownership registry completeness — ORM tables and Celery task names (#551)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from check_ownership_registry import (  # noqa: E402
    MODELS_PATH,
    WORKERS_DIR,
    discover_celery_task_names,
    discover_orm_table_names,
    load_ownership_registry,
    validate_registry_completeness,
)


def test_registry_file_exists() -> None:
    registry_path = REPO_ROOT / "docs" / "architecture" / "ownership-registry.yml"
    assert registry_path.is_file(), "ownership-registry.yml must exist"


def test_every_orm_table_is_registered() -> None:
    registry = load_ownership_registry()
    tables = discover_orm_table_names()
    registered = set(registry["databaseTables"])
    missing = sorted(tables - registered)
    assert not missing, f"ORM tables missing from registry: {missing}"


def test_registry_verifiable_without_live_tiktok_supabase() -> None:
    """Registry drift check uses static AST/regex only — no vendor HTTP."""
    errors = validate_registry_completeness()
    assert errors == []
    # Discovery paths are local files under backend/
    assert MODELS_PATH.is_file()
    assert WORKERS_DIR.is_dir()


def test_registry_lists_celery_task_names() -> None:
    registry = load_ownership_registry()
    tasks = discover_celery_task_names()
    registered = set(registry["celeryTasks"])
    missing = sorted(tasks - registered)
    assert not missing, f"Celery tasks missing from registry: {missing}"


def test_registry_lists_redis_patterns_and_external_systems() -> None:
    registry = load_ownership_registry()
    patterns = {entry["pattern"] for entry in registry["redisNamespaces"]}
    required_patterns = {
        "ratelimit:*",
        "analytics:kpi_envelope:*",
        "material_analytics:mutex:*",
        "material_analytics:coalesce68:*",
        "celery-*",
    }
    missing_patterns = sorted(required_patterns - patterns)
    assert not missing_patterns, f"Redis patterns missing: {missing_patterns}"
    integration_ids = {entry["id"] for entry in registry["externalIntegrations"]}
    required = {
        "tiktok_shop_api",
        "supabase_postgres",
        "supabase_jwt",
        "redis",
        "celery_broker",
    }
    missing = sorted(required - integration_ids)
    assert not missing, f"External integrations missing: {missing}"


def test_registry_documents_redis_key_policy() -> None:
    registry = load_ownership_registry()
    policy = registry.get("metadata", {}).get("redisKeyPolicy", {})
    assert policy.get("futureConvention") == "juli:<module>:"
    allowlist = set(policy.get("legacyAllowlist") or [])
    assert "ratelimit:*" in allowlist
    assert "analytics:kpi_envelope:*" in allowlist


def test_each_entry_has_planning_module_owner() -> None:
    registry = load_ownership_registry()
    allowed = set(registry["planningModules"])
    problems: list[str] = []

    for table, entry in registry["databaseTables"].items():
        owner = entry.get("owner")
        if owner not in allowed:
            problems.append(f"databaseTables.{table}.owner={owner!r}")

    for task, entry in registry["celeryTasks"].items():
        owner = entry.get("owner")
        if owner not in allowed:
            problems.append(f"celeryTasks.{task}.owner={owner!r}")

    for idx, entry in enumerate(registry["redisNamespaces"]):
        owner = entry.get("owner")
        if owner not in allowed:
            problems.append(f"redisNamespaces[{idx}].owner={owner!r}")

    for entry in registry["externalIntegrations"]:
        owner = entry.get("owner")
        if owner not in allowed:
            problems.append(f"externalIntegrations.{entry.get('id')}.owner={owner!r}")

    assert not problems, "Invalid planning module owners:\n" + "\n".join(problems)


def test_boundary_guidance_documented() -> None:
    registry = load_ownership_registry()
    guidance = registry.get("metadata", {}).get("boundaryGuidance", {})
    assert guidance.get("doNotImport"), "doNotImport guidance required"
    assert guidance.get("readVsWrite"), "readVsWrite guidance required"


def test_registry_cli_prints_check_result_prefix() -> None:
    """CLI uses ownership_registry: PASS/FAIL prefix for CI log parsing."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "agent-runtime/scripts/ci/check_ownership_registry.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ownership_registry: PASS" in result.stdout


def test_registry_fails_when_celery_task_missing_from_registry() -> None:
    registry = load_ownership_registry()
    tasks = discover_celery_task_names()
    assert tasks, "expected at least one celery task in codebase"
    victim = sorted(tasks)[0]
    broken = {
        **registry,
        "celeryTasks": {k: v for k, v in registry["celeryTasks"].items() if k != victim},
    }
    errors = validate_registry_completeness(broken)
    assert any("celeryTasks missing owner registration" in err for err in errors)
