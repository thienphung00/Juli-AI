"""Modular monolith test-layer discipline — unit contract tests (MMU-14 / #564).

Codifies placement rules for unit / integration / E2E suites and proves sample
architecture contracts (import boundaries, ownership registry) stay enforceable.

See python-testing.md "Modular Monolith Test Layers" for placement guidance.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTING_GUIDANCE = ROOT / ".cursor/skills/domain/testing-patterns/python-testing.md"
CHECK_SCRIPT = ROOT / "agent-runtime/scripts/ci/check_import_boundaries.py"
SYNTHETIC_CONFIG = ROOT / "tests/fixtures/import_boundaries/synthetic/.importlinter.toml"
SYNTHETIC_SCAN_ROOT = SYNTHETIC_CONFIG.parent / "backend/src/juli_backend"
CI_DIR = ROOT / "agent-runtime" / "scripts" / "ci"

sys.path.insert(0, str(CI_DIR))
from check_ownership_registry import load_ownership_registry  # noqa: E402


def _run_import_checker(*extra: str) -> subprocess.CompletedProcess[str]:
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


def test_no_full_suite_rewrite_required_for_mmu14_slice() -> None:
    """AC4 — slice adds targeted guidance/contract tests; existing suites stay in place."""
    assert (ROOT / "tests/unit/test_import_boundaries.py").is_file()
    assert (ROOT / "tests/unit/test_ownership_registry.py").is_file()
    assert (ROOT / "tests/unit/test_modular_monolith_test_layers.py").is_file()


def test_testing_guidance_codifies_unit_integration_e2e_layers() -> None:
    """Unit layer contract — guidance must state placement and public-surface rules."""
    text = TESTING_GUIDANCE.read_text(encoding="utf-8")

    assert "Modular Monolith Test Layers" in text
    assert "tests/unit/" in text
    assert "tests/integration/" in text
    assert "public surface" in text.lower() or "public facades" in text.lower()
    assert "test_import_boundaries" in text
    assert "test_ownership_registry" in text


def test_architecture_contract_tests_live_in_unit_layer() -> None:
    """Import and ownership registry proofs belong in tests/unit/, not integration."""
    unit_dir = ROOT / "tests" / "unit"
    required = (
        unit_dir / "test_import_boundaries.py",
        unit_dir / "test_ownership_registry.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"architecture contract tests missing from unit layer: {missing}"


def test_synthetic_forbidden_deep_import_proves_boundary_contract() -> None:
    """Import-boundary contract — deep cross-package imports fail strict check."""
    result = _run_import_checker("--strict")

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "import_boundaries: FAIL" in combined
    assert "forbidden_deep_import.py" in combined
    assert "integrations.tiktok.client" in combined


def test_ownership_registry_documents_cross_module_import_policy() -> None:
    """Ownership contract — registry must publish do-not-import and read/write guidance."""
    registry = load_ownership_registry()
    guidance = registry.get("metadata", {}).get("boundaryGuidance", {})

    do_not_import = guidance.get("doNotImport", "")
    read_vs_write = guidance.get("readVsWrite", "")

    assert do_not_import, "doNotImport guidance required"
    assert read_vs_write, "readVsWrite guidance required"
    assert "facade" in do_not_import.lower()
    assert "owner" in read_vs_write.lower()


def test_no_requirement_to_rewrite_entire_suite() -> None:
    """AC4 — targeted guidance/examples only; existing contract tests stay authoritative."""
    targeted = (
        ROOT / "tests/unit/test_modular_monolith_test_layers.py",
        ROOT / "tests/integration/test_modular_monolith_public_facades.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in targeted if not path.is_file()]
    assert not missing, f"targeted MMU-14 tests missing: {missing}"
    assert (ROOT / "tests/unit/test_import_boundaries.py").is_file()
    assert (ROOT / "tests/unit/test_ownership_registry.py").is_file()
