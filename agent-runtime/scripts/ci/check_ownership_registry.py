#!/usr/bin/env python3
"""Validate ownership registry completeness vs ORM tables and Celery tasks (#551)."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "docs" / "architecture" / "ownership-registry.yml"
MODELS_PATH = REPO_ROOT / "backend" / "src" / "juli_backend" / "models" / "models.py"
WORKERS_DIR = REPO_ROOT / "backend" / "src" / "juli_backend" / "workers"
TABLENAME_RE = re.compile(r'__tablename__\s*=\s*["\']([^"\']+)["\']')
CELERY_TASK_NAME_RE = re.compile(
    r'@celery_app\.task\s*\(\s*name\s*=\s*["\']([^"\']+)["\']'
)


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load ownership-registry.yml; install PyYAML or use backend dev env"
        ) from exc
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("ownership registry root must be a mapping")
    return loaded


def load_ownership_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or REGISTRY_PATH
    return _load_yaml(registry_path.read_text(encoding="utf-8"))


def discover_orm_table_names(models_path: Path | None = None) -> set[str]:
    source = (models_path or MODELS_PATH).read_text(encoding="utf-8")
    return set(TABLENAME_RE.findall(source))


def discover_celery_task_names(workers_dir: Path | None = None) -> set[str]:
    root = workers_dir or WORKERS_DIR
    names: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        names.update(CELERY_TASK_NAME_RE.findall(text))
        # Also match name= on following lines inside @celery_app.task(...)
        if "@celery_app.task" in text:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    func = dec.func
                    if not (
                        isinstance(func, ast.Attribute)
                        and func.attr == "task"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "celery_app"
                    ):
                        continue
                    for kw in dec.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            if isinstance(kw.value.value, str):
                                names.add(kw.value.value)
    return names


def validate_registry_completeness(registry: dict[str, Any] | None = None) -> list[str]:
    reg = registry if registry is not None else load_ownership_registry()
    errors: list[str] = []

    tables = discover_orm_table_names()
    registered_tables = set(reg.get("databaseTables") or {})
    missing_tables = sorted(tables - registered_tables)
    extra_tables = sorted(registered_tables - tables)
    if missing_tables:
        errors.append(f"ORM tables missing from registry: {', '.join(missing_tables)}")
    if extra_tables:
        errors.append(f"Registry lists unknown ORM tables: {', '.join(extra_tables)}")

    tasks = discover_celery_task_names()
    registered_tasks = set(reg.get("celeryTasks") or {})
    missing_tasks = sorted(tasks - registered_tasks)
    extra_tasks = sorted(registered_tasks - tasks)
    if missing_tasks:
        errors.append(f"Celery tasks missing from registry: {', '.join(missing_tasks)}")
    if extra_tasks:
        errors.append(f"Registry lists unknown Celery tasks: {', '.join(extra_tasks)}")

    allowed = set(reg.get("planningModules") or [])
    for table, entry in (reg.get("databaseTables") or {}).items():
        owner = (entry or {}).get("owner")
        if owner not in allowed:
            errors.append(f"databaseTables.{table} owner {owner!r} not in planningModules")

    for task, entry in (reg.get("celeryTasks") or {}).items():
        owner = (entry or {}).get("owner")
        if owner not in allowed:
            errors.append(f"celeryTasks.{task} owner {owner!r} not in planningModules")

    patterns = {e.get("pattern") for e in reg.get("redisNamespaces") or []}
    if "ratelimit:*" not in patterns:
        errors.append("redisNamespaces must include ratelimit:*")

    integration_ids = {e.get("id") for e in reg.get("externalIntegrations") or []}
    required_integrations = {
        "tiktok_shop_api",
        "supabase_postgres",
        "supabase_jwt",
        "redis",
        "celery_broker",
    }
    missing_integrations = sorted(required_integrations - integration_ids)
    if missing_integrations:
        errors.append(
            "externalIntegrations missing ids: " + ", ".join(missing_integrations)
        )

    guidance = (reg.get("metadata") or {}).get("boundaryGuidance") or {}
    if not guidance.get("doNotImport"):
        errors.append("metadata.boundaryGuidance.doNotImport is required")
    if not guidance.get("readVsWrite"):
        errors.append("metadata.boundaryGuidance.readVsWrite is required")

    return errors


def main() -> int:
    if not REGISTRY_PATH.is_file():
        print(f"missing registry: {REGISTRY_PATH}", file=sys.stderr)
        return 1
    errors = validate_registry_completeness()
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"ownership registry OK ({REGISTRY_PATH.relative_to(REPO_ROOT)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
