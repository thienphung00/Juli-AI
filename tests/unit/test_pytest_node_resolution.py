"""Unit tests for pytest node-id resolution in validation gates (#735 / P2-OPS-1).

`parse_pytest_node` split on the LAST "::" and treated everything before it as the
file path, so `file.py::TestClass::test_x` produced the non-existent path
`file.py::TestClass`. `pytest_node_exists` then bailed on its `path.exists()` check
before reaching the `ast.ClassDef` walk that would have resolved the method, and the
acceptance-mapping gate reported every class-based test as missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from common import parse_pytest_node, pytest_node_exists  # noqa: E402

SELF = "tests/unit/test_pytest_node_resolution.py"


class ExampleSuite:
    """Fixture class — resolved by the class-based node-id tests below."""

    def test_example_method(self):
        return True


def test_module_level_node_id_resolves():
    path, name = parse_pytest_node(f"{SELF}::test_module_level_node_id_resolves")
    assert path == REPO_ROOT / SELF
    assert name == "test_module_level_node_id_resolves"


def test_bare_path_resolves_with_empty_test_name():
    path, name = parse_pytest_node(SELF)
    assert path == REPO_ROOT / SELF
    assert name == ""


def test_class_based_node_id_resolves_to_file_not_class():
    """#735: the class segment must not be folded into the file path."""
    path, name = parse_pytest_node(f"{SELF}::ExampleSuite::test_example_method")
    assert path == REPO_ROOT / SELF, "file path must stop at the first '::'"
    assert name == "test_example_method"


def test_parametrised_class_node_id_resolves():
    path, name = parse_pytest_node(f"{SELF}::ExampleSuite::test_example_method[case-1]")
    assert path == REPO_ROOT / SELF
    assert name == "test_example_method", "parametrisation suffix must be stripped"


def test_pytest_node_exists_finds_class_method():
    """The ClassDef walk already existed; it was unreachable behind the bad path."""
    assert pytest_node_exists(f"{SELF}::ExampleSuite::test_example_method") is True


def test_pytest_node_exists_finds_module_level_function():
    assert pytest_node_exists(f"{SELF}::test_bare_path_resolves_with_empty_test_name") is True


def test_pytest_node_exists_rejects_absent_method_on_real_class():
    assert pytest_node_exists(f"{SELF}::ExampleSuite::test_does_not_exist") is False


def test_pytest_node_exists_rejects_absent_file():
    assert pytest_node_exists("tests/unit/no_such_file_here.py::test_x") is False
