"""Import boundary contract tests (MMU-2 / GitHub #552)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = ROOT / "agent-runtime/scripts/ci/check_import_boundaries.py"
SYNTHETIC_FIXTURE = ROOT / "tests/fixtures/import_boundaries/synthetic"
SYNTHETIC_CONFIG = SYNTHETIC_FIXTURE / ".importlinter.toml"
SYNTHETIC_SCAN_ROOT = SYNTHETIC_FIXTURE / "backend/src/juli_backend"

sys.path.insert(0, str(ROOT / "agent-runtime/scripts/ci"))
from import_boundary_config import load_import_boundary_config  # noqa: E402


def _run_checker(*extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(CHECK_SCRIPT),
        "--config",
        str(SYNTHETIC_CONFIG),
        "--scan-root",
        str(SYNTHETIC_SCAN_ROOT),
        *extra,
    ]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)


def test_synthetic_forbidden_deep_import_fails_strict_check() -> None:
    """Synthetic fixture must fail strict import-boundary check with clear importer/target."""
    result = _run_checker("--strict")

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "import_boundaries: FAIL" in combined
    assert "forbidden_deep_import.py" in combined
    assert "integrations.tiktok.client" in combined
    assert "api" in combined


def test_import_boundary_config_defines_core_package_matrix() -> None:
    config_path = ROOT / ".importlinter.toml"
    text = config_path.read_text(encoding="utf-8")

    for package in ("services", "ai", "integrations", "api", "workers", "core"):
        assert package in text


def test_import_boundaries_doc_update_matrix_when_modules_gains_module() -> None:
    """Document how to update the matrix when MODULES.md gains a module."""
    doc = (ROOT / "docs/architecture/import-boundaries.md").read_text(encoding="utf-8")
    assert "MODULES.md" in doc
    assert "[allowed_edges]" in doc or "allowed_edges" in doc
    assert "Updating the matrix" in doc


def test_no_microservices_single_deployable_unchanged_by_import_checker() -> None:
    """No microservices; single deployable unchanged — checker scans in-tree backend only."""
    config = load_import_boundary_config(ROOT / ".importlinter.toml")
    assert config.scan_root == ROOT / "backend/src/juli_backend"
    assert config.root_package == "juli_backend"


def test_check_import_boundaries_warn_mode_exits_zero_on_repo_scan() -> None:
    """Production tree may violate until MMU-3; default local run warns only."""
    result = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--config",
            str(ROOT / ".importlinter.toml"),
            "--scan-root",
            str(ROOT / "backend/src/juli_backend"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "import_boundaries: PASS" in result.stdout
