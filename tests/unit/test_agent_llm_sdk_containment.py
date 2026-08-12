"""AC (#988, ADR-068 decision 6(a)): provider SDK imports are legal only inside
`services/agent/llm/`.

This is deliberately a *source-level AST scan*, not a runtime import check, following
the convention already established by `tests/unit/test_demo_execution_import_boundary.py`
(AC3 of #717). The reasons for that choice are sharper here than there:

- **What this test is actually guarding against changed mid-wave (#988, "Update —
  Architect decision (Option A)").** The adapter this wave built
  (`services/agent/llm/openai_adapter.py`, #986) is written directly against `httpx`,
  not the `openai` SDK — the SDK is a declared dependency nowhere in
  `backend/pyproject.toml` / `backend/constraints.txt`. So as of this commit, nothing
  in the backend imports a provider SDK at all, and a scan that finds zero violations
  is the *expected* steady state — this is not a live boundary, it is a guard against
  future SDK creep. This test does not assert the SDK *is* used anywhere, only that
  *if* one ever is, it stays contained to the LLM module.
- **A runtime import check cannot express that guarantee at all.** `import openai`
  succeeding or failing on the machine running the test depends on whatever happens to
  be `pip install`-ed locally (a workstation's data-science environment can make
  `openai` importable even though it is declared nowhere the backend actually depends
  on it — the same trap that already broke CI once for `jsonschema`). The property
  this test needs to hold is independent of installed packages: it must pass whether
  or not any provider SDK is installed, and it must never silently skip when one is
  absent — a containment guard that skips itself when the thing it forbids isn't
  installed guards nothing. A static AST parse of `.py` source text has no such
  dependency.
- **A static scan also can't be defeated by a conditional import that only fires on an
  untested branch** — the same "an import that is never written cannot ever be reached,
  no matter how the module is exercised" argument `test_demo_execution_import_boundary`
  makes for its own forbidden-target scan applies here symmetrically to the *allowed*
  target: any `import openai` (or a handful of other common provider SDKs) anywhere in
  the source text is caught, regardless of whether the branch containing it ever
  executes in a test run.
- **A string-grep would false-positive on comments/docstrings** (this very module's
  docstring says "openai" several times) — using `ast` instead of `re`/`in` avoids that
  entirely.

`PROVIDER_SDK_MODULES` intentionally covers more than `openai` — the acceptance
criterion ("asserts `openai` is imported only within the agent LLM module") is the
concrete instance this guards; a couple of other common single-provider SDKs are
included too since the next SDK someone reaches for outside the LLM module is unlikely
to be `openai` specifically.

Does NOT touch (per the issue's explicit instruction, correcting the implementation
handoff): `test_rules_copy_layer_contract.py`, `test_recommendations.py`
`TestRuleBasedNoLlmDependency`, or the dashboard listing-rules test. ADR-068 decision 6
keeps those three unchanged as module-scoped determinism guarantees; this slice only
*adds* a new, separate containment test alongside them.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "backend/src"
ALLOWED_DIR = SRC_ROOT / "juli_backend/services/agent/llm"

# Top-level provider-SDK module names that are legal to import only inside
# ALLOWED_DIR. Matched against the *first* dotted component of an import, so
# `import openai.types` and `from openai import OpenAI` are both caught.
PROVIDER_SDK_MODULES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "litellm",
    "cohere",
    "mistralai",
)

# A sweep that silently discovers zero source files would pass vacuously. This is
# the floor for "plausibly walked the real backend source tree" (as of this commit
# there are 300+ .py files under backend/src/juli_backend); kept well below that so
# the test doesn't become a tripwire on ordinary repo growth/pruning.
MIN_PLAUSIBLE_MODULE_COUNT = 100


def _top_level_module(dotted_name: str) -> str:
    return dotted_name.split(".", 1)[0]


def _provider_sdk_imports(
    py_file: Path, *, provider_modules: tuple[str, ...] = PROVIDER_SDK_MODULES
) -> set[str]:
    """Return the forbidden provider-SDK top-level module names imported anywhere in
    `py_file` — `ast.walk` (not just module-level statements), so an import nested
    inside a function or a conditional is caught exactly like a top-level one.
    """
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level_module(alias.name)
                if top in provider_modules:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # node.level == 0 excludes relative imports (`from . import x`), which
            # can never resolve to a third-party package name.
            top = _top_level_module(node.module)
            if top in provider_modules:
                found.add(top)
    return found


def _discover_source_files(*, src_root: Path = SRC_ROOT) -> list[Path]:
    """Walk `src_root` for `.py` files rather than using a hard-coded file list, so
    new modules are automatically covered as they're added.
    """
    return sorted(p for p in src_root.rglob("*.py") if "__pycache__" not in p.parts)


def _scan_for_violations(
    *,
    src_root: Path = SRC_ROOT,
    allowed_dir: Path = ALLOWED_DIR,
    provider_modules: tuple[str, ...] = PROVIDER_SDK_MODULES,
) -> dict[Path, set[str]]:
    """Walk every `.py` file under `src_root`, skipping `allowed_dir`, and return a
    map of {offending file: forbidden module names imported in it}.

    Parameterized (defaulting to the real repo `SRC_ROOT`/`ALLOWED_DIR`) so tests can
    point this at a hermetic temp-directory tree to exercise the scan logic itself
    without adding permanent violation fixtures to the real `services/` tree.
    """
    violations: dict[Path, set[str]] = {}
    for py_file in _discover_source_files(src_root=src_root):
        if py_file.is_relative_to(allowed_dir):
            continue
        found = _provider_sdk_imports(py_file, provider_modules=provider_modules)
        if found:
            violations[py_file] = found
    return violations


def test_allowed_llm_module_directory_resolves_to_a_real_module() -> None:
    """Sanity check the allowlisted path isn't accidentally checking nothing."""
    assert ALLOWED_DIR.is_relative_to(SRC_ROOT)
    assert ALLOWED_DIR.is_dir(), f"expected the agent LLM module at {ALLOWED_DIR}"
    assert (ALLOWED_DIR / "openai_adapter.py").is_file(), (
        "expected the httpx-based adapter (#986) inside the allowlisted directory — "
        "if this moves, ALLOWED_DIR must move with it"
    )


def test_sweep_discovers_a_plausible_number_of_source_modules() -> None:
    """Guards against the sweep silently finding zero (or near-zero) files — a scan
    over an empty or wrong directory would pass every containment assertion
    vacuously, which is worse than no test at all.
    """
    discovered = _discover_source_files()
    assert len(discovered) >= MIN_PLAUSIBLE_MODULE_COUNT, (
        f"expected to discover at least {MIN_PLAUSIBLE_MODULE_COUNT} source files "
        f"under {SRC_ROOT}, only found {len(discovered)} — is SRC_ROOT wrong, or did "
        "the sweep silently fail to walk the tree?"
    )


def test_provider_sdk_import_is_contained_to_agent_llm_module() -> None:
    """The real repo-wide check: no provider SDK is imported anywhere in the backend
    source tree except inside `services/agent/llm/`.

    As of this commit the adapter is httpx-based (Option A) and nothing imports a
    provider SDK at all, so this is expected to pass with an empty violation set —
    that is the correct steady state, not a sign the check is vacuous (see
    `test_scan_detects_a_synthetic_violation_outside_the_allowed_module` below for
    proof the scan does fire when a violation exists).
    """
    violations = _scan_for_violations()

    assert not violations, (
        "provider SDK import(s) found outside services/agent/llm/ — this is the "
        "ADR-068 decision 6(a) containment guard against future SDK creep. "
        f"Offending module(s): "
        f"{ {str(f.relative_to(REPO_ROOT)): mods for f, mods in violations.items()} }"
    )


def _write_module(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_scan_detects_a_synthetic_violation_outside_the_allowed_module(
    tmp_path: Path,
) -> None:
    """Proves the guard is not vacuous: builds a throwaway package hermetically under
    `tmp_path` (never touching the real repo tree) with a provider-SDK import outside
    the allowed directory, and asserts the scan catches it and names the offending
    module — matching the acceptance criterion "fails loudly... naming the offending
    module."
    """
    offending = tmp_path / "juli_backend" / "services" / "not_llm" / "oops.py"
    _write_module(offending, "import openai\n\ndef f() -> None:\n    import anthropic\n")

    allowed_dir = tmp_path / "juli_backend" / "services" / "agent" / "llm"

    violations = _scan_for_violations(src_root=tmp_path, allowed_dir=allowed_dir)

    assert offending in violations
    assert violations[offending] == {"openai", "anthropic"}

    # Drive the same failure-message construction the real assertion uses, and
    # confirm it names the offending module (not just a generic "violation found").
    message = (
        "provider SDK import(s) found outside services/agent/llm/ — this is the "
        "ADR-068 decision 6(a) containment guard against future SDK creep. "
        f"Offending module(s): "
        f"{ {str(f.relative_to(tmp_path)): mods for f, mods in violations.items()} }"
    )
    offending_rel = str(offending.relative_to(tmp_path))
    assert offending_rel in message
    assert "openai" in message
    assert "anthropic" in message


def test_scan_catches_from_import_variants_including_submodules(tmp_path: Path) -> None:
    """Covers `from openai import X` and `from openai.foo import X` as well as plain
    `import openai` / `import openai.foo` — all four import shapes are legal only
    inside the allowed directory.
    """
    offending = tmp_path / "juli_backend" / "services" / "not_llm" / "shapes.py"
    _write_module(
        offending,
        "import openai\n"
        "import openai.types\n"
        "from openai import OpenAI\n"
        "from openai.types.chat import ChatCompletion\n",
    )

    allowed_dir = tmp_path / "juli_backend" / "services" / "agent" / "llm"
    violations = _scan_for_violations(src_root=tmp_path, allowed_dir=allowed_dir)

    assert violations == {offending: {"openai"}}


def test_scan_ignores_provider_sdk_imports_inside_the_allowed_module(
    tmp_path: Path,
) -> None:
    """The mirror image of the test above: the same import, but written inside the
    allowlisted directory, is not reported as a violation — proves the allowlist
    itself is doing the excluding, not just the forbidden-name detection.
    """
    allowed_dir = tmp_path / "juli_backend" / "services" / "agent" / "llm"
    inside = allowed_dir / "adapter.py"
    _write_module(inside, "import openai\n")

    violations = _scan_for_violations(src_root=tmp_path, allowed_dir=allowed_dir)

    assert violations == {}


def test_scan_ignores_relative_imports_comments_and_unrelated_third_party_packages(
    tmp_path: Path,
) -> None:
    """A relative import can never resolve to a third-party SDK name, a comment/
    docstring mentioning "openai" is not an import (proving this is an AST check, not
    a string-grep that would false-positive on such text), and an unrelated
    third-party import (e.g. `httpx`, the adapter's actual dependency) is not a
    provider SDK — none of these should ever be reported.
    """
    benign = tmp_path / "juli_backend" / "services" / "not_llm" / "benign.py"
    _write_module(
        benign,
        '"""This module deliberately does not use openai or anthropic."""\n'
        "# TODO: consider openai someday\n"
        "from . import sibling\n"
        "from .. import other\n"
        "import httpx\n"
        "from httpx import Client\n",
    )

    allowed_dir = tmp_path / "juli_backend" / "services" / "agent" / "llm"
    violations = _scan_for_violations(src_root=tmp_path, allowed_dir=allowed_dir)

    assert violations == {}
