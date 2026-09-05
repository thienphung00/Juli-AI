"""The code standard's pointers resolve, and its exemplars still have the shape it describes.

``CLAUDE.md``, ``code-quality.mdc``, ``code-standard.md`` and ``python-testing.md`` tell an
agent which module to copy for each kind of change. A pointer to a file that moved is
worse than none: the agent invents a shape. This module fails when any named path is gone
or when an exemplar has drifted from the property the docs cite it for.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/src/juli_backend"

STANDARD_DOCS = {
    "code-quality": ROOT / ".cursor/rules/code-quality.mdc",
    "code-standard": ROOT / "docs/architecture/code-standard.md",
    "python-testing": ROOT / ".cursor/skills/domain/testing-patterns/python-testing.md",
    "python-patterns": ROOT / ".cursor/skills/domain/testing-patterns/python-patterns.md",
    "repositories-module": BACKEND / "repositories/MODULE.md",
}

# Path-shaped backtick spans. Globs, placeholders and brace groups are prose, not pointers.
_BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)`")


def _claude_md_code_standard_section() -> str:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("## Code standard")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def _paths_named_in(text: str) -> set[str]:
    return {m.group(1).rstrip("/") for m in _BACKTICK_PATH.finditer(text)}


def _is_shop_scoped(base: ast.expr) -> bool:
    if isinstance(base, ast.Subscript):
        base = base.value
    return isinstance(base, ast.Name) and base.id == "ShopScopedRepo"


def _resolves(rel: str) -> bool:
    return (ROOT / rel).exists() or (BACKEND / rel).exists()


@pytest.mark.parametrize("doc", sorted(STANDARD_DOCS))
def test_every_path_the_standard_names_exists(doc: str) -> None:
    text = STANDARD_DOCS[doc].read_text(encoding="utf-8")
    missing = sorted(rel for rel in _paths_named_in(text) if not _resolves(rel))
    assert missing == [], (
        f"{STANDARD_DOCS[doc].relative_to(ROOT)} points at paths that do not exist"
    )


def test_claude_md_code_standard_section_paths_exist() -> None:
    missing = sorted(
        rel for rel in _paths_named_in(_claude_md_code_standard_section()) if not _resolves(rel)
    )
    assert missing == []


def test_claude_md_and_the_rule_name_the_same_exemplars() -> None:
    """Two indexes to the same exemplars must not drift apart."""
    section = _claude_md_code_standard_section()
    rule = STANDARD_DOCS["code-quality"].read_text(encoding="utf-8")
    for exemplar in (
        "repositories/_base.py",
        "services/agent_runs/",
        "api/routes/agent_runs.py",
        "services/kpi_cache/",
    ):
        assert exemplar in section, f"CLAUDE.md no longer names {exemplar}"
        assert exemplar in rule, f"code-quality.mdc no longer names {exemplar}"


class TestRepositoryExemplarShape:
    """``_base.py`` is cited for structural tenant scoping; the package must still honour it."""

    def _repo_classes(self) -> dict[str, ast.ClassDef]:
        classes: dict[str, ast.ClassDef] = {}
        for path in (BACKEND / "repositories").glob("*.py"):
            if path.name in {"__init__.py", "repos.py"}:
                continue
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef):
                    classes[node.name] = node
        return classes

    def test_base_defines_the_two_bases(self) -> None:
        tree = ast.parse((BACKEND / "repositories/_base.py").read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.ClassDef | ast.FunctionDef)}
        assert {"SessionRepo", "ShopScopedRepo", "utc_now_naive"} <= names

    def test_every_shop_scoped_subclass_declares_its_model_and_inherits_upsert(self) -> None:
        classes = self._repo_classes()
        subclasses = [c for c in classes.values() if any(map(_is_shop_scoped, c.bases))]
        assert len(subclasses) >= 10
        for cls in subclasses:
            assigned = {
                t.id
                for node in cls.body
                if isinstance(node, ast.Assign)
                for t in node.targets
                if isinstance(t, ast.Name)
            }
            assert "_model" in assigned, f"{cls.name} does not declare _model"
            methods = {n.name for n in cls.body if isinstance(n, ast.AsyncFunctionDef)}
            assert "upsert" not in methods, (
                f"{cls.name} reimplements upsert instead of declaring _lookup_attrs"
            )

    # Hand-written tenant filters that cannot go through ``_scoped`` because the statement
    # is not ``select(self._model)``: an aggregate + bulk UPDATE, and a join on a column
    # select. Listed exactly so an addition anywhere else fails this test.
    SANCTIONED_HAND_WRITTEN_FILTERS = {
        "commerce.py:ProductsRepo._scoped_order_item_totals",
        "commerce.py:ProductsRepo.recompute_revenue_from_order_items",
        "decisions.py:AlertHistoryRepo.has_recent_for_type",
    }

    def test_hand_written_tenant_filters_are_exactly_the_sanctioned_ones(self) -> None:
        """A hand-written ``Model.shop_id == shop_id`` is the bug ``_scoped`` exists to remove."""
        found: set[str] = set()
        for path in (BACKEND / "repositories").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                if not any(map(_is_shop_scoped, cls.bases)):
                    continue
                for fn in (
                    n for n in cls.body if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
                ):
                    for node in ast.walk(fn):
                        if (
                            isinstance(node, ast.Compare)
                            and isinstance(node.left, ast.Attribute)
                            and node.left.attr == "shop_id"
                            and isinstance(node.left.value, ast.Name)
                            and node.left.value.id[:1].isupper()
                        ):
                            found.add(f"{path.name}:{cls.name}.{fn.name}")
        assert found == self.SANCTIONED_HAND_WRITTEN_FILTERS


def test_route_exemplar_stays_thin() -> None:
    """The route is cited for being HTTP skin; it must not regrow behaviour."""
    source = (BACKEND / "api/routes/agent_runs.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) < 450, "api/routes/agent_runs.py is growing past a thin route"
    tree = ast.parse(source)
    longest = max(
        (node.end_lineno or 0) - node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    )
    assert longest < 80, "a handler in the route exemplar exceeds the 80-line guideline"


def test_test_support_exports_what_the_testing_guide_lists() -> None:
    from tests.support import api, builders, clock, event_stream, fakes, postgres, tiktok_fakes

    assert {"make_tenant", "make_shop", "make_product", "make_order", "make_workflow_run"} <= set(
        builders.__all__
    )
    assert {"authenticated_client", "build_app"} <= set(api.__all__)
    assert "FakeAsyncRedis" in fakes.__all__
    assert "requires_postgres" in postgres.__all__
    assert "SteppingClock" in clock.__all__
    assert {"FakePubSub", "sse_ids", "drain"} <= set(event_stream.__all__)
    assert "RecordingRateLimiter" in tiktok_fakes.__all__
