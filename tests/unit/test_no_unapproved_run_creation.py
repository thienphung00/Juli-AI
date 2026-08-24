"""Structural proof: no `api/routes/*.py` handler constructs a `WorkflowRun`
row directly (ADR-075 decision 1, #1222).

Deliberately an AST scan, not a test of every route's *current* behaviour --
the point (per the issue brief) is that a FUTURE route cannot reintroduce
the hole `create_run` (`POST /v1/demo/runs`, removed by this same slice --
see `api/routes/agent_runs.py`'s own docstring) used to be: a standalone
endpoint that built a `WorkflowRun` from caller-supplied data with no
approved `ActionCard` in the same transaction. A runtime/behavioural test
can only prove the routes it happens to exercise never do this; a
route module that is never even IMPORTED into a test at all would sail
straight past it. This scan reads every `.py` file under `api/routes/`
whether or not anything ever calls its routes.

The one sanctioned constructor call site is `services/agent/approval.py`
(reached from `api/routes/demo_execution.py`, never called from an
`api/routes/` module directly) -- so the assertion is exactly zero
`WorkflowRun(...)` calls anywhere under `api/routes/`, full stop.

Mirrors `test_demo_execution_import_boundary.py`'s own style: a static AST
assertion (import aliases resolved, then every `Call` node checked), plus a
hermetic positive-control test proving the scanner actually catches a
construction when one is deliberately introduced -- so this file cannot
quietly become a test that always passes no matter what.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "backend/src"
ROUTES_DIR = SRC_ROOT / "juli_backend/api/routes"

#: The fully-qualified model whose direct construction outside the one
#: sanctioned transaction module is the thing this test forbids.
FORBIDDEN_QUALNAME = "juli_backend.models.models.WorkflowRun"


def _local_names_bound_to_forbidden_qualname(tree: ast.AST) -> set[str]:
    """Every local name a file's own imports bind to `WorkflowRun` --
    handles `from juli_backend.models.models import WorkflowRun`,
    `... import WorkflowRun as WorkflowRunRow`, and (defensively)
    `import juli_backend.models.models as models_module` (in which case the
    forbidden call would show up as `models_module.WorkflowRun(...)`, an
    Attribute access rather than a bare Name -- handled separately below)."""
    bare_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "juli_backend.models.models":
            for alias in node.names:
                if alias.name == "WorkflowRun":
                    bare_names.add(alias.asname or alias.name)
    return bare_names


def _module_aliases_for_models_module(tree: ast.AST) -> set[str]:
    """Local names bound to the `juli_backend.models.models` module itself
    (via a plain `import ... as X`) -- a `X.WorkflowRun(...)` call is the
    Attribute-access shape those imports would enable."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "juli_backend.models.models":
                    aliases.add(alias.asname or "juli_backend")
        if isinstance(node, ast.ImportFrom) and node.module == "juli_backend.models":
            for alias in node.names:
                if alias.name == "models":
                    aliases.add(alias.asname or "models")
    return aliases


def _forbidden_call_sites(py_file: Path) -> list[int]:
    """Line numbers of every direct `WorkflowRun(...)` construction in
    `py_file`, how ever the name was imported/aliased."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    bare_names = _local_names_bound_to_forbidden_qualname(tree)
    module_aliases = _module_aliases_for_models_module(tree)

    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in bare_names:
            hits.append(node.lineno)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "WorkflowRun"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            hits.append(node.lineno)
    return hits


def test_routes_directory_exists_and_has_source_files() -> None:
    assert ROUTES_DIR.is_dir(), f"missing routes directory: {ROUTES_DIR}"
    py_files = sorted(ROUTES_DIR.glob("*.py"))
    assert py_files, f"no .py files found under {ROUTES_DIR}"


def test_no_route_module_constructs_a_workflow_run_directly() -> None:
    """The structural guarantee: `git grep`-equivalent, but AST-based so it
    cannot be fooled by the string `WorkflowRun` appearing in a comment or a
    docstring (both of which legitimately appear across this package after
    #1222 -- e.g. `agent_runs.py`'s own removal note)."""
    violations: dict[str, list[int]] = {}
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        hits = _forbidden_call_sites(py_file)
        if hits:
            violations[str(py_file.relative_to(REPO_ROOT))] = hits

    assert not violations, (
        "api/routes/*.py must never construct a WorkflowRun directly -- the only "
        "sanctioned constructor call site is services/agent/approval.py, reached "
        f"from demo_execution.py's approve route. Violations: {violations}"
    )


def test_scanner_catches_a_bare_name_construction(tmp_path: Path) -> None:
    """Positive control: a file that DOES construct `WorkflowRun(...)` via a
    plain `from ... import WorkflowRun` must be caught -- proves the scan
    logic itself, independent of whatever the real tree currently contains."""
    offender = tmp_path / "offending_route.py"
    offender.write_text(
        "from juli_backend.models.models import WorkflowRun\n\n"
        "def create_run_without_a_card(shop_id, product_id):\n"
        "    return WorkflowRun(shop_id=shop_id, product_id=product_id)\n",
        encoding="utf-8",
    )

    hits = _forbidden_call_sites(offender)

    assert hits == [4]


def test_scanner_catches_an_aliased_name_construction(tmp_path: Path) -> None:
    """Same positive control, but via `import ... as WorkflowRunRow` -- the
    exact alias shape every real route module in this package actually
    uses (`from juli_backend.models.models import WorkflowRun as
    WorkflowRunRow`)."""
    offender = tmp_path / "offending_aliased_route.py"
    offender.write_text(
        "from juli_backend.models.models import WorkflowRun as WorkflowRunRow\n\n"
        "def create_run_without_a_card(shop_id, product_id):\n"
        "    return WorkflowRunRow(shop_id=shop_id, product_id=product_id)\n",
        encoding="utf-8",
    )

    hits = _forbidden_call_sites(offender)

    assert hits == [4]


def test_scanner_ignores_an_unrelated_model_construction(tmp_path: Path) -> None:
    """Negative control: constructing some OTHER model must not trip this
    scanner -- it is specifically about `WorkflowRun`, not every ORM
    construction in a route module (`api/routes/agent_runs.py` legitimately
    has none at all after #1222; other route modules legitimately construct
    plenty of other models)."""
    innocent = tmp_path / "innocent_route.py"
    innocent.write_text(
        "from juli_backend.models.models import Product\n\n"
        "def make_product(shop_id):\n"
        "    return Product(shop_id=shop_id)\n",
        encoding="utf-8",
    )

    hits = _forbidden_call_sites(innocent)

    assert hits == []
