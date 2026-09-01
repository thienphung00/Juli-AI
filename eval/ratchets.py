"""Debt ratchets: freeze today's standard as a set of identities (#1462).

Future agents pattern-match on what is already in the tree, so entropy compounds
— it is the one failure mode with a positive feedback loop already running. This
module measures that debt and fails when it grows.

Debt is a **set of identities** — ``(normalized_path, symbol, rule_code)`` — and
never a count. A count is gameable two ways, and both reward the wrong move:

1. Delete five suppressions in dead code and add five in shipped code. The count
   holds; the codebase is worse. Two identities-per-path sets disagree, so the
   ratchet fails.
2. Widen ``ignore_errors`` and the suppression count *falls*, so the single worst
   available action scores as the largest possible improvement. ``suppressions``
   alone cannot see this, which is why ``mypy_statement_coverage`` is measured
   beside it as a scalar that **must not fall**.

An identity may leave the set — that is a fix, and on merge the baseline tightens
to exclude it. An identity entering the set is a failure.

Ratchets are **factual** gates: ``check`` compares two recorded sets and cannot
infer intent, so it blocks from day one with no false-positive risk. Even the
classes whose measurer is a heuristic (``unused_ts_exports``) are factual as
ratchets, because both sides of the comparison are produced by the same measurer
— an over-broad reading is already in the baseline and can only ever depart.

**Tighten only on merge, never mid-PR.** ``check`` never writes. ``tighten`` is a
separate call, and it refuses to run on a measurement that does not pass.

**Fail closed.** A class whose measurement raises is recorded in ``errors`` and
produces an ``unmeasurable`` violation. It is never folded into "clean". A class
in the baseline that the measurement did not produce fails; a measured class with
no baseline entry fails too — an unknown quantity is not a clean one.

Standard library only. CI installs ``./backend[dev] -c backend/constraints.txt``
and nothing else, so a third-party import here is a collection error in CI even
when it passes locally.

CLI::

    python -m eval.ratchets measure            # print the current reading
    python -m eval.ratchets check              # compare tree to committed baseline
    python -m eval.ratchets measure --write    # regenerate the baseline (merge only)
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).resolve().parent / "baselines" / "debt_ratchet_baseline.json"

#: Suppression lines reported in issue #1462 (144 `type: ignore` + 250 `noqa`),
#: verified against an earlier `origin/main`. Carried as a reference point only:
#: the baseline freezes what the tree actually measures, and the divergence from
#: this figure is recorded in the baseline rather than reconciled away.
REPORTED_SUPPRESSION_LINES = 394

IDENTITY_CLASS = "identities"
SCALAR_CLASS = "scalar"

MUST_NOT_RISE = "must_not_rise"
MUST_NOT_FALL = "must_not_fall"

#: Floating-point slack for scalar comparisons. Tight enough that a single
#: excluded module in a repo of any size trips it.
SCALAR_EPSILON = 1e-9

#: The four roots the 394 figure was verified over, plus `eval` itself. Without
#: `eval`, moving a suppression into this package would make the count fall —
#: gaming path 1 with extra steps. The baseline records the four-root subtotal
#: separately so the reported figure stays reconcilable.
SUPPRESSION_ROOTS: tuple[str, ...] = ("backend", "tests", "scripts", "agent-runtime", "eval")
REPORTED_SUPPRESSION_ROOTS: tuple[str, ...] = ("backend", "tests", "scripts", "agent-runtime")

#: Where `mypy backend/` is pointed by CI, and the config that governs it.
MYPY_CORPUS_ROOT = "backend"
MYPY_CONFIG = "backend/pyproject.toml"

TS_ROOTS: tuple[str, ...] = ("apps", "packages")
TS_SUFFIXES = frozenset({".ts", ".tsx"})

DOC_SUFFIXES = frozenset({".md", ".mdc"})

TIER1_ROOT_DOC = "CLAUDE.md"
TIER1_RULES_DIR = ".cursor/rules"
#: CLAUDE.md's own accounting: bytes divided by four.
BYTES_PER_TOKEN = 4

PRUNED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".turbo",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "venv",
    }
)

MODULE_SYMBOL = "<module>"
ANY_RULE = "*"


class MeasurementError(Exception):
    """A debt class could not be measured. Always a failure, never a clean read."""


# ---------------------------------------------------------------------------
# identities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Identity:
    """One unit of debt: where it lives, what encloses it, and which rule it silences.

    Deliberately not line-numbered. A line number would churn the whole baseline
    every time a file gains an import, and the churn would drown the one arrival
    that matters. ``symbol`` is coarse enough to survive reformatting and fine
    enough that moving a suppression into a different function is a new identity.
    """

    debt_class: str
    path: str
    symbol: str
    rule_code: str

    def key(self) -> str:
        return "\t".join((self.debt_class, self.path, self.symbol, self.rule_code))

    @classmethod
    def parse(cls, key: str) -> Identity:
        parts = key.split("\t")
        if len(parts) != 4:
            raise MeasurementError(f"malformed identity key: {key!r}")
        return cls(*parts)


@dataclass(frozen=True)
class ClassMeasurement:
    """One debt class as read from the tree."""

    name: str
    kind: str
    occurrences: Mapping[Identity, int] = field(default_factory=dict)
    scalar: float | None = None
    direction: str | None = None
    stats: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.occurrences.values())


@dataclass(frozen=True)
class Measurement:
    repo_root: Path
    classes: Mapping[str, ClassMeasurement] = field(default_factory=dict)
    errors: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Violation:
    debt_class: str
    kind: str
    detail: str
    identity: Identity | None = None


@dataclass(frozen=True)
class RatchetResult:
    ok: bool
    violations: tuple[Violation, ...] = ()
    departed: tuple[Identity, ...] = ()

    def render(self) -> str:
        if self.ok:
            gone = f", {len(self.departed)} identities departed" if self.departed else ""
            return f"PASS: no new debt identities{gone}"
        lines = [f"FAIL: {len(self.violations)} ratchet violation(s)"]
        for violation in self.violations:
            lines.append(f"  [{violation.debt_class}/{violation.kind}] {violation.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# shared filesystem walk
# ---------------------------------------------------------------------------


def _is_pruned(repo_root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(repo_root).parts
    except ValueError:  # pragma: no cover - defensive
        return True
    return any(part in PRUNED_DIRS or part.endswith(".egg-info") for part in parts)


def _walk(repo_root: Path, roots: Iterable[str], suffixes: frozenset[str]) -> Iterator[Path]:
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in suffixes or not path.is_file():
                continue
            if _is_pruned(repo_root, path):
                continue
            yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MeasurementError(f"unreadable file {path}: {exc}") from exc


def _rel(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


# ---------------------------------------------------------------------------
# class: suppressions
# ---------------------------------------------------------------------------

_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?:\[([^\]]*)\])?")
_NOQA = re.compile(r"#\s*noqa(?::\s*([A-Za-z]+[0-9]+(?:\s*,\s*[A-Za-z]+[0-9]+)*))?")


def _symbol_map(source: str, path: Path) -> dict[int, str]:
    """Map every line to its innermost enclosing ``class``/``def`` qualname."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise MeasurementError(f"unparseable python in {path}: {exc}") from exc

    mapping: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                end = child.end_lineno or child.lineno
                for line in range(start, end + 1):
                    mapping[line] = qualname
                visit(child, qualname)

    visit(tree, "")
    return mapping


def _codes(raw: str | None) -> list[str]:
    if not raw:
        return [ANY_RULE]
    found = [chunk.strip().upper() for chunk in raw.split(",") if chunk.strip()]
    return found or [ANY_RULE]


def measure_suppressions(repo_root: Path) -> ClassMeasurement:
    """Every ``# type: ignore`` and ``# noqa`` in the Python corpus.

    Read from ``tokenize`` COMMENT tokens rather than by line regex, so that a
    string literal that merely *contains* the text — a test fixture, this
    module's own docstring — is not counted as debt. A file that cannot be
    tokenized or parsed raises: a scan that skipped it would under-report, and
    under-reporting is the failure mode this whole module exists to prevent.
    """
    occurrences: Counter[Identity] = Counter()
    lines = 0
    reported_lines = 0
    files = 0
    by_rule_code: Counter[str] = Counter()

    for path in _walk(repo_root, SUPPRESSION_ROOTS, frozenset({".py"})):
        files += 1
        source = _read_text(path)
        symbols = _symbol_map(source, path)
        rel = _rel(repo_root, path)
        in_reported_root = rel.split("/", 1)[0] in REPORTED_SUPPRESSION_ROOTS
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
            raise MeasurementError(f"untokenizable python in {path}: {exc}") from exc

        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            hits = 0
            for pattern, kind in ((_TYPE_IGNORE, "type-ignore"), (_NOQA, "noqa")):
                for match in pattern.finditer(token.string):
                    hits += 1
                    for code in _codes(match.group(1)):
                        rule = f"{kind}:{code}"
                        occurrences[
                            Identity(
                                "suppressions",
                                rel,
                                symbols.get(token.start[0], MODULE_SYMBOL),
                                rule,
                            )
                        ] += 1
                        by_rule_code[rule] += 1
            if hits:
                lines += 1
                if in_reported_root:
                    reported_lines += 1

    return ClassMeasurement(
        name="suppressions",
        kind=IDENTITY_CLASS,
        occurrences=dict(occurrences),
        stats={
            "files_scanned": files,
            "lines": lines,
            "occurrences": sum(occurrences.values()),
            "distinct_identities": len(occurrences),
            "lines_in_reported_roots": reported_lines,
            "by_rule_code": dict(sorted(by_rule_code.items())),
        },
    )


# ---------------------------------------------------------------------------
# class: mypy_statement_coverage
# ---------------------------------------------------------------------------


def _module_name(repo_root: Path, path: Path) -> str:
    """Dotted module name, resolved by walking up while ``__init__.py`` exists."""
    parts = [path.stem]
    parent = path.parent
    while (parent / "__init__.py").is_file() and parent != repo_root:
        parts.append(parent.name)
        parent = parent.parent
    if parts[0] == "__init__":
        parts = parts[1:] or ["__init__"]
    return ".".join(reversed(parts))


def _module_matches(pattern: str, module: str) -> bool:
    """mypy override semantics: an exact name, or a ``.``-prefix, or a ``*`` glob."""
    if pattern == module:
        return True
    if pattern.endswith(".*") and (module == pattern[:-2] or module.startswith(pattern[:-1])):
        return True
    if "*" in pattern:
        regex = "^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$"
        return re.match(regex, module) is not None
    return False


def measure_mypy_statement_coverage(repo_root: Path) -> ClassMeasurement:
    """Share of statements in the mypy corpus that mypy will actually check.

    This is the paired guard against the second gaming path. Widening
    ``ignore_errors`` (or ``exclude``) makes the suppression count fall while
    making the codebase less checked; that shows up here immediately as a scalar
    that must not fall.

    Computed from the config and the AST rather than by invoking mypy: it is
    deterministic, it needs no type-check run inside a 30-second test budget, and
    it reads exactly the knob the gaming path turns.
    """
    config_path = repo_root / MYPY_CONFIG
    if not config_path.is_file():
        raise MeasurementError(f"no mypy config at {MYPY_CONFIG}")
    try:
        config = tomllib.loads(_read_text(config_path))
    except tomllib.TOMLDecodeError as exc:
        raise MeasurementError(f"unparseable {MYPY_CONFIG}: {exc}") from exc

    mypy_config = config.get("tool", {}).get("mypy", {})
    if not isinstance(mypy_config, dict):
        raise MeasurementError(f"[tool.mypy] in {MYPY_CONFIG} is not a table")

    exclude_raw = mypy_config.get("exclude", [])
    excludes = [exclude_raw] if isinstance(exclude_raw, str) else list(exclude_raw)
    try:
        exclude_res = [re.compile(pattern) for pattern in excludes]
    except re.error as exc:
        raise MeasurementError(f"unparseable mypy exclude pattern: {exc}") from exc

    ignored_patterns: list[str] = []
    for override in mypy_config.get("overrides", []) or []:
        if not isinstance(override, dict):
            raise MeasurementError("malformed [[tool.mypy.overrides]] entry")
        if not override.get("ignore_errors"):
            continue
        module = override.get("module", [])
        ignored_patterns.extend([module] if isinstance(module, str) else list(module))

    disabled_codes = list(mypy_config.get("disable_error_code", []) or [])

    checked = 0
    total = 0
    unchecked_modules: list[str] = []
    files = 0
    for path in _walk(repo_root, (MYPY_CORPUS_ROOT,), frozenset({".py"})):
        files += 1
        rel = _rel(repo_root, path)
        source = _read_text(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise MeasurementError(f"unparseable python in {path}: {exc}") from exc
        statements = sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt))
        total += statements

        module = _module_name(repo_root, path)
        excluded = any(rx.search(rel) for rx in exclude_res)
        ignored = any(_module_matches(p, module) for p in ignored_patterns)
        if excluded or ignored:
            unchecked_modules.append(module)
        else:
            checked += statements

    if total == 0:
        raise MeasurementError(f"mypy corpus {MYPY_CORPUS_ROOT}/ contains no statements")

    return ClassMeasurement(
        name="mypy_statement_coverage",
        kind=SCALAR_CLASS,
        scalar=checked / total,
        direction=MUST_NOT_FALL,
        stats={
            "files_scanned": files,
            "checked_statements": checked,
            "total_statements": total,
            "unchecked_modules": sorted(unchecked_modules),
            "exclude_patterns": excludes,
            "ignore_errors_patterns": sorted(ignored_patterns),
            "disable_error_code": sorted(disabled_codes),
        },
    )


# ---------------------------------------------------------------------------
# class: unused_ts_exports
# ---------------------------------------------------------------------------

_TS_DECL = re.compile(
    r"^\s*export\s+(?:declare\s+)?(?:async\s+)?(?:abstract\s+)?"
    r"(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
    re.M,
)
_TS_LIST = re.compile(r"^\s*export\s*\{([^}]*)\}", re.M)
_TS_WORD = re.compile(r"[A-Za-z_$][\w$]*")


def measure_unused_ts_exports(repo_root: Path) -> ClassMeasurement:
    """Named TypeScript exports referenced by no other file in the workspace.

    A heuristic reading — it is identifier-level, it does not resolve imports,
    and it deliberately ignores ``export default`` because a default export is
    renamed at the import site and cannot be matched by name. As a *ratchet* that
    is still factual: both sides of the comparison use this same definition, so
    an over-broad reading sits in the baseline from the start and can only ever
    depart. It is not a claim about what is safe to delete.
    """
    sources: dict[Path, str] = {}
    for path in _walk(repo_root, TS_ROOTS, TS_SUFFIXES):
        if path.name.endswith(".d.ts"):
            continue
        sources[path] = _read_text(path)

    words: dict[Path, set[str]] = {
        path: set(_TS_WORD.findall(text)) for path, text in sources.items()
    }

    occurrences: Counter[Identity] = Counter()
    exported = 0
    for path, text in sources.items():
        names: set[str] = {m.group(1) for m in _TS_DECL.finditer(text)}
        for match in _TS_LIST.finditer(text):
            for chunk in match.group(1).split(","):
                name = chunk.strip().split(" as ")[-1].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", name) and name != "default":
                    names.add(name)
        exported += len(names)
        rel = _rel(repo_root, path)
        for name in sorted(names):
            if any(name in other for candidate, other in words.items() if candidate != path):
                continue
            occurrences[Identity("unused_ts_exports", rel, name, "unreferenced")] += 1

    return ClassMeasurement(
        name="unused_ts_exports",
        kind=IDENTITY_CLASS,
        occurrences=dict(occurrences),
        stats={
            "files_scanned": len(sources),
            "exported_symbols": exported,
            "occurrences": sum(occurrences.values()),
        },
    )


# ---------------------------------------------------------------------------
# class: broken_doc_refs
# ---------------------------------------------------------------------------

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_NON_PATH = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|<|\$|\{)")


def measure_broken_doc_refs(repo_root: Path) -> ClassMeasurement:
    """Relative markdown links whose target does not exist on disk.

    Purely factual: it resolves a path and stats it. External URLs, anchors and
    template placeholders are skipped because they are not path references.
    """
    occurrences: Counter[Identity] = Counter()
    checked = 0
    docs = 0
    broken_docs: set[str] = set()

    for path in _walk(repo_root, ("",), DOC_SUFFIXES):
        docs += 1
        text = _read_text(path)
        rel = _rel(repo_root, path)
        for match in _MD_LINK.finditer(text):
            raw = match.group(1)
            if _NON_PATH.match(raw):
                continue
            checked += 1
            target = raw.split("#", 1)[0]
            if not target:
                continue
            resolved = (
                repo_root / target.lstrip("/") if target.startswith("/") else path.parent / target
            )
            if not resolved.exists():
                occurrences[Identity("broken_doc_refs", rel, target, "missing_path")] += 1
                broken_docs.add(rel)

    return ClassMeasurement(
        name="broken_doc_refs",
        kind=IDENTITY_CLASS,
        occurrences=dict(occurrences),
        stats={
            "docs_scanned": docs,
            "relative_links_checked": checked,
            "occurrences": sum(occurrences.values()),
            "docs_with_broken_refs": len(broken_docs),
        },
    )


# ---------------------------------------------------------------------------
# class: tier1_always_on_tokens
# ---------------------------------------------------------------------------


def measure_tier1_always_on_tokens(repo_root: Path) -> ClassMeasurement:
    """Bytes-over-four for CLAUDE.md plus every ``alwaysApply: true`` Cursor rule.

    This is context every agent pays for on every request, so it must not rise.
    A missing CLAUDE.md raises rather than reading as zero tokens — zero would be
    the best possible score for the worst possible state.
    """
    root_doc = repo_root / TIER1_ROOT_DOC
    if not root_doc.is_file():
        raise MeasurementError(f"{TIER1_ROOT_DOC} is absent; Tier-1 budget is unmeasurable")

    rules_dir = repo_root / TIER1_RULES_DIR
    if not rules_dir.is_dir():
        raise MeasurementError(f"{TIER1_RULES_DIR} is absent; Tier-1 budget is unmeasurable")

    files: list[Path] = [root_doc]
    for rule in sorted(rules_dir.glob("*.mdc")):
        if re.search(r"^alwaysApply:\s*true\s*$", _read_text(rule), re.M):
            files.append(rule)

    per_file = {_rel(repo_root, f): f.stat().st_size for f in files}
    total_bytes = sum(per_file.values())

    return ClassMeasurement(
        name="tier1_always_on_tokens",
        kind=SCALAR_CLASS,
        scalar=float(total_bytes // BYTES_PER_TOKEN),
        direction=MUST_NOT_RISE,
        stats={
            "always_on_files": sorted(per_file),
            "bytes_per_file": dict(sorted(per_file.items())),
            "total_bytes": total_bytes,
            "bytes_per_token": BYTES_PER_TOKEN,
        },
    )


# ---------------------------------------------------------------------------
# registry + measurement
# ---------------------------------------------------------------------------

Measurer = Callable[[Path], ClassMeasurement]

MEASURERS: dict[str, Measurer] = {
    "suppressions": measure_suppressions,
    "mypy_statement_coverage": measure_mypy_statement_coverage,
    "unused_ts_exports": measure_unused_ts_exports,
    "broken_doc_refs": measure_broken_doc_refs,
    "tier1_always_on_tokens": measure_tier1_always_on_tokens,
}

DEBT_CLASSES: tuple[str, ...] = tuple(MEASURERS)


def measure(
    repo_root: Path,
    classes: Sequence[str] | None = None,
    measurers: Mapping[str, Measurer] | None = None,
) -> Measurement:
    """Read every requested debt class, recording failures instead of raising.

    Failures are collected per class so one unmeasurable class does not hide the
    readings of the others — but a recorded failure is still a hard failure at
    ``check`` time. ``measurers`` exists so a test can inject a measurer that
    raises; the production path never passes it.
    """
    repo_root = Path(repo_root)
    registry = dict(MEASURERS if measurers is None else measurers)
    names = list(DEBT_CLASSES if classes is None else classes)

    results: dict[str, ClassMeasurement] = {}
    errors: dict[str, str] = {}
    for name in names:
        measurer = registry.get(name)
        if measurer is None:
            errors[name] = f"no measurer registered for debt class {name!r}"
            continue
        try:
            results[name] = measurer(repo_root)
        except MeasurementError as exc:
            errors[name] = str(exc)
        except Exception as exc:  # fail closed on anything at all
            errors[name] = f"{type(exc).__name__}: {exc}"

    return Measurement(repo_root=repo_root, classes=results, errors=errors)


# ---------------------------------------------------------------------------
# baseline serialisation
# ---------------------------------------------------------------------------


def _class_to_json(measurement: ClassMeasurement) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": measurement.kind,
        "stats": dict(measurement.stats),
    }
    if measurement.kind == IDENTITY_CLASS:
        payload["occurrences"] = {
            identity.key(): count
            for identity, count in sorted(measurement.occurrences.items(), key=lambda kv: kv[0])
        }
    else:
        payload["scalar"] = measurement.scalar
        payload["direction"] = measurement.direction
    return payload


def baseline_from(measurement: Measurement) -> dict[str, Any]:
    """Serialise a measurement as a baseline document.

    Refuses to freeze a reading that failed: a baseline missing a class it could
    not measure would make that class permanently invisible.
    """
    if measurement.errors:
        raise MeasurementError(
            "cannot baseline a failed measurement: "
            + "; ".join(f"{name}: {msg}" for name, msg in sorted(measurement.errors.items()))
        )

    classes = {name: _class_to_json(cls) for name, cls in sorted(measurement.classes.items())}

    suppressions = measurement.classes.get("suppressions")
    if suppressions is not None:
        in_reported_roots = suppressions.stats["lines_in_reported_roots"]
        classes["suppressions"]["reportedLineDivergence"] = {
            "reported": REPORTED_SUPPRESSION_LINES,
            "measured": in_reported_roots,
            "delta": in_reported_roots - REPORTED_SUPPRESSION_LINES,
            "reportedRoots": list(REPORTED_SUPPRESSION_ROOTS),
            "measuredAllRoots": suppressions.stats["lines"],
            "allRoots": list(SUPPRESSION_ROOTS),
            "note": (
                "#1462 reports 394 suppression lines over "
                f"{' '.join(REPORTED_SUPPRESSION_ROOTS)}. `measured` is the "
                "like-for-like reading over those same roots; `measuredAllRoots` "
                "adds eval/, which is ratcheted so that moving a suppression into "
                "this package cannot make the count fall. The measurement wins — "
                "this records the divergence rather than reconciling it away."
            ),
        }

    return {
        "issue": 1462,
        "schema": "debt-ratchet-baseline/1",
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "python -m eval.ratchets measure --write",
        "classes": classes,
    }


def write_baseline(path: Path, baseline: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, Any]:
    """Read a baseline, raising on anything that is not a well-formed one.

    Fail-closed: an absent, unreadable or malformed baseline must never degrade
    to an empty set, because an empty baseline passes everything.
    """
    path = Path(path)
    if not path.is_file():
        raise MeasurementError(f"no baseline at {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MeasurementError(f"unreadable baseline {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("classes"), dict):
        raise MeasurementError(f"malformed baseline {path}: missing 'classes' table")
    return loaded


def _baseline_occurrences(entry: Mapping[str, Any], name: str) -> dict[Identity, int]:
    raw = entry.get("occurrences")
    if not isinstance(raw, dict):
        raise MeasurementError(f"baseline class {name!r} has no 'occurrences' table")
    return {Identity.parse(key): int(count) for key, count in raw.items()}


# ---------------------------------------------------------------------------
# check + tighten
# ---------------------------------------------------------------------------


def check(baseline: Mapping[str, Any], measurement: Measurement) -> RatchetResult:
    """Compare a measurement against a baseline. Never writes.

    An identity leaving the set is fine. An identity entering it, or an existing
    identity gaining occurrences, is a violation. A scalar moving in its
    forbidden direction is a violation. Anything unmeasurable is a violation.
    """
    baselined = baseline.get("classes", {})
    if not isinstance(baselined, dict):
        raise MeasurementError("malformed baseline: 'classes' is not a table")

    violations: list[Violation] = []
    departed: list[Identity] = []

    for name, message in sorted(measurement.errors.items()):
        violations.append(
            Violation(
                debt_class=name,
                kind="unmeasurable",
                detail=(f"{name} could not be measured and is not treated as clean: {message}"),
            )
        )

    for name in sorted(measurement.classes):
        if name not in baselined and name not in measurement.errors:
            violations.append(
                Violation(
                    debt_class=name,
                    kind="unbaselined_class",
                    detail=(
                        f"{name} was measured but has no baseline entry; an unknown "
                        "quantity of debt is not a clean one"
                    ),
                )
            )

    for name in sorted(baselined):
        if name in measurement.errors:
            continue  # already reported as unmeasurable
        current = measurement.classes.get(name)
        if current is None:
            violations.append(
                Violation(
                    debt_class=name,
                    kind="missing_class",
                    detail=f"{name} is baselined but was not measured",
                )
            )
            continue

        entry = baselined[name]
        kind = entry.get("kind")
        if kind != current.kind:
            violations.append(
                Violation(
                    debt_class=name,
                    kind="kind_mismatch",
                    detail=f"{name} is baselined as {kind!r} but measured as {current.kind!r}",
                )
            )
            continue

        if kind == IDENTITY_CLASS:
            recorded = _baseline_occurrences(entry, name)
            for identity, count in sorted(current.occurrences.items()):
                was = recorded.get(identity, 0)
                if was == 0:
                    violations.append(
                        Violation(
                            debt_class=name,
                            kind="new_identity",
                            detail=(
                                f"new debt identity {identity.path}::{identity.symbol} "
                                f"[{identity.rule_code}]"
                            ),
                            identity=identity,
                        )
                    )
                elif count > was:
                    violations.append(
                        Violation(
                            debt_class=name,
                            kind="increased_occurrences",
                            detail=(
                                f"{identity.path}::{identity.symbol} [{identity.rule_code}] "
                                f"rose from {was} to {count}"
                            ),
                            identity=identity,
                        )
                    )
            for identity, was in sorted(recorded.items()):
                if current.occurrences.get(identity, 0) < was:
                    departed.append(identity)
        else:
            recorded_scalar = entry.get("scalar")
            direction = entry.get("direction")
            if not isinstance(recorded_scalar, (int, float)) or current.scalar is None:
                violations.append(
                    Violation(
                        debt_class=name,
                        kind="unmeasurable",
                        detail=f"{name} has no comparable scalar on one side",
                    )
                )
                continue
            if direction == MUST_NOT_FALL and current.scalar < recorded_scalar - SCALAR_EPSILON:
                violations.append(
                    Violation(
                        debt_class=name,
                        kind="scalar_regression",
                        detail=(
                            f"{name} fell from {recorded_scalar} to {current.scalar}; "
                            "it must not fall"
                        ),
                    )
                )
            elif direction == MUST_NOT_RISE and current.scalar > recorded_scalar + SCALAR_EPSILON:
                violations.append(
                    Violation(
                        debt_class=name,
                        kind="scalar_regression",
                        detail=(
                            f"{name} rose from {recorded_scalar} to {current.scalar}; "
                            "it must not rise"
                        ),
                    )
                )
            elif direction not in (MUST_NOT_FALL, MUST_NOT_RISE):
                violations.append(
                    Violation(
                        debt_class=name,
                        kind="unmeasurable",
                        detail=f"{name} has no ratchet direction; cannot be compared",
                    )
                )

    return RatchetResult(
        ok=not violations,
        violations=tuple(violations),
        departed=tuple(sorted(departed)),
    )


def tighten(baseline: Mapping[str, Any], measurement: Measurement) -> dict[str, Any]:
    """Lower the floor to the current reading. **Merge only.**

    Separate from ``check`` on purpose: mid-PR tightening would let a branch
    ratify its own regressions. It refuses outright on a measurement that does
    not pass, so debt can never be tightened *upwards*.
    """
    result = check(baseline, measurement)
    if not result.ok:
        raise MeasurementError(
            "refusing to tighten against a failing measurement:\n" + result.render()
        )
    tightened = baseline_from(measurement)
    tightened["tightenedFrom"] = baseline.get("generatedAt")
    return tightened


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _summarise(measurement: Measurement) -> dict[str, Any]:
    out: dict[str, Any] = {"errors": dict(measurement.errors), "classes": {}}
    for name, cls in sorted(measurement.classes.items()):
        entry: dict[str, Any] = {"kind": cls.kind, "stats": dict(cls.stats)}
        if cls.kind == IDENTITY_CLASS:
            entry["distinctIdentities"] = len(cls.occurrences)
            entry["occurrences"] = cls.total
        else:
            entry["scalar"] = cls.scalar
            entry["direction"] = cls.direction
        out["classes"][name] = entry
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.ratchets", description=__doc__)
    parser.add_argument("command", choices=("measure", "check", "tighten"))
    parser.add_argument("--repo-root", default=str(REPO_ROOT), type=Path)
    parser.add_argument("--baseline", default=str(BASELINE_PATH), type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the baseline (merge only; never mid-PR)",
    )
    args = parser.parse_args(argv)

    measurement = measure(args.repo_root)

    if args.command == "measure":
        print(json.dumps(_summarise(measurement), indent=2))
        if measurement.errors:
            return 1
        if args.write:
            write_baseline(args.baseline, baseline_from(measurement))
            print(f"wrote baseline -> {args.baseline}")
        return 0

    try:
        baseline = load_baseline(args.baseline)
    except MeasurementError as exc:
        print(f"FAIL: {exc}")
        return 1

    if args.command == "check":
        result = check(baseline, measurement)
        print(result.render())
        return 0 if result.ok else 1

    try:
        tightened = tighten(baseline, measurement)
    except MeasurementError as exc:
        print(f"FAIL: {exc}")
        return 1
    if args.write:
        write_baseline(args.baseline, tightened)
        print(f"tightened baseline -> {args.baseline}")
    else:
        print(json.dumps(_summarise(measurement), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
