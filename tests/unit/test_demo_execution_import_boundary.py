"""AC3 (#717, B-5): dry-run execution path has no import path to Partner write clients.

This is deliberately a *static* AST assertion, not a mock-call count — a runtime
assertion (patch + assert_not_called) can be defeated by a conditional that only
reaches the forbidden call under some untested branch; an import that is never
written cannot ever be reached at runtime, under any branch, no matter how the
module is exercised. Consistent with the MMU-2 import-linter contract
(`.importlinter.toml`, `agent-runtime/scripts/ci/check_import_boundaries.py`),
which is also a direct-edge AST scan rather than a runtime trace.

The check below is deliberately more precise than the repo-wide MMU-2 matrix: the
matrix allows `services -> integrations` edges in general (real webhook/execution
code legitimately calls TikTok), so it would not catch this slice's specific
safety requirement on its own. This test walks the *transitive* import graph
starting at `services/demo_execution/`, following edges through **any**
`juli_backend.services.*` module (not just `demo_execution`'s own submodules —
a hidden path could just as easily route through a helper in some unrelated
`services.*` module that itself reaches a forbidden target), and fails if that
graph ever reaches:

- `juli_backend.integrations.tiktok` (any submodule) — home of `TikTokClient` /
  `SandboxWriteClientFactory`, the concrete Partner write clients (ADR-037).
- `juli_backend.services.execution` (any submodule) — home of the two functions
  the PRD names explicitly as forbidden: `enqueue_approved_tool` (dispatch.py)
  and `run_tool_async` (runner.py).
- `juli_backend.repositories` (any submodule) — `repositories/repos.py` itself
  imports `juli_backend.integrations.tiktok` (a pre-existing, baselined edge),
  so reaching it would be an indirect path to the same forbidden surface.
- `juli_backend.api` (any submodule) — `api/routes/executions.py` is the HTTP
  handler that calls `enqueue_approved_tool`; a `services.*` module should never
  import `api.*` in the first place (forbidden by the MMU-2 matrix too).

We do not expand into `models`, `database`, `core`, `ai`, or `workers` — those
are shared, foundational packages that (by design) nearly everything imports,
and `juli_backend.models.models` in particular already has a pre-existing,
unrelated bottom-of-file import of `services.etl.persistence.ingest` (a SQLAlchemy
metadata-registration side effect) that itself reaches `integrations.tiktok`
transitively. A closure that expanded through `models` would therefore flag
*every* module in the codebase that touches an ORM model — including every
sanctioned, unrelated module — which is not what "no import path to Partner
write clients" is asking for. We instead check `models`/`database`/`core`/`ai`/
`workers` themselves only as *terminal* nodes (their own module name is
checked against the forbidden prefixes, but we do not parse their source to
keep expanding) — none of the forbidden prefixes above live under those
packages anyway, so this scoping loses no real coverage of this slice's risk.
This terminal treatment is deliberately a static-import-graph decision, not a
runtime one: a `sys.modules` check is genuinely useless as an alternative
here, since merely `import juli_backend.services.demo_execution` already pulls
20+ `integrations.tiktok.*` modules into `sys.modules` via that same
`models.py` bottom-of-file `services.etl.persistence.ingest` import — so
"is `integrations.tiktok` in `sys.modules`" would be true for every test run
in this suite regardless of what `demo_execution` itself does.

`RECURSE_PREFIXES` previously covered only `juli_backend.services.demo_execution`
itself, which meant the closure stopped at the first hop into any *other*
`services.*` module — an import chain like
`services/demo_execution/x.py -> services/some_other_service/y.py ->
services.execution.dispatch` would be recorded as reaching
`services.some_other_service.y` (not forbidden) and never followed further, so
the real forbidden edge one hop later was silently missed. `RECURSE_PREFIXES`
now covers all of `juli_backend.services`, so the closure follows import edges
through any service module, not just `demo_execution`'s own files.
`test_widened_recursion_config_catches_the_two_hop_evasion_shape` below builds
that exact two-hop shape hermetically (temp files, not real repo modules) and
asserts the previous narrow config missed it while the current config catches
it.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "backend/src"
MODULE_DIR = SRC_ROOT / "juli_backend/services/demo_execution"

FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "juli_backend.integrations.tiktok",
    "juli_backend.services.execution",
    "juli_backend.repositories",
    "juli_backend.api",
)

# Only recurse (parse further) through modules under these prefixes when
# following the import graph — see module docstring for rationale. This
# covers *all* of juli_backend.services (not just demo_execution's own
# submodules) so a two-hop chain through an unrelated services.* module is
# followed too, instead of stopping one hop short of a forbidden target.
RECURSE_PREFIXES: tuple[str, ...] = ("juli_backend.services",)


def _direct_juli_backend_imports(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("juli_backend"):
                    modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("juli_backend"):
                modules.add(node.module)
    return modules


def _module_source_file(module_name: str, *, src_root: Path = SRC_ROOT) -> Path | None:
    rel_parts = module_name.split(".")
    # module_name is "juli_backend.<...>"; src_root already contains juli_backend/.
    candidate = src_root.joinpath(*rel_parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    candidate = src_root.joinpath(*rel_parts, "__init__.py")
    if candidate.is_file():
        return candidate
    return None


def _is_forbidden(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_PREFIXES
    )


def _should_recurse(
    module_name: str, *, recurse_prefixes: tuple[str, ...] = RECURSE_PREFIXES
) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".") for prefix in recurse_prefixes
    )


def _transitive_closure(
    start_files: list[Path],
    *,
    src_root: Path = SRC_ROOT,
    recurse_prefixes: tuple[str, ...] = RECURSE_PREFIXES,
) -> set[str]:
    """Walk the transitive `juli_backend.*` import graph from `start_files`.

    `src_root` and `recurse_prefixes` are parameterized (defaulting to the
    real repo's `SRC_ROOT`/`RECURSE_PREFIXES`) so tests can point this at a
    hermetic, temp-directory package to exercise the recursion logic itself
    without adding permanent fixture modules to the real `services/` tree.
    """
    reached: set[str] = set()
    visited_files: set[Path] = set()
    queue: list[Path] = list(start_files)

    while queue:
        current = queue.pop()
        if current in visited_files or not current.is_file():
            continue
        visited_files.add(current)

        for module in _direct_juli_backend_imports(current):
            reached.add(module)
            if _should_recurse(module, recurse_prefixes=recurse_prefixes):
                target = _module_source_file(module, src_root=src_root)
                if target is not None and target not in visited_files:
                    queue.append(target)

    return reached


def test_demo_execution_module_exists_and_has_source_files() -> None:
    assert MODULE_DIR.is_dir(), f"missing module directory: {MODULE_DIR}"
    py_files = sorted(MODULE_DIR.glob("*.py"))
    assert py_files, f"no .py files found under {MODULE_DIR}"


def test_demo_execution_has_no_import_path_to_partner_write_clients() -> None:
    py_files = sorted(MODULE_DIR.glob("*.py"))
    reached = _transitive_closure(py_files)

    violations = sorted(m for m in reached if _is_forbidden(m))
    assert not violations, (
        "services/demo_execution has an import path to a forbidden module "
        f"(Partner write client / real execution dispatch): {violations}"
    )


def test_demo_execution_dry_run_module_does_not_directly_import_forbidden_targets() -> None:
    """Belt-and-braces direct-edge check mirroring check_import_boundaries.py's own style."""
    dry_run_file = MODULE_DIR / "dry_run.py"
    assert dry_run_file.is_file()

    direct_imports = _direct_juli_backend_imports(dry_run_file)
    violations = sorted(m for m in direct_imports if _is_forbidden(m))
    assert not violations, f"dry_run.py directly imports forbidden module(s): {violations}"


def test_forbidden_prefixes_actually_resolve_to_real_modules() -> None:
    """Sanity check the forbidden-module list isn't accidentally checking nothing."""
    assert _module_source_file("juli_backend.integrations.tiktok") is not None
    assert _module_source_file("juli_backend.services.execution.dispatch") is not None
    assert _module_source_file("juli_backend.services.execution.runner") is not None


def _write_module(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _build_two_hop_evasion_package(tmp_path: Path) -> Path:
    """Build, hermetically under `tmp_path`, the exact two-hop evasion shape Review
    described empirically against the real closure logic: a `services/demo_execution/`
    file imports a helper from a *different* `services.*` module, and that helper module
    is the one that actually reaches the forbidden targets — one hop further than
    `demo_execution`'s own files.

    Deliberately not added as a permanent fixture module under the real
    `services/demo_execution/` package (that would ship a fake, deliberately-unsafe
    module into production source) — this writes throwaway files under pytest's
    `tmp_path` and points `_transitive_closure` at them via `src_root`.
    """
    evade_file = tmp_path / "juli_backend" / "services" / "demo_execution" / "evade.py"
    _write_module(
        evade_file,
        "import juli_backend.services.other_service.foo\n",
    )
    _write_module(
        tmp_path / "juli_backend" / "services" / "other_service" / "foo.py",
        "import juli_backend.services.execution.dispatch\n"
        "import juli_backend.integrations.tiktok.client\n",
    )
    return evade_file


def test_narrow_demo_execution_only_recurse_prefix_misses_the_two_hop_evasion_shape(
    tmp_path: Path,
) -> None:
    """Documents the exact gap Review found: recursing only through
    `juli_backend.services.demo_execution` stops one hop too early, so a chain that
    routes through a *different* services.* module before reaching a forbidden target
    is recorded as reaching only that intermediate (non-forbidden) module and the real
    violation one hop later is never seen. This uses the narrow prefix explicitly (not
    the module's current global default) so it stays a permanent, accurate record of
    what the old configuration missed, independent of what `RECURSE_PREFIXES` is set to
    today.
    """
    evade_file = _build_two_hop_evasion_package(tmp_path)

    reached = _transitive_closure(
        [evade_file],
        src_root=tmp_path,
        recurse_prefixes=("juli_backend.services.demo_execution",),
    )
    violations = sorted(m for m in reached if _is_forbidden(m))

    assert "juli_backend.services.other_service.foo" in reached
    assert not violations, (
        "expected the narrow demo_execution-only recurse prefix to miss this "
        f"evasion shape, but it caught: {violations}"
    )


def test_current_recurse_prefixes_catch_the_two_hop_evasion_shape(tmp_path: Path) -> None:
    """The fix: with the module's actual, current `RECURSE_PREFIXES` (covering all of
    `juli_backend.services`, not just `demo_execution`'s own submodules), the same
    two-hop evasion shape from the test above is now caught. This uses the module's
    real default (no explicit `recurse_prefixes` override), so a future accidental
    narrowing of `RECURSE_PREFIXES` regresses this test.
    """
    evade_file = _build_two_hop_evasion_package(tmp_path)

    reached = _transitive_closure([evade_file], src_root=tmp_path)
    violations = sorted(m for m in reached if _is_forbidden(m))

    assert violations == [
        "juli_backend.integrations.tiktok.client",
        "juli_backend.services.execution.dispatch",
    ]
