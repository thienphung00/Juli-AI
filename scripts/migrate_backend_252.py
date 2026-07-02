#!/usr/bin/env python3
"""One-shot migration: src/ runtime → backend/ layout (issue #252).

Moves Python modules, rewrites imports, generates src/ compatibility shims,
and relocates Alembic migrations under backend/database/migrations/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ("src.shared.utils.data", "backend.database"),
    ("src.modules.catalog", "backend.integrations.catalog"),
    ("src.modules.ordering", "backend.integrations.ordering"),
    ("src.modules.identity", "backend.integrations.identity"),
    ("src.modules.ml", "backend.ai"),
    ("src.apps.api_gateway", "backend.api"),
    ("src.apps.cron_jobs", "backend.workers"),
    ("src.apps.runtime", "backend.runtime"),
]

MODULE_MD_MOVES: list[tuple[str, str]] = [
    ("src/apps/api_gateway/api/MODULE.md", "backend/api/api/MODULE.md"),
    ("src/apps/api_gateway/services/webhook/MODULE.md", "backend/api/services/webhook/MODULE.md"),
    ("src/apps/cron_jobs/services/polling/MODULE.md", "backend/workers/services/polling/MODULE.md"),
    ("src/shared/utils/data/MODULE.md", "backend/database/MODULE.md"),
    ("src/modules/identity/infrastructure/auth/MODULE.md", "backend/integrations/identity/infrastructure/auth/MODULE.md"),
    ("src/modules/catalog/domain/integrations/tiktok/MODULE.md", "backend/integrations/catalog/domain/integrations/tiktok/MODULE.md"),
    ("src/modules/catalog/domain/recommendations/MODULE.md", "backend/integrations/catalog/domain/recommendations/MODULE.md"),
    ("src/modules/catalog/domain/intelligence/scoring/MODULE.md", "backend/integrations/catalog/domain/intelligence/scoring/MODULE.md"),
    ("src/modules/catalog/domain/intelligence/forecasting/MODULE.md", "backend/integrations/catalog/domain/intelligence/forecasting/MODULE.md"),
    ("src/modules/ordering/api/ingestion/MODULE.md", "backend/integrations/ordering/api/ingestion/MODULE.md"),
    ("src/modules/ordering/use_cases/etl/MODULE.md", "backend/integrations/ordering/use_cases/etl/MODULE.md"),
    ("src/modules/ml/dataset/MODULE.md", "backend/ai/dataset/MODULE.md"),
    ("src/modules/ml/features/MODULE.md", "backend/ai/features/MODULE.md"),
    ("src/modules/ml/seller_stage/MODULE.md", "backend/ai/seller_stage/MODULE.md"),
    ("src/modules/ml/anomaly/MODULE.md", "backend/ai/anomaly/MODULE.md"),
    ("src/modules/ml/ad_performance/MODULE.md", "backend/ai/ad_performance/MODULE.md"),
    ("src/modules/ml/artifacts/MODULE.md", "backend/ai/artifacts/MODULE.md"),
]

SHIM_TARGETS: list[tuple[str, str]] = [
    ("src/apps/runtime.py", "backend.runtime"),
    ("src/apps/api_gateway/api/main.py", "backend.api.api.main"),
    ("src/apps/api_gateway/api/app.py", "backend.api.api.app"),
    ("src/apps/api_gateway/api/dependencies.py", "backend.api.api.dependencies"),
    ("src/apps/api_gateway/api/__init__.py", "backend.api.api"),
    ("src/apps/api_gateway/services/webhook/main.py", "backend.api.services.webhook.main"),
    ("src/apps/api_gateway/services/webhook/app.py", "backend.api.services.webhook.app"),
    ("src/apps/api_gateway/services/webhook/__init__.py", "backend.api.services.webhook"),
    ("src/apps/cron_jobs/services/polling/sync.py", "backend.workers.services.polling.sync"),
    ("src/apps/cron_jobs/services/polling/__init__.py", "backend.workers.services.polling"),
    ("src/shared/utils/data/__init__.py", "backend.database"),
    ("src/shared/utils/data/models.py", "backend.database.models"),
    ("src/shared/utils/data/repos.py", "backend.database.repos"),
    ("src/shared/utils/data/database.py", "backend.database.database"),
    ("src/shared/utils/data/exceptions.py", "backend.database.exceptions"),
]


def git_mv(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise SystemExit(f"destination already exists: {dst}")
    subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=REPO)


def rewrite_imports(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in IMPORT_REPLACEMENTS:
        text = text.replace(old, new)
    # CLI module paths: python -m src.modules.ml... → backend.ai...
    text = re.sub(r"python -m src\.modules\.ml\.", "python -m backend.ai.", text)
    text = re.sub(r"python -m src\.modules\.ml\b", "python -m backend.ai", text)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def move_runtime_tree() -> None:
    (REPO / "backend" / "__init__.py").write_text('"""Juli Python backend package (issue #252)."""\n', encoding="utf-8")

    git_mv(REPO / "src/apps/runtime.py", REPO / "backend/runtime.py")
    git_mv(REPO / "src/apps/api_gateway/api", REPO / "backend/api/api")
    git_mv(REPO / "src/apps/api_gateway/services", REPO / "backend/api/services")
    git_mv(REPO / "src/apps/cron_jobs/services", REPO / "backend/workers/services")

    for name in ("ad_performance", "anomaly", "artifacts", "dataset", "features", "seller_stage"):
        git_mv(REPO / f"src/modules/ml/{name}", REPO / f"backend/ai/{name}")

    git_mv(REPO / "src/modules/catalog", REPO / "backend/integrations/catalog")
    git_mv(REPO / "src/modules/ordering", REPO / "backend/integrations/ordering")
    git_mv(REPO / "src/modules/identity", REPO / "backend/integrations/identity")

    data_src = REPO / "src/shared/utils/data"
    for item in data_src.iterdir():
        if item.name == "__pycache__":
            continue
        git_mv(item, REPO / "backend/database" / item.name)

    git_mv(REPO / "alembic", REPO / "backend/database/migrations")

    for pkg in (
        "backend/api",
        "backend/workers",
        "backend/ai",
        "backend/integrations",
        "backend/integrations/catalog",
        "backend/integrations/ordering",
        "backend/integrations/identity",
        "backend/database",
    ):
        init = REPO / pkg / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def rewrite_all_imports() -> int:
    changed = 0
    for root in (REPO / "backend", REPO / "tests"):
        for path in root.rglob("*.py"):
            if rewrite_imports(path):
                changed += 1
    for old, new in MODULE_MD_MOVES:
        src = REPO / old
        dst = REPO / new
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=REPO)
            if rewrite_imports(dst):
                changed += 1
    return changed


def write_shim(rel_path: str, module: str) -> None:
    path = REPO / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    content = (
        f'"""Compatibility shim — runtime moved to `{module.rsplit(".", 1)[0]}` (issue #252)."""\n'
        f"from {module} import *  # noqa: F403\n"
    )
    if stem not in ("__init__", "main"):
        content += f"from {module} import {stem}\n"
    if stem == "main":
        content += "from backend.api.api.main import app\n"
    path.write_text(content, encoding="utf-8")


def generate_shims() -> None:
    for rel, module in SHIM_TARGETS:
        write_shim(rel, module)

    # Package-level shims for nested trees re-exported via submodules.
    package_inits = {
        "src/__init__.py": '"""Legacy import root — use `backend` for runtime code (issue #252)."""\n',
        "src/apps/__init__.py": '"""Legacy backend entrypoints — use `backend.api` / `backend.workers` (issue #252)."""\n',
        "src/apps/api_gateway/__init__.py": '"""Shim package — see `backend.api` (issue #252)."""\n',
        "src/apps/cron_jobs/__init__.py": '"""Shim package — see `backend.workers` (issue #252)."""\n',
        "src/modules/__init__.py": '"""Shim package — see `backend.integrations` / `backend.ai` (issue #252)."""\n',
        "src/shared/__init__.py": "",
        "src/shared/utils/__init__.py": "",
    }
    for rel, body in package_inits.items():
        (REPO / rel).write_text(body, encoding="utf-8")

    # ML submodule shims: src.modules.ml.<name> → backend.ai.<name>
    for name in ("ad_performance", "anomaly", "artifacts", "dataset", "features", "seller_stage"):
        init = REPO / f"src/modules/ml/{name}/__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text(
            f'"""Compatibility shim — use `backend.ai.{name}` (issue #252)."""\n'
            f"from backend.ai.{name} import *  # noqa: F403\n",
            encoding="utf-8",
        )
        cli = REPO / f"src/modules/ml/{name}/cli.py"
        if (REPO / f"backend/ai/{name}/cli.py").is_file():
            cli.write_text(
                f'"""Compatibility shim — use `backend.ai.{name}.cli` (issue #252)."""\n'
                f"from backend.ai.{name}.cli import *  # noqa: F403\n",
                encoding="utf-8",
            )

    (REPO / "src/modules/ml/__init__.py").write_text(
        '"""Compatibility shim — use `backend.ai` (issue #252)."""\n',
        encoding="utf-8",
    )

    def shim_tree(old_prefix: str, new_prefix: str, subpath: str) -> None:
        src_root = REPO / old_prefix / subpath
        if not src_root.exists():
            return
        for path in sorted((REPO / new_prefix / subpath).rglob("*.py")):
            rel = path.relative_to(REPO / new_prefix / subpath)
            shim_path = src_root / rel
            if shim_path.name == "__pycache__":
                continue
            mod = new_prefix.replace("/", ".") + "." + subpath.replace("/", ".")
            mod += "." + ".".join(rel.with_suffix("").parts)
            if rel.parts and rel.parts[-1] == "__init__":
                mod = mod.removesuffix(".__init__")
            write_shim(str(shim_path.relative_to(REPO)), mod)

    shim_tree("src/modules/catalog", "backend/integrations/catalog", "domain")
    shim_tree("src/modules/ordering", "backend/integrations/ordering", "api")
    shim_tree("src/modules/ordering", "backend/integrations/ordering", "use_cases")
    shim_tree("src/modules/identity", "backend/integrations/identity", "infrastructure")


def update_alembic_ini() -> None:
    ini = REPO / "alembic.ini"
    text = ini.read_text(encoding="utf-8")
    text = text.replace("script_location = %(here)s/alembic", "script_location = %(here)s/backend/database/migrations")
    ini.write_text(text, encoding="utf-8")


def update_backend_readme() -> None:
    readme = REPO / "backend/README.md"
    text = readme.read_text(encoding="utf-8")
    text = text.replace(
        "**Status:** Scaffold only — runtime code currently in `src/`.",
        "**Status:** Runtime code lives here; `src/` retains documented compatibility shims (issue #252).",
    )
    readme.write_text(text, encoding="utf-8")

    compat = REPO / "src/COMPAT.md"
    compat.write_text(
        "# `src/` compatibility shims (issue #252)\n\n"
        "Runtime Python code moved to `backend/`. Import paths under `src/` are thin\n"
        "re-exports so existing deploy entrypoints (e.g. `uvicorn src.apps.api_gateway.api.main:app`)\n"
        "and Alembic tooling keep working until deploy config is updated in a later slice.\n\n"
        "New code and tests should import from `backend.*` only.\n",
        encoding="utf-8",
    )


def cleanup_empty_dirs() -> None:
    for rel in (
        "src/apps/api_gateway",
        "src/apps/cron_jobs/services",
        "src/apps/cron_jobs",
        "src/modules/ml",
        "src/modules",
        "src/shared/utils/data",
        "src/shared/utils",
        "src/shared",
    ):
        path = REPO / rel
        if path.is_dir() and not any(path.rglob("*")):
            shutil.rmtree(path, ignore_errors=True)


def main() -> None:
    move_runtime_tree()
    rewrite_all_imports()
    generate_shims()
    update_alembic_ini()
    update_backend_readme()
    cleanup_empty_dirs()
    print("Migration complete.")


if __name__ == "__main__":
    main()
