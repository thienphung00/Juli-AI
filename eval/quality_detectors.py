"""Test-quality detectors and diff-scoped mutation testing (#1463).

The failure class: a test that is green on day one, never went red, and cannot
notice the defect it was written for. ``check_implementation_tdd_evidence.py``
tests for a *key's presence*, so nothing anywhere in the harness fails on a test
with no assertion. This module measures the property instead of a claim about it.

Two layers, deliberately separate:

**1. AST detectors.** Five classes, each emitting fingerprints in exactly the
identity format ``eval.ratchets`` already consumes — ``Identity(debt_class,
normalized_path, symbol, rule_code)``. Zero-assertion tests therefore ratchet
through #1462's mechanism rather than needing a parallel one; ``ratchet_measurers()``
hands ``eval.ratchets.measure`` a measurer per class and nothing is transformed
on the way in.

**2. Diff-scoped mutation testing.** Scoped to ``git diff --name-only base...HEAD``.
A repo-wide run exhausts the VPS budget, so a changed-file set that covers the
whole repository is treated as *a wrong diff base* — a hard failure, not a large
job to be throttled. Silently truncating it would hide the bug.

**No composite score.** Each sub-metric ratchets independently and mutation score
is the headline. A composite hides which dimension moved and is the easiest thing
here to game: walk one dimension up to mask another falling. ``assert_no_composite``
makes emitting one an error rather than a convention.

**Enforcement is not uniform.** ``asserts_mock_return`` and ``weak_assertions_only``
are ratchet-only: both have legitimate uses and their false-positive rate on this
repo is unmeasured, so blocking on them would train agents to write worse tests to
appease the gate. ``mutation_score_min`` stays unenforced until a distribution
from real diffs exists — on a small diff the score swings hard on a handful of
mutants.

Standard library only. CI installs ``./backend[dev] -c backend/constraints.txt``
and nothing else, so a third-party import here is a collection error in CI even
when it passes locally. That is why the mutation engine below is written against
``ast`` rather than pulling in ``mutmut`` or ``cosmic-ray``: neither is in that
set, and adding one is a dependency decision this slice does not get to make.

CLI::

    python -m eval.quality_detectors scan               # per-class counts
    python -m eval.quality_detectors report             # full JSON report
    python -m eval.quality_detectors mutate --base main # diff-scoped mutation
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from eval.ratchets import (
    IDENTITY_CLASS,
    PRUNED_DIRS,
    ClassMeasurement,
    Identity,
    MeasurementError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = "test-quality-report/1"

# --------------------------------------------------------------------------
# rule codes
# --------------------------------------------------------------------------

RULE_ZERO_ASSERTION = "zero_assertion"
RULE_TRIVIAL_ASSERTION = "trivial_assertion"
RULE_MOCK_ONLY = "mock_only"
RULE_ASSERTS_MOCK_RETURN = "asserts_mock_return"
RULE_WEAK_ASSERTIONS_ONLY = "weak_assertions_only"

RULE_CODES: tuple[str, ...] = (
    RULE_ZERO_ASSERTION,
    RULE_TRIVIAL_ASSERTION,
    RULE_MOCK_ONLY,
    RULE_ASSERTS_MOCK_RETURN,
    RULE_WEAK_ASSERTIONS_ONLY,
)

ENFORCEMENT_BLOCKING = "blocking"
ENFORCEMENT_RATCHET = "ratchet"

#: Ratchet-only by decision, not by omission. Both classes have legitimate uses
#: — a contract test that only checks a call was routed, a smoke test whose
#: assertion is deliberately loose — and their false-positive rate on this
#: corpus has never been measured. Blocking on an unmeasured heuristic teaches
#: agents to defeat the detector rather than to write a test that can fail.
RATCHET_ONLY_CLASSES = frozenset({RULE_ASSERTS_MOCK_RETURN, RULE_WEAK_ASSERTIONS_ONLY})
BLOCKING_CLASSES = frozenset(RULE_CODES) - RATCHET_ONLY_CLASSES

DEBT_CLASS_PREFIX = "test_quality_"

#: The prior measurement, carried as a reference point and never as ground
#: truth. It has not been independently reproduced; ``RECONCILIATION`` below
#: records this module's own reading beside it and explains the divergence
#: rather than reconciling it away.
REPORTED_ZERO_ASSERTION_TESTS = 97
REPORTED_TEST_FUNCTIONS = 4048

TEST_ROOTS: tuple[str, ...] = ("tests", "backend", "scripts", "agent-runtime", "eval")


def debt_class_for(rule_code: str) -> str:
    """The ``eval.ratchets`` debt-class name for one detector rule.

    One class per rule, never one class for all five: a shared class would make
    the five counts interchangeable in the baseline, which is the composite this
    slice refuses to emit wearing a different hat.
    """
    if rule_code not in RULE_CODES:
        raise MeasurementError(f"unknown test-quality rule {rule_code!r}")
    return f"{DEBT_CLASS_PREFIX}{rule_code}"


def enforcement(rule_code: str) -> str:
    if rule_code not in RULE_CODES:
        raise MeasurementError(f"unknown test-quality rule {rule_code!r}")
    return ENFORCEMENT_RATCHET if rule_code in RATCHET_ONLY_CLASSES else ENFORCEMENT_BLOCKING


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Finding:
    """One test that cannot notice what it was written for.

    ``symbol`` is the qualname, matching ``eval.ratchets``' convention, and is
    deliberately not line-numbered: a line number would churn the whole baseline
    every time a file gains an import, and the churn would drown the one arrival
    that matters.
    """

    rule_code: str
    path: str
    symbol: str
    detail: str = ""

    def identity(self) -> Identity:
        code = f"{self.rule_code}:{self.detail}" if self.detail else self.rule_code
        return Identity(debt_class_for(self.rule_code), self.path, self.symbol, code)


# --------------------------------------------------------------------------
# filesystem walk
# --------------------------------------------------------------------------


def _is_pruned(repo_root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(repo_root).parts
    except ValueError:  # pragma: no cover - defensive
        return True
    return any(part in PRUNED_DIRS or part.endswith(".egg-info") for part in parts)


def is_test_path(rel: str) -> bool:
    """Whether a repo-relative path is a pytest test module.

    Conservative on purpose. ``conftest.py`` is excluded: it holds fixtures and
    helpers, not tests, and scanning it would report every fixture as a test
    that asserts nothing.
    """
    name = rel.rsplit("/", 1)[-1]
    if not name.endswith(".py"):
        return False
    return name.startswith("test_") or name.endswith("_test.py")


def _walk_python(repo_root: Path, roots: Iterable[str] | None) -> Iterator[Path]:
    bases = [repo_root] if roots is None else [repo_root / r for r in roots]
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if not path.is_file() or _is_pruned(repo_root, path) or path in seen:
                continue
            seen.add(path)
            yield path


def _rel(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _parse(path: Path) -> ast.Module:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MeasurementError(f"unreadable file {path}: {exc}") from exc
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise MeasurementError(f"unparseable python in {path}: {exc}") from exc


# --------------------------------------------------------------------------
# AST vocabulary
# --------------------------------------------------------------------------

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

_MOCK_FACTORIES = frozenset(
    {
        "Mock",
        "MagicMock",
        "AsyncMock",
        "NonCallableMock",
        "NonCallableMagicMock",
        "PropertyMock",
        "create_autospec",
        "patch",
        "mock_open",
    }
)

#: Calls that do not count as "exercising real code" when deciding whether a
#: test is mock-only. Builtins and the mock factories themselves — a test whose
#: only non-mock call is ``len()`` has still not run any production code.
_INERT_CALLEES = frozenset(
    {
        "len",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "sorted",
        "range",
        "print",
        "repr",
        "getattr",
        "setattr",
        "hasattr",
        "isinstance",
        "type",
        "enumerate",
        "zip",
        "next",
        "iter",
        "any",
        "all",
    }
    | _MOCK_FACTORIES
)

_MOCK_ASSERT_METHODS = (
    "assert_called",
    "assert_not_called",
    "assert_any_call",
    "assert_has_calls",
    "assert_awaited",
)

_PYTEST_RAISING = frozenset({"raises", "warns", "deprecated_call", "fail", "xfail"})

#: Comparisons that are tautological when both sides are the same expression.
_REFLEXIVE_OPS = (ast.Eq, ast.Is, ast.LtE, ast.GtE)


def _root_name(node: ast.AST) -> str | None:
    """The leftmost ``Name`` of an attribute/subscript/call chain."""
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return None


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _body_nodes(func: FunctionNode) -> Iterator[ast.AST]:
    """Every node in a function body, excluding nested function definitions.

    Nested defs are excluded because a helper closure's assertions only fire if
    the closure is called, and a test that defines an asserting closure and never
    calls it is precisely the vacuous case this module exists to catch.
    """
    for stmt in func.body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            yield node


def _is_mock_assert_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith(_MOCK_ASSERT_METHODS)
    )


def _is_unittest_assert_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and _root_name(node.func) == "self"
        and (node.func.attr.startswith("assert") or node.func.attr == "fail")
    )


def _is_pytest_raising_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    dotted = _dotted(node.func)
    return dotted.startswith("pytest.") and dotted.rsplit(".", 1)[-1] in _PYTEST_RAISING


def _asserting_helper_names(tree: ast.Module) -> frozenset[str]:
    """Same-file helpers that assert, resolved to a fixed point.

    Without this the detector's dominant false positive would be the repo's own
    house style: ``tests/unit/test_api.py`` asserts almost entirely through
    ``_assert_envelope(response)``. A test delegating to such a helper *can*
    fail, so it is not vacuous.
    """
    functions: dict[str, FunctionNode] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, node)

    asserting: set[str] = set()
    for name, func in functions.items():
        if any(_direct_assertion(node) for node in _body_nodes(func)):
            asserting.add(name)

    changed = True
    while changed:
        changed = False
        for name, func in functions.items():
            if name in asserting:
                continue
            for node in _body_nodes(func):
                if isinstance(node, ast.Call) and _root_name(node.func) in asserting:
                    asserting.add(name)
                    changed = True
                    break
    return frozenset(asserting)


def _direct_assertion(node: ast.AST) -> bool:
    """Whether one node is, on its own, something that can fail the test."""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Raise):
        exc = node.exc
        name = _dotted(exc.func) if isinstance(exc, ast.Call) else _dotted(exc) if exc else ""
        return name.endswith("AssertionError")
    return (
        _is_mock_assert_call(node)
        or _is_unittest_assert_call(node)
        or _is_pytest_raising_call(node)
    )


# --------------------------------------------------------------------------
# per-rule classification
# --------------------------------------------------------------------------


def _trivial_form(test: ast.expr) -> str | None:
    """Why an assertion is true regardless of the code under test, or ``None``."""
    if isinstance(test, ast.Constant):
        return "constant" if test.value else None
    if isinstance(test, (ast.List, ast.Tuple, ast.Set)) and test.elts:
        return "container_literal"
    if isinstance(test, ast.Dict) and test.keys:
        return "container_literal"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, right, op = test.left, test.comparators[0], test.ops[0]
        if isinstance(op, _REFLEXIVE_OPS) and ast.dump(left) == ast.dump(right):
            return "self_comparison"
        if (
            isinstance(op, ast.GtE)
            and isinstance(right, ast.Constant)
            and right.value == 0
            and isinstance(left, ast.Call)
            and _dotted(left.func) == "len"
        ):
            return "len_ge_zero"
    if isinstance(test, ast.Call) and _dotted(test.func) == "isinstance":
        if len(test.args) == 2 and _dotted(test.args[1]) == "object":
            return "isinstance_object"
    return None


def _weak_form(test: ast.expr) -> str | None:
    """Why an assertion barely constrains its subject, or ``None`` if it does.

    ``x is None`` is *not* weak: it pins an exact value. ``x is not None`` is,
    because every wrong answer that is not ``None`` still passes.
    """
    if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
        return "truthiness"
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return "falsiness"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, right = test.ops[0], test.comparators[0]
        if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return "is_not_none"
    if isinstance(test, ast.Call) and _dotted(test.func) == "isinstance":
        return "isinstance_only"
    return None


def _mock_names(func: FunctionNode) -> frozenset[str]:
    """Names in this test that are bound to a mock."""
    names: set[str] = set()

    for arg in [*func.args.args, *func.args.posonlyargs, *func.args.kwonlyargs]:
        if arg.arg.startswith("mock") or arg.arg.endswith(("_mock", "_mocks")):
            names.add(arg.arg)

    def _bind(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                _bind(elt)

    for node in _body_nodes(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _dotted(node.value.func).rsplit(".", 1)[-1] in _MOCK_FACTORIES:
                for target in node.targets:
                    _bind(target)
        elif isinstance(node, ast.withitem):
            call = node.context_expr
            if (
                isinstance(call, ast.Call)
                and node.optional_vars is not None
                and _dotted(call.func).rsplit(".", 1)[-1] in _MOCK_FACTORIES
            ):
                _bind(node.optional_vars)
    return frozenset(names)


def _exercises_real_code(func: FunctionNode, mocks: frozenset[str]) -> bool:
    for node in _body_nodes(func):
        if not isinstance(node, ast.Call):
            continue
        if _is_mock_assert_call(node) or _is_unittest_assert_call(node):
            continue
        root = _root_name(node.func)
        callee = _dotted(node.func).rsplit(".", 1)[-1]
        if root in mocks or callee in _INERT_CALLEES or root in ("self", "pytest"):
            continue
        return True
    return False


def _mock_return_roots(func: FunctionNode, mocks: frozenset[str]) -> frozenset[str]:
    """Mock roots whose ``return_value`` (or ``side_effect``) this test set."""
    roots: set[str] = set()
    for node in _body_nodes(func):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in ("return_value", "side_effect"):
                root = _root_name(target)
                if root in mocks:
                    roots.add(root)
    return frozenset(roots)


def _asserts_its_own_injection(
    func: FunctionNode, mocks: frozenset[str], seeded: frozenset[str]
) -> bool:
    """Whether an assertion's subject is the value the test just injected.

    The tautology: configure ``client.fetch.return_value = X``, then assert
    ``client.fetch() == X``. Nothing but the mock library is under test.
    """
    if not seeded:
        return False
    for node in _body_nodes(func):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Attribute) and sub.attr == "return_value":
                if _root_name(sub) in mocks:
                    return True
            if isinstance(sub, ast.Call) and _root_name(sub.func) in seeded:
                return True
    return False


def _classify(func: FunctionNode, asserting_helpers: frozenset[str]) -> list[tuple[str, str]]:
    """Every ``(rule_code, detail)`` this test function earns."""
    nodes = list(_body_nodes(func))
    asserts = [n for n in nodes if isinstance(n, ast.Assert)]
    has_direct = any(_direct_assertion(n) for n in nodes)
    via_helper = any(
        isinstance(n, ast.Call) and _root_name(n.func) in asserting_helpers for n in nodes
    )

    if not has_direct and not via_helper:
        return [(RULE_ZERO_ASSERTION, "")]

    findings: list[tuple[str, str]] = []

    trivial = [form for form in (_trivial_form(a.test) for a in asserts) if form]
    if trivial:
        findings.append((RULE_TRIVIAL_ASSERTION, sorted(set(trivial))[0]))

    mocks = _mock_names(func)
    if mocks and not _exercises_real_code(func, mocks):
        findings.append((RULE_MOCK_ONLY, ""))

    seeded = _mock_return_roots(func, mocks)
    if _asserts_its_own_injection(func, mocks, seeded):
        findings.append((RULE_ASSERTS_MOCK_RETURN, ""))

    if asserts and not trivial:
        weak = [_weak_form(a.test) for a in asserts]
        if all(form is not None for form in weak):
            findings.append((RULE_WEAK_ASSERTIONS_ONLY, sorted({f for f in weak if f})[0]))

    return findings


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------


def _iter_tests(tree: ast.Module) -> Iterator[tuple[str, FunctionNode]]:
    def visit(node: ast.AST, prefix: str) -> Iterator[tuple[str, FunctionNode]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                yield from visit(child, qual)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                if child.name.startswith("test"):
                    yield qual, child

    yield from visit(tree, "")


@dataclass(frozen=True)
class Scan:
    """One pass over the corpus: the findings and what they are a share of.

    Both numbers come from the same walk deliberately. Counting the corpus in a
    second pass would let the denominator drift from the numerator whenever the
    two disagreed about which files are tests — and a rate computed from two
    different corpora is worse than no rate.
    """

    findings: tuple[Finding, ...]
    test_functions: int
    files: int


def scan_file(repo_root: Path, path: Path) -> tuple[Finding, ...]:
    return _scan_one(repo_root, path)[0]


def _scan_one(repo_root: Path, path: Path) -> tuple[tuple[Finding, ...], int]:
    tree = _parse(path)
    rel = _rel(repo_root, path)
    helpers = _asserting_helper_names(tree)
    findings: list[Finding] = []
    tests = 0
    for qualname, func in _iter_tests(tree):
        tests += 1
        for rule_code, detail in _classify(func, helpers):
            findings.append(Finding(rule_code=rule_code, path=rel, symbol=qualname, detail=detail))
    return tuple(findings), tests


def scan_corpus(repo_root: Path, roots: Sequence[str] | None = TEST_ROOTS) -> Scan:
    """Every finding in the test corpus, sorted and fail-closed.

    A file that cannot be parsed raises rather than being skipped: a scan that
    skipped it would under-report, and under-reporting is the exact failure this
    module exists to prevent. Reporting a broken file as "clean" is the same lie
    as a test with no assertion.
    """
    repo_root = Path(repo_root)
    findings: list[Finding] = []
    tests = 0
    files = 0
    for path in _walk_python(repo_root, roots):
        if not is_test_path(_rel(repo_root, path)):
            continue
        files += 1
        found, count = _scan_one(repo_root, path)
        findings.extend(found)
        tests += count
    return Scan(findings=tuple(sorted(findings)), test_functions=tests, files=files)


#: The order the reconciliation peels evidence off in. Each entry names one kind
#: of thing that can fail a test; the union of all six is exactly what
#: ``_classify`` accepts as "this test can fail", so the last layer is the
#: headline by construction rather than by coincidence.
RECONCILIATION_LAYER_ORDER: tuple[str, ...] = (
    "no_assert_statement",
    "and_no_pytest_raises",
    "and_no_mock_assert_called",
    "and_no_unittest_self_assert",
    "and_no_same_file_asserting_helper",
    "and_no_raise_assertionerror",
)


def _raises_assertionerror(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise):
        return False
    exc = node.exc
    name = _dotted(exc.func) if isinstance(exc, ast.Call) else _dotted(exc) if exc else ""
    return name.endswith("AssertionError")


def reconciliation_identities(
    repo_root: Path, roots: Sequence[str] | None = TEST_ROOTS
) -> dict[str, set[tuple[str, str]]]:
    """The ``(path, qualname)`` set surviving each reconciliation layer.

    Derived, never recorded. The decomposition is arithmetic over the corpus --
    there is no state of the world in which a committed layer legitimately
    differs from the computed one -- so committing the six integers by hand made
    five of them unfalsifiable and the sixth the only one ever checked. Two of
    the three figures recorded alongside them in #1503 were wrong on the day they
    were written (#1535); this exists so that cannot recur.

    Uses the same walk and the same predicates as :func:`scan_corpus`, including
    ``_iter_tests``' direct-children-only enumeration. An independent ``ast.walk``
    reads two extra functions -- a dependency-override generator and a route
    handler nested inside a test -- and lands on a final layer that does not
    equal the headline it is supposed to explain.
    """
    repo_root = Path(repo_root)
    survivors: dict[str, set[tuple[str, str]]] = {
        name: set() for name in RECONCILIATION_LAYER_ORDER
    }

    for path in _walk_python(repo_root, roots):
        rel = _rel(repo_root, path)
        if not is_test_path(rel):
            continue
        tree = _parse(path)
        helpers = _asserting_helper_names(tree)
        for qualname, func in _iter_tests(tree):
            nodes = list(_body_nodes(func))
            key = (rel, qualname)
            # Ordered so each test drops out at the first kind of evidence it has.
            for layer, has_evidence in (
                ("no_assert_statement", any(isinstance(n, ast.Assert) for n in nodes)),
                ("and_no_pytest_raises", any(_is_pytest_raising_call(n) for n in nodes)),
                ("and_no_mock_assert_called", any(_is_mock_assert_call(n) for n in nodes)),
                ("and_no_unittest_self_assert", any(_is_unittest_assert_call(n) for n in nodes)),
                (
                    "and_no_same_file_asserting_helper",
                    any(isinstance(n, ast.Call) and _root_name(n.func) in helpers for n in nodes),
                ),
                ("and_no_raise_assertionerror", any(_raises_assertionerror(n) for n in nodes)),
            ):
                if has_evidence:
                    break
                survivors[layer].add(key)
    return survivors


def reconciliation_layers(
    repo_root: Path, roots: Sequence[str] | None = TEST_ROOTS
) -> dict[str, int]:
    """The layer decomposition, re-derived from the tree it describes."""
    return {name: len(ids) for name, ids in reconciliation_identities(repo_root, roots).items()}


def scan_tree(repo_root: Path, roots: Sequence[str] | None = TEST_ROOTS) -> tuple[Finding, ...]:
    return scan_corpus(repo_root, roots).findings


def count_test_functions(repo_root: Path, roots: Sequence[str] | None = TEST_ROOTS) -> int:
    """Size of the corpus the findings are a share of."""
    return scan_corpus(repo_root, roots).test_functions


def counts_by_rule(findings: Iterable[Finding]) -> dict[str, int]:
    """Per-class counts, with every class present even at zero.

    An absent key would read as "not measured" and "not measured" must never be
    indistinguishable from "clean".
    """
    counter: Counter[str] = Counter(f.rule_code for f in findings)
    return {rule: counter.get(rule, 0) for rule in RULE_CODES}


# --------------------------------------------------------------------------
# ratchet integration
# --------------------------------------------------------------------------


def measure_rule(repo_root: Path, rule_code: str, roots: Sequence[str] | None = TEST_ROOTS):
    """One detector class as an ``eval.ratchets`` identity measurement."""
    findings = [f for f in scan_tree(repo_root, roots) if f.rule_code == rule_code]
    occurrences: Counter[Identity] = Counter(f.identity() for f in findings)
    return ClassMeasurement(
        name=debt_class_for(rule_code),
        kind=IDENTITY_CLASS,
        occurrences=dict(occurrences),
        stats={
            "rule_code": rule_code,
            "enforcement": enforcement(rule_code),
            "distinct_identities": len(occurrences),
            "occurrences": sum(occurrences.values()),
        },
    )


def ratchet_measurers(roots: Sequence[str] | None = TEST_ROOTS) -> dict[str, Any]:
    """Measurers keyed by debt class, ready for ``eval.ratchets.measure``.

    This is the whole point of the identity format: the fingerprints go into the
    existing ratchet with no transformation, so a new zero-assertion test fails
    ``check`` as a ``new_identity`` exactly like a new ``# noqa`` does.

    Deliberately uncached. The two ``measure`` calls in a ratchet round-trip read
    the same tree at two different states, and a cache keyed on the path alone
    would serve the first reading twice — a false PASS in the one place a false
    PASS is least acceptable.
    """

    def _make(rule_code: str):
        def _measurer(repo_root: Path) -> ClassMeasurement:
            return measure_rule(repo_root, rule_code, roots)

        return _measurer

    return {debt_class_for(rule): _make(rule) for rule in RULE_CODES}


# --------------------------------------------------------------------------
# diff-scoped mutation testing
# --------------------------------------------------------------------------


class BadDiffBaseError(Exception):
    """The changed-file set covers the repository, so the base is wrong.

    Not a budget error. Truncating to the first N files would run *some*
    mutation and report a score, hiding the fact that the comparison point was
    never valid.
    """


class CompositeScoreError(Exception):
    """A report tried to roll the sub-metrics into one number."""


#: Above this share of the repository's source inventory the changed set is not
#: a diff. Applied only once the inventory is big enough for the ratio to mean
#: anything — on a five-file repository, three changed files is a normal PR.
WHOLE_REPO_FRACTION = 0.5
MIN_INVENTORY_FOR_FRACTION = 50

#: Budget ceiling for one run. A cap on *mutants*, not on files: capping files
#: would silently narrow the scope the caller asked for.
DEFAULT_MAX_MUTANTS = 200

#: Unenforced by decision. On a small diff the score swings hard on a handful of
#: mutants, so a floor set before a distribution from real diffs exists would
#: gate on noise and teach agents to pad diffs with easily-killed code.
MUTATION_SCORE_MIN: float | None = None

VERDICT_UNENFORCED = "unenforced"
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"


def mutation_gate_enforced() -> bool:
    return MUTATION_SCORE_MIN is not None


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or str(exc)
        raise BadDiffBaseError(f"git {' '.join(args)} failed: {stderr.strip()}") from exc
    return result.stdout


def all_python_sources(repo_root: Path) -> tuple[str, ...]:
    """Every mutable source file in the tree — the inventory a diff is judged against."""
    repo_root = Path(repo_root)
    return tuple(
        rel
        for rel in (_rel(repo_root, p) for p in _walk_python(repo_root, None))
        if not is_test_path(rel)
    )


def _reject_whole_repo(repo_root: Path, changed: Sequence[str], base: str | None) -> None:
    inventory = set(all_python_sources(repo_root))
    if len(inventory) < 2:
        # With one source file there is no observable difference between "a
        # normal diff" and "the whole repository", so the guard has nothing to
        # decide and must not invent a failure.
        return
    changed_set = set(changed)
    covers_all = inventory.issubset(changed_set)
    share = len(changed_set & inventory) / len(inventory)
    too_broad = len(inventory) >= MIN_INVENTORY_FOR_FRACTION and share >= WHOLE_REPO_FRACTION
    if covers_all or too_broad:
        where = f" from diff base {base!r}" if base else ""
        raise BadDiffBaseError(
            f"changed-file set{where} covers {len(changed_set & inventory)} of "
            f"{len(inventory)} source files ({share:.0%}); that is not a diff, "
            "it is the whole repository — the diff base is wrong, and mutating "
            "repo-wide would exhaust the budget while reporting a meaningless score"
        )


def changed_python_sources(repo_root: Path, base: str, head: str = "HEAD") -> tuple[str, ...]:
    """Source files changed between ``base`` and ``head``, as a mutation scope.

    Test files are excluded: mutating a test proves nothing about that test's
    power to notice a defect in the code it covers.
    """
    repo_root = Path(repo_root)
    try:
        raw = _git(repo_root, "diff", "--name-only", f"{base}...{head}")
    except BadDiffBaseError as exc:
        # An unresolvable base is a bad diff base, not an infrastructure blip.
        # Reported in the same vocabulary so a caller need not distinguish
        # "the base does not exist" from "the base is so old it means nothing".
        raise BadDiffBaseError(f"diff base {base!r} does not resolve: {exc}") from exc
    changed = tuple(
        sorted(
            rel
            for rel in (line.strip() for line in raw.splitlines())
            if rel.endswith(".py")
            and not is_test_path(rel)
            and (repo_root / rel).is_file()
            and not _is_pruned(repo_root, repo_root / rel)
        )
    )
    _reject_whole_repo(repo_root, changed, base)
    return changed


@dataclass(frozen=True)
class Mutant:
    path: str
    index: int
    operator: str
    lineno: int
    description: str


def _mutation_sites(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Deterministically ordered mutation points.

    ``ast.walk`` is breadth-first over a deque, so the ordering is stable across
    runs — which is what lets a mutant be identified by index and re-applied to
    a freshly parsed tree instead of deep-copying one.
    """
    sites: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            if type(node.ops[0]) in _CMP_FLIP:
                sites.append(("comparison", node))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_FLIP:
            sites.append(("arithmetic", node))
        elif isinstance(node, ast.BoolOp):
            sites.append(("boolean", node))
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                sites.append(("bool_constant", node))
            elif isinstance(node.value, int):
                sites.append(("int_constant", node))
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                sites.append(("return_value", node))
    return sites


_CMP_FLIP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}

_BIN_FLIP: dict[type, type] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
}


def _apply(kind: str, node: ast.AST) -> str:
    """Mutate one node in place and describe the change."""
    if kind == "comparison" and isinstance(node, ast.Compare):
        old = type(node.ops[0])
        node.ops[0] = _CMP_FLIP[old]()
        return f"{old.__name__} -> {_CMP_FLIP[old].__name__}"
    if kind == "arithmetic" and isinstance(node, ast.BinOp):
        old = type(node.op)
        node.op = _BIN_FLIP[old]()
        return f"{old.__name__} -> {_BIN_FLIP[old].__name__}"
    if kind == "boolean" and isinstance(node, ast.BoolOp):
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return "And <-> Or"
    if kind == "bool_constant" and isinstance(node, ast.Constant):
        was = node.value
        node.value = not was
        return f"{was} -> {not was}"
    if kind == "int_constant" and isinstance(node, ast.Constant):
        was = node.value
        node.value = was + 1
        return f"{was} -> {was + 1}"
    if kind == "return_value" and isinstance(node, ast.Return):
        node.value = ast.Constant(value=None)
        return "return <expr> -> return None"
    raise MeasurementError(f"no mutation for site kind {kind!r}")  # pragma: no cover


def generate_mutants(repo_root: Path, rel: str) -> tuple[tuple[Mutant, str], ...]:
    """Every single-point mutant of one file, as ``(descriptor, mutated source)``."""
    repo_root = Path(repo_root)
    path = repo_root / rel
    original = _parse(path)
    total = len(_mutation_sites(original))

    produced: list[tuple[Mutant, str]] = []
    for index in range(total):
        tree = _parse(path)
        kind, node = _mutation_sites(tree)[index]
        description = _apply(kind, node)
        ast.fix_missing_locations(tree)
        try:
            source = ast.unparse(tree)
        except (ValueError, RecursionError) as exc:  # pragma: no cover - defensive
            raise MeasurementError(f"cannot render mutant {index} of {rel}: {exc}") from exc
        lineno = getattr(node, "lineno", 0)
        produced.append(
            (
                Mutant(
                    path=rel, index=index, operator=kind, lineno=lineno, description=description
                ),
                source,
            )
        )
    return tuple(produced)


def plan_mutations(
    repo_root: Path,
    changed_paths: Sequence[str],
    max_mutants: int = DEFAULT_MAX_MUTANTS,
) -> tuple[tuple[Mutant, str], ...]:
    """Mutants for exactly the changed files, refusing a repo-wide scope."""
    repo_root = Path(repo_root)
    _reject_whole_repo(repo_root, changed_paths, None)
    planned: list[tuple[Mutant, str]] = []
    for rel in changed_paths:
        planned.extend(generate_mutants(repo_root, rel))
        if len(planned) >= max_mutants:
            break
    return tuple(planned[:max_mutants])


@dataclass(frozen=True)
class MutationOutcome:
    files: tuple[str, ...]
    killed: int
    survived: int
    errored: int
    surviving: tuple[Mutant, ...]
    mutants_considered: int

    @property
    def total(self) -> int:
        return self.killed + self.survived + self.errored

    @property
    def score(self) -> float:
        """Killed over the mutants that ran. The headline sub-metric, alone."""
        denominator = self.killed + self.survived
        return self.killed / denominator if denominator else 0.0


def mutation_verdict(outcome: MutationOutcome) -> str:
    if not mutation_gate_enforced():
        return VERDICT_UNENFORCED
    assert MUTATION_SCORE_MIN is not None
    return VERDICT_PASS if outcome.score >= MUTATION_SCORE_MIN else VERDICT_FAIL


#: Plugins the suite genuinely needs, loaded by name because autoload is off.
#: Autoload dominates the cost of a mutation run — every mutant pays it again,
#: and on a developer machine with a crowded site-packages it is ~10s of the
#: ~10.4s a trivial run takes. Naming the two the corpus depends on turns a
#: 200-mutant campaign from half an hour of import into about a minute.
#:
#: These must be *module* paths, not distribution names. ``-p pytest_asyncio``
#: imports a package whose ``__init__`` registers no hooks, so ``asyncio_mode``
#: stays an unknown ini option and every async fixture in ``tests/unit/conftest.py``
#: errors at setup — turning every mutant into ``errored`` and the score into a
#: zero-denominator 0.0. Measured on this repo: ``("pytest_asyncio",)`` gives
#: 40/40 errored, ``("pytest_asyncio.plugin",)`` gives 29 killed / 10 survived.
#: A campaign that reports no kills and no survivors has not run.
MUTATION_PYTEST_PLUGINS: tuple[str, ...] = ("pytest_asyncio.plugin",)

#: pytest's own exit codes. Only 1 — "tests failed" — is a kill. 4 (usage
#: error) and 5 (no tests collected) must never be read as a kill: they are the
#: shape a misconfigured run takes, and scoring them as kills would report a
#: perfect mutation score for a campaign that never ran a single test.
_EXIT_TESTS_FAILED = 1
_EXIT_KILLED: frozenset[int] = frozenset({_EXIT_TESTS_FAILED})
_EXIT_SURVIVED: frozenset[int] = frozenset({0})


def _run_tests(
    repo_root: Path,
    test_paths: Sequence[str],
    timeout: float,
    plugins: Sequence[str],
) -> int:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    plugin_args: list[str] = ["-p", "no:cacheprovider"]
    for plugin in plugins:
        plugin_args += ["-p", plugin]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", *plugin_args, *test_paths],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # A hang is a kill: the mutant changed observable behaviour, and the
        # suite noticed by never finishing.
        return _EXIT_TESTS_FAILED
    return result.returncode


def run_mutations(
    repo_root: Path,
    changed_paths: Sequence[str],
    test_paths: Sequence[str],
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    timeout: float = 60.0,
    plugins: Sequence[str] = MUTATION_PYTEST_PLUGINS,
) -> MutationOutcome:
    """Apply each mutant to the tree, run the tests, restore the original.

    The original source is restored in a ``finally`` per mutant, so an
    interrupted run cannot leave a mutated file behind — a mutated file left in
    a worktree would be indistinguishable from a real edit.
    """
    repo_root = Path(repo_root)
    planned = plan_mutations(repo_root, changed_paths, max_mutants=max_mutants)

    killed = survived = errored = 0
    surviving: list[Mutant] = []
    originals = {rel: (repo_root / rel).read_text(encoding="utf-8") for rel in changed_paths}

    for mutant, source in planned:
        target = repo_root / mutant.path
        try:
            target.write_text(source, encoding="utf-8")
            code = _run_tests(repo_root, test_paths, timeout, plugins)
        finally:
            target.write_text(originals[mutant.path], encoding="utf-8")
        if code in _EXIT_SURVIVED:
            survived += 1
            surviving.append(mutant)
        elif code in _EXIT_KILLED:
            killed += 1
        else:
            errored += 1

    return MutationOutcome(
        files=tuple(changed_paths),
        killed=killed,
        survived=survived,
        errored=errored,
        surviving=tuple(surviving),
        mutants_considered=len(planned),
    )


# --------------------------------------------------------------------------
# reporting — sub-metrics only, never a composite
# --------------------------------------------------------------------------

#: Key names that would roll independent dimensions into one number. A composite
#: is the easiest thing here to game: walk mutation score up on trivial code
#: while zero-assertion debt rises, and the single number improves.
_FORBIDDEN_KEY_FRAGMENTS = ("composite",)
_FORBIDDEN_KEYS = frozenset(
    {
        "overallscore",
        "totalscore",
        "aggregatescore",
        "combinedscore",
        "qualityscore",
        "testqualityscore",
        "overall",
    }
)


def _normalise_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def assert_no_composite(report: Mapping[str, Any]) -> None:
    """Raise if any key anywhere in the report aggregates the sub-metrics."""

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                normalised = _normalise_key(str(key))
                if normalised in _FORBIDDEN_KEYS or any(
                    fragment in normalised for fragment in _FORBIDDEN_KEY_FRAGMENTS
                ):
                    raise CompositeScoreError(
                        f"{path}.{key} rolls independent sub-metrics into one number; "
                        "each dimension ratchets on its own so a fall in one cannot "
                        "be masked by a rise in another"
                    )
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, path)

    walk(report, "report")


def build_report(
    repo_root: Path,
    roots: Sequence[str] | None = TEST_ROOTS,
    mutation: MutationOutcome | None = None,
) -> dict[str, Any]:
    """The per-class reading, with mutation kept as its own separate section."""
    repo_root = Path(repo_root)
    scan = scan_corpus(repo_root, roots)
    findings = scan.findings
    counts = counts_by_rule(findings)

    detectors: dict[str, Any] = {}
    for rule in RULE_CODES:
        detectors[rule] = {
            "count": counts[rule],
            "enforcement": enforcement(rule),
            "debtClass": debt_class_for(rule),
            "identities": sorted(f.identity().key() for f in findings if f.rule_code == rule),
        }

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "issue": 1463,
        "root": str(repo_root),
        "testFilesScanned": scan.files,
        "testFunctionsScanned": scan.test_functions,
        "detectors": detectors,
    }
    if mutation is not None:
        report["mutation"] = {
            "score": mutation.score,
            "killed": mutation.killed,
            "survived": mutation.survived,
            "errored": mutation.errored,
            "mutantsConsidered": mutation.mutants_considered,
            "files": list(mutation.files),
            "verdict": mutation_verdict(mutation),
            "enforced": mutation_gate_enforced(),
            "surviving": [
                {
                    "path": m.path,
                    "line": m.lineno,
                    "operator": m.operator,
                    "change": m.description,
                }
                for m in mutation.surviving
            ],
        }
    assert_no_composite(report)
    return report


#: This module's own reading of the repository, recorded beside the prior figure
#: rather than reconciled away. Regenerate with
#: ``python -m eval.quality_detectors scan`` and update both numbers together.
MEASURED_ZERO_ASSERTION_TESTS = 50
MEASURED_TEST_FUNCTIONS = 4567
#: Test modules the corpus figure is spread over. Like the corpus it is a
#: denominator, not a claim, so it is held to a tolerance rather than pinned.
MEASURED_TEST_MODULES = 465

#: The measured decomposition that reconciles the two figures. Each layer
#: subtracts one kind of evidence that a test *can* fail; the prior ~97 lands on
#: the third layer, this module's headline on the fifth.
RECONCILIATION_LAYERS: dict[str, int] = {
    "no_assert_statement": 404,
    "and_no_pytest_raises": 124,
    "and_no_mock_assert_called": 107,
    "and_no_unittest_self_assert": 107,
    "and_no_same_file_asserting_helper": 54,
    "and_no_raise_assertionerror": 50,
}

RECONCILIATION: dict[str, Any] = {
    "reported": REPORTED_ZERO_ASSERTION_TESTS,
    "reportedCorpus": REPORTED_TEST_FUNCTIONS,
    "measured": MEASURED_ZERO_ASSERTION_TESTS,
    "measuredCorpus": MEASURED_TEST_FUNCTIONS,
    "delta": MEASURED_ZERO_ASSERTION_TESTS - REPORTED_ZERO_ASSERTION_TESTS,
    "measuredAt": "2026-09-03",
    "roots": list(TEST_ROOTS),
    "layers": dict(RECONCILIATION_LAYERS),
    "priorFigureLayer": "and_no_mock_assert_called",
    "note": (
        "Neither figure is wrong; they count different things, and the layer "
        "decomposition above shows exactly where they part. Measured here: 50 "
        "zero-assertion tests in a corpus of 4,567 test functions over tests/ "
        "backend/ scripts/ agent-runtime/ eval/ (465 test modules). The prior "
        "~97-of-4,048 reading corresponds to the `and_no_mock_assert_called` "
        "layer — a detector that credits `pytest.raises` and `mock.assert_called*` "
        "as assertions but not delegation to a same-file asserting helper. That "
        "layer reads 107 today; scaled to this corpus it is 97 * 4567/4048 = 109, "
        "within two of that layer's 107, and the two rates agree to within a tenth "
        "of a percentage point (2.40% then, 2.34% now). So the prior measurement "
        "reproduces, and the gap between 107 and 50 is 53 tests whose only "
        "assertion is inside a "
        "same-file `_assert_*` helper plus 4 that raise AssertionError directly. "
        "Both were inspected: `tests/unit/test_agent_prompt_budget_gate.py` and "
        "`tests/integration/test_two_tenant_isolation_proof.py` are typical, and "
        "every one of them can genuinely fail. Crediting them is a correction to "
        "the prior reading, not a weakening of the detector — a test that fails "
        "when the code breaks is not a vacuous test, wherever its assert lives. "
        "The divergence is recorded rather than averaged away, and the number "
        "the ratchet freezes is the reproducible one: "
        "`python -m eval.quality_detectors scan`."
    ),
}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.quality_detectors")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="per-class counts for the test corpus")
    scan.add_argument("--root", default=str(REPO_ROOT))

    report_cmd = sub.add_parser("report", help="full JSON report, no composite")
    report_cmd.add_argument("--root", default=str(REPO_ROOT))

    mutate = sub.add_parser("mutate", help="diff-scoped mutation testing")
    mutate.add_argument("--root", default=str(REPO_ROOT))
    mutate.add_argument("--base", required=True)
    mutate.add_argument("--head", default="HEAD")
    mutate.add_argument("--tests", nargs="*", default=["tests/unit"])
    mutate.add_argument("--max-mutants", type=int, default=DEFAULT_MAX_MUTANTS)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        if args.command == "scan":
            scan_result = scan_corpus(root)
            counts = counts_by_rule(scan_result.findings)
            print(f"test files scanned: {scan_result.files}")
            print(f"test functions scanned: {scan_result.test_functions}")
            for rule in RULE_CODES:
                print(f"  {rule:<24} {counts[rule]:>5}  [{enforcement(rule)}]")
            return 0

        if args.command == "report":
            print(json.dumps(build_report(root), indent=2))
            return 0

        changed = changed_python_sources(root, base=args.base, head=args.head)
        if not changed:
            print("no changed source files; nothing to mutate")
            return 0
        outcome = run_mutations(root, changed, args.tests, max_mutants=args.max_mutants)
        print(json.dumps(build_report(root, mutation=outcome)["mutation"], indent=2))
        return 0
    except (MeasurementError, BadDiffBaseError, CompositeScoreError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
