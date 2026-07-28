"""Load `.importlinter.toml` contract for modular monolith import checks."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from common import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / ".importlinter.toml"


@dataclass(frozen=True)
class ImportBoundaryConfig:
    root_package: str
    scan_root: Path
    top_level_packages: frozenset[str]
    allowed_edges: dict[str, frozenset[str]]
    max_cross_package_depth: int


def load_import_boundary_config(path: Path | None = None) -> ImportBoundaryConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    contract = raw["contract"]
    packages = raw["packages"]
    edges = raw["allowed_edges"]
    deep = raw["deep_imports"]

    allowed: dict[str, frozenset[str]] = {}
    for importer, targets in edges.items():
        allowed[importer] = frozenset(targets)

    return ImportBoundaryConfig(
        root_package=str(contract["root_package"]),
        scan_root=REPO_ROOT / str(contract["scan_root"]),
        top_level_packages=frozenset(packages["top_level"]),
        allowed_edges=allowed,
        max_cross_package_depth=int(deep["max_cross_package_depth"]),
    )
