"""Additive-only migration gate — refuse non-additive schema change before a candidate starts.

Why this is a *hard block* and not a warning
--------------------------------------------
During a release, a candidate instance and the still-serving stable instance
briefly share one database. Additive-only change is precisely what makes a code
rollback safe in that window: an added nullable column or a brand-new table is
still compatible with the previous code, so reverting the code needs no schema
undo. The moment a pending migration drops or renames something, or narrows a
type, or moves rows, that property is gone — the old code no longer matches the
schema it is pointed at, and the only remaining recovery is a schema change,
which is exactly what a rollback must not require.

That is why this gate refuses rather than warns, and why the answer is never
"revert the migration": migrations in this repo are schema-only and are **never**
automatically reverted (ADR-027). Refusing before the candidate starts is the
only point at which the situation is still cheap to fix.

Relationship to the existing safe-alembic pipeline
--------------------------------------------------
This is an extension of that pipeline, not a parallel mechanism. It is a
*pre-flight, static* check of pending migration source, complementing the
*post-flight, dynamic* row-count comparison in ``safe_alembic_compare.py``:

  - ``safe_alembic_helpers.pending_revisions()`` decides *which* revisions are
    pending — this module reuses that, it does not reimplement it.
  - ``safe_alembic_compare.py`` catches row loss *after* an upgrade ran.
  - this module refuses the upgrade *before* it runs, so no candidate starts.

It deliberately does not import ``juli_backend``, SQLAlchemy or a database
connection when given explicit revisions or files, so it can run at the very
front of a release, before any release virtualenv is usable.

Callers
-------
Automatic release (issue #838) must run, and must abort on a non-zero exit,
*before starting any candidate instance*::

    python infra/scripts/migration_additive_gate.py \\
        --alembic-ini "$RELEASE_DIR/alembic.ini" \\
        --from-revision "$(... current-revision ...)"

Exit codes: 0 accepted, 3 refused, 1 usage/IO error.

The allowlist at ``safe-migrate-allowlist.txt`` is deliberately *not* consulted
here: it authorises intentional row-count decreases for the post-migration
comparison, which is a different question from whether a pending change keeps
the previous code runnable. Widening that file must never make this gate pass.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

GATE_EXIT_ACCEPTED = 0
GATE_EXIT_ERROR = 1
GATE_EXIT_REFUSED = 3

KIND_DESTRUCTIVE = "destructive"
KIND_DATA_MOVING = "data_moving"
KIND_UNVERIFIABLE = "unverifiable"

# Alembic operations that remove or rename an existing schema object. Each maps
# to a small extractor that names the offending subject from the call site.
_DROP_TABLE_OPS = frozenset({"drop_table"})
_DROP_COLUMN_OPS = frozenset({"drop_column"})
_RENAME_TABLE_OPS = frozenset({"rename_table"})
_DATA_MOVING_OPS = frozenset({"bulk_insert"})
_EXECUTE_OPS = frozenset({"execute"})

# Operations that relax rather than narrow: dropping an index or a constraint
# removes a restriction, so previously-valid code stays valid. They are not
# additive, but they are rollback-safe, which is the property this gate defends.
_TOLERATED_OPS = frozenset({"drop_index", "drop_constraint"})

_INTEGER_WIDTHS = {
    "smallinteger": 2,
    "smallint": 2,
    "integer": 4,
    "int": 4,
    "biginteger": 8,
    "bigint": 8,
}
_STRING_TYPES = frozenset(
    {"string", "varchar", "unicode", "nvarchar", "char", "text", "unicodetext", "clob"}
)
_UNBOUNDED_STRING_TYPES = frozenset({"text", "unicodetext", "clob"})
_NUMERIC_TYPES = frozenset({"numeric", "decimal"})


@dataclass(frozen=True)
class Finding:
    """One reason a pending migration is refused, named precisely enough to fix."""

    revision: str
    kind: str
    operation: str
    subject: str
    line: int
    detail: str

    def render(self) -> str:
        return (
            f"  [{self.kind}] {self.revision}:{self.line} "
            f"{self.operation} -> {self.subject}\n"
            f"      {self.detail}"
        )


@dataclass
class GateResult:
    """Verdict over every pending migration inspected."""

    inspected: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.findings

    def report(self) -> str:
        inspected = ", ".join(self.inspected) or "(none)"
        if self.accepted:
            return (
                "ADDITIVE-ONLY: ACCEPTED\n"
                f"  pending revisions inspected: {inspected}\n"
                "  Every pending change is additive, so the previous code stays "
                "compatible with this schema and a code rollback needs no schema undo."
            )
        lines = [
            "ADDITIVE-ONLY: REFUSED",
            f"  pending revisions inspected: {inspected}",
            f"  {len(self.findings)} non-additive change(s) block this release:",
        ]
        lines.extend(finding.render() for finding in self.findings)
        lines.append(
            "  This is a hard block. A candidate instance must not start: the stable "
            "release still shares this database, and these changes would leave the "
            "previous code mismatched with the schema, so a code rollback could no "
            "longer recover the release. Migrations are never automatically reverted "
            "— split this into an additive expand step and land the contract step in "
            "a later, separately-operated release."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Type comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TypeSpec:
    name: str
    args: tuple[int, ...]
    length: int | None

    def render(self) -> str:
        if self.args:
            return f"{self.name}({', '.join(str(a) for a in self.args)})"
        return f"{self.name}()"

    @property
    def key(self) -> str:
        return self.name.lower()


def _parse_type(node: ast.AST | None) -> _TypeSpec | None:
    """Read ``sa.String(length=64)`` / ``sa.BigInteger()`` into a comparable spec."""
    if node is None:
        return None
    if isinstance(node, ast.Call):
        name = _dotted_tail(node.func)
        if name is None:
            return None
        args: list[int] = []
        length: int | None = None
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                args.append(arg.value)
        for kw in node.keywords:
            if kw.arg in {"length", "precision", "scale"} and isinstance(
                kw.value, ast.Constant
            ):
                if isinstance(kw.value.value, int):
                    args.append(kw.value.value)
                    if kw.arg == "length":
                        length = kw.value.value
        if length is None and args and name.lower() in _STRING_TYPES:
            length = args[0]
        return _TypeSpec(name=name, args=tuple(args), length=length)
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _dotted_tail(node)
        if name is None:
            return None
        return _TypeSpec(name=name, args=(), length=None)
    return None


def _type_change_verdict(old: _TypeSpec, new: _TypeSpec) -> str | None:
    """Return a refusal reason, or None when the change is provably widening."""
    old_key, new_key = old.key, new.key

    if old_key in _INTEGER_WIDTHS and new_key in _INTEGER_WIDTHS:
        if _INTEGER_WIDTHS[new_key] < _INTEGER_WIDTHS[old_key]:
            return (
                f"narrows {old.render()} to {new.render()}; values the previous "
                "code can still write would no longer fit"
            )
        return None

    if old_key in _STRING_TYPES and new_key in _STRING_TYPES:
        old_unbounded = old_key in _UNBOUNDED_STRING_TYPES or old.length is None
        new_unbounded = new_key in _UNBOUNDED_STRING_TYPES or new.length is None
        if new_unbounded:
            return None
        if old_unbounded:
            return (
                f"narrows unbounded {old.render()} to {new.render()}; existing "
                "values may not fit"
            )
        if (
            new.length is not None
            and old.length is not None
            and new.length < old.length
        ):
            return (
                f"narrows {old.render()} to {new.render()}; existing values may "
                "not fit and the previous code still writes the wider value"
            )
        return None

    if old_key in _NUMERIC_TYPES and new_key in _NUMERIC_TYPES:
        if any(n < o for n, o in zip(new.args, old.args)):
            return f"narrows {old.render()} to {new.render()}"
        if len(new.args) < len(old.args):
            return (
                f"changes {old.render()} to {new.render()} with fewer precision "
                "arguments; this cannot be proven to be widening"
            )
        return None

    if old_key == new_key:
        return None

    return (
        f"changes {old.render()} to {new.render()} across type families; this "
        "cannot be proven to preserve every value the previous code can write"
    )


# ---------------------------------------------------------------------------
# AST inspection
# ---------------------------------------------------------------------------


def _dotted_tail(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # f-strings: keep the literal parts and mark interpolations, which is
        # enough to spot a SQL verb without evaluating anything.
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("<expr>")
        return "".join(parts)
    return None


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _positional_str(call: ast.Call, index: int) -> str | None:
    if len(call.args) > index:
        return _literal_str(call.args[index])
    return None


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node  # type: ignore[return-value]
    return None


def _read_revision(tree: ast.Module, fallback: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "revision":
            literal = _literal_str(value)
            if literal:
                return literal
    return fallback


def _collect_string_bindings(fn: ast.AST) -> dict[str, list[ast.AST]]:
    """Map local names to the string expressions assigned to them in upgrade()."""
    bindings: dict[str, list[ast.AST]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        if _literal_str(node.value) is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, []).append(node.value)
    return bindings


def _inspect_upgrade(fn: ast.AST, revision: str) -> list[Finding]:
    findings: list[Finding] = []
    bindings = _collect_string_bindings(fn)

    def add(kind: str, operation: str, subject: str, line: int, detail: str) -> None:
        findings.append(
            Finding(
                revision=revision,
                kind=kind,
                operation=operation,
                subject=subject,
                line=line,
                detail=detail,
            )
        )

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        op_name = _dotted_tail(node.func)
        if op_name is None or op_name in _TOLERATED_OPS:
            continue
        line = node.lineno

        if op_name in _DROP_TABLE_OPS:
            table = (
                _positional_str(node, 0)
                or _literal_str(_keyword(node, "table_name"))
                or "<unresolved table>"
            )
            add(
                KIND_DESTRUCTIVE,
                "drop_table",
                table,
                line,
                f"drops table {table}; the previous code still reads it",
            )
        elif op_name in _DROP_COLUMN_OPS:
            table = _positional_str(node, 0) or "<unresolved table>"
            column = _positional_str(node, 1) or "<unresolved column>"
            add(
                KIND_DESTRUCTIVE,
                "drop_column",
                f"{table}.{column}",
                line,
                f"drops column {table}.{column}; the previous code still "
                "selects and writes it, so a code rollback would not recover",
            )
        elif op_name in _RENAME_TABLE_OPS:
            old = _positional_str(node, 0) or "<unresolved table>"
            new = _positional_str(node, 1) or "<unresolved table>"
            add(
                KIND_DESTRUCTIVE,
                "rename_table",
                f"{old} -> {new}",
                line,
                f"renames table {old} to {new}; the previous code still queries {old}",
            )
        elif op_name == "alter_column":
            findings.extend(_inspect_alter_column(node, revision))
        elif op_name == "add_column":
            findings.extend(_inspect_add_column(node, revision))
        elif op_name in _DATA_MOVING_OPS:
            add(
                KIND_DATA_MOVING,
                "bulk_insert",
                _describe_target(node),
                line,
                "bulk_insert writes rows during migration; data-moving "
                "migrations are refused from automatic release and must be run "
                "as a separately-operated step",
            )
        elif op_name in _EXECUTE_OPS:
            findings.extend(_inspect_execute(node, revision, bindings))

    findings.sort(key=lambda f: (f.line, f.operation, f.subject))
    return findings


def _describe_target(node: ast.Call) -> str:
    if node.args:
        literal = _literal_str(node.args[0])
        if literal:
            return literal
        name = _dotted_tail(node.args[0])
        if name:
            return name
    return "<unresolved target>"


def _inspect_alter_column(node: ast.Call, revision: str) -> list[Finding]:
    table = _positional_str(node, 0) or "<unresolved table>"
    column = _positional_str(node, 1) or "<unresolved column>"
    subject = f"{table}.{column}"
    out: list[Finding] = []

    renamed = _literal_str(_keyword(node, "new_column_name"))
    if renamed:
        out.append(
            Finding(
                revision,
                KIND_DESTRUCTIVE,
                "alter_column(rename)",
                f"{subject} -> {renamed}",
                node.lineno,
                f"renames column {subject} to {renamed}; the previous code "
                f"still selects {subject}",
            )
        )

    new_type_node = _keyword(node, "type_")
    if new_type_node is not None:
        new_type = _parse_type(new_type_node)
        old_type = _parse_type(_keyword(node, "existing_type"))
        if new_type is None:
            out.append(
                Finding(
                    revision,
                    KIND_UNVERIFIABLE,
                    "alter_column(type)",
                    subject,
                    node.lineno,
                    f"changes the type of {subject} to an expression this gate "
                    "cannot read, so it cannot be proven additive",
                )
            )
        elif old_type is None:
            out.append(
                Finding(
                    revision,
                    KIND_DESTRUCTIVE,
                    "alter_column(type)",
                    subject,
                    node.lineno,
                    f"changes the type of {subject} to {new_type.render()} "
                    "without declaring existing_type, so the change cannot be "
                    "proven to be widening",
                )
            )
        else:
            reason = _type_change_verdict(old_type, new_type)
            if reason:
                out.append(
                    Finding(
                        revision,
                        KIND_DESTRUCTIVE,
                        "alter_column(type)",
                        subject,
                        node.lineno,
                        f"{subject} {reason}",
                    )
                )

    nullable_node = _keyword(node, "nullable")
    if isinstance(nullable_node, ast.Constant) and nullable_node.value is False:
        out.append(
            Finding(
                revision,
                KIND_DESTRUCTIVE,
                "alter_column(not null)",
                subject,
                node.lineno,
                f"makes existing column {subject} NOT NULL; this narrows what "
                "the previous code is allowed to write, so a code rollback "
                "would start failing inserts",
            )
        )
    return out


def _inspect_add_column(node: ast.Call, revision: str) -> list[Finding]:
    table = _positional_str(node, 0) or "<unresolved table>"
    column_node = node.args[1] if len(node.args) > 1 else _keyword(node, "column")
    if not isinstance(column_node, ast.Call):
        return []
    name = _positional_str(column_node, 0) or "<unresolved column>"
    nullable = _keyword(column_node, "nullable")
    has_default = (
        _keyword(column_node, "server_default") is not None
        or _keyword(column_node, "default") is not None
    )
    if (
        isinstance(nullable, ast.Constant)
        and nullable.value is False
        and not has_default
    ):
        return [
            Finding(
                revision,
                KIND_DESTRUCTIVE,
                "add_column(not null)",
                f"{table}.{name}",
                node.lineno,
                f"adds NOT NULL column {table}.{name} with no server_default; "
                "existing rows have no value and the previous code does not "
                "write this column, so its inserts would fail",
            )
        ]
    return []


def _inspect_execute(
    node: ast.Call, revision: str, bindings: dict[str, list[ast.AST]]
) -> list[Finding]:
    if not node.args:
        return []
    arg = node.args[0]
    candidates: list[ast.AST] = []
    literal = _literal_str(arg)
    if literal is not None:
        candidates.append(arg)
    elif isinstance(arg, ast.Name) and arg.id in bindings:
        candidates.extend(bindings[arg.id])
    elif isinstance(arg, ast.Call) and _dotted_tail(arg.func) == "text" and arg.args:
        inner = _literal_str(arg.args[0])
        if inner is not None:
            candidates.append(arg.args[0])

    if not candidates:
        return [
            Finding(
                revision,
                KIND_UNVERIFIABLE,
                "execute",
                _describe_target(node),
                node.lineno,
                "executes SQL this gate cannot read statically, so it cannot be "
                "proven additive; pass a literal statement or run it as a "
                "separately-operated step",
            )
        ]

    out: list[Finding] = []
    for candidate in candidates:
        sql = _literal_str(candidate) or ""
        for kind, operation, subject, detail in _scan_sql(sql):
            out.append(Finding(revision, kind, operation, subject, node.lineno, detail))
    return out


# ---------------------------------------------------------------------------
# Raw SQL scanning — raw SQL must not be an escape hatch around the op.* checks
# ---------------------------------------------------------------------------

_DATA_MOVING_SQL = (
    (re.compile(r"^INSERT\s+INTO\b", re.I), "INSERT"),
    (re.compile(r"^UPDATE\s+\S+\s+SET\b", re.I), "UPDATE"),
    (re.compile(r"^DELETE\s+FROM\b", re.I), "DELETE"),
    (re.compile(r"^TRUNCATE\b", re.I), "TRUNCATE"),
    (re.compile(r"^MERGE\s+INTO\b", re.I), "MERGE"),
    (re.compile(r"^COPY\b.*\bFROM\b", re.I), "COPY"),
    (re.compile(r"^SELECT\b.*\bINTO\b", re.I), "SELECT INTO"),
    (
        re.compile(r"^CREATE\s+(TABLE|MATERIALIZED\s+VIEW)\b.*\bAS\s+SELECT\b", re.I),
        "CTAS",
    ),
)

# DROP of a policy, index, trigger, constraint or default relaxes a restriction
# rather than removing data, so it stays compatible with the previous code.
_DROP_DESTRUCTIVE = re.compile(
    r"^DROP\s+(TABLE|SCHEMA|VIEW|MATERIALIZED\s+VIEW|SEQUENCE|TYPE|DATABASE|COLUMN)\b",
    re.I,
)
_ALTER_DESTRUCTIVE = (
    (re.compile(r"\bDROP\s+COLUMN\b", re.I), "DROP COLUMN"),
    (re.compile(r"\bRENAME\s+(COLUMN|TO)\b", re.I), "RENAME"),
    (
        re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b", re.I),
        "ALTER COLUMN TYPE",
    ),
    (re.compile(r"\bSET\s+NOT\s+NULL\b", re.I), "SET NOT NULL"),
)


def _split_statements(sql: str) -> list[str]:
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def _scan_sql(sql: str) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    for statement in _split_statements(sql):
        excerpt = statement if len(statement) <= 160 else statement[:157] + "..."
        matched = False
        for pattern, label in _DATA_MOVING_SQL:
            if pattern.search(statement):
                out.append(
                    (
                        KIND_DATA_MOVING,
                        f"execute({label})",
                        excerpt,
                        "this statement moves rows; data-moving migrations are "
                        "refused from automatic release and must be run as a "
                        "separately-operated step",
                    )
                )
                matched = True
                break
        if matched:
            continue
        if _DROP_DESTRUCTIVE.search(statement):
            out.append(
                (
                    KIND_DESTRUCTIVE,
                    "execute(DROP)",
                    excerpt,
                    "this statement removes a schema object the previous code "
                    "may still depend on",
                )
            )
            continue
        if re.match(r"^ALTER\s+TABLE\b", statement, re.I):
            for pattern, label in _ALTER_DESTRUCTIVE:
                if pattern.search(statement):
                    out.append(
                        (
                            KIND_DESTRUCTIVE,
                            f"execute({label})",
                            excerpt,
                            f"this statement performs {label}, which the previous "
                            "code is not compatible with",
                        )
                    )
                    break
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def evaluate_migration_source(source: str, revision: str = "<source>") -> GateResult:
    """Judge one migration's ``upgrade()`` body. ``downgrade()`` is not inspected."""
    tree = ast.parse(source)
    resolved = _read_revision(tree, revision)
    upgrade = _find_function(tree, "upgrade")
    if upgrade is None:
        return GateResult(inspected=[resolved], findings=[])
    return GateResult(
        inspected=[resolved], findings=_inspect_upgrade(upgrade, resolved)
    )


def evaluate_migration_paths(paths: list[Path]) -> GateResult:
    """Judge every pending migration file, reporting *all* offending changes."""
    result = GateResult()
    for path in paths:
        source = Path(path).read_text(encoding="utf-8")
        single = evaluate_migration_source(source, revision=Path(path).stem)
        result.inspected.extend(single.inspected)
        result.findings.extend(single.findings)
    return result


def resolve_pending_migration_paths(
    migrations_dir: Path, revisions: list[str]
) -> list[Path]:
    """Map revision ids to their migration files, in the order given."""
    migrations_dir = Path(migrations_dir)
    if not migrations_dir.is_dir():
        raise RuntimeError(f"migrations directory not found: {migrations_dir}")
    by_revision: dict[str, Path] = {}
    for path in sorted(migrations_dir.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        revision = _read_revision(tree, "")
        if revision:
            by_revision[revision] = path
    resolved: list[Path] = []
    for revision in revisions:
        path = by_revision.get(revision)
        if path is None:
            raise RuntimeError(
                f"pending revision {revision!r} has no migration file under "
                f"{migrations_dir}; refusing to release a schema change this "
                "gate cannot inspect"
            )
        resolved.append(path)
    return resolved


def _pending_from_alembic_ini(
    alembic_ini: Path, from_revision: str | None
) -> tuple[Path, list[str]]:
    """Reuse the existing safe-alembic helper rather than reimplementing discovery."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from safe_alembic_helpers import (  # noqa: PLC0415
        _resolve_script_location,
        pending_revisions,
    )
    from alembic.config import Config  # noqa: PLC0415

    alembic_ini = Path(alembic_ini)
    cfg = Config(str(alembic_ini))
    script_location = cfg.get_main_option("script_location") or ""
    versions = (
        _resolve_script_location(alembic_ini.parent, script_location) / "versions"
    )
    return versions, pending_revisions(alembic_ini, from_revision or None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse non-additive pending schema changes before any candidate "
            "instance starts. Exit 0 accepted, 3 refused."
        )
    )
    parser.add_argument(
        "--migration-file",
        action="append",
        default=[],
        help="inspect this migration file directly (repeatable)",
    )
    parser.add_argument("--migrations-dir", help="directory holding migration versions")
    parser.add_argument(
        "--revisions", help="comma-separated pending revision ids in --migrations-dir"
    )
    parser.add_argument(
        "--alembic-ini",
        help="resolve pending revisions via the existing safe-alembic helper",
    )
    parser.add_argument(
        "--from-revision", default="", help="the database's current revision"
    )
    args = parser.parse_args(argv)

    try:
        if args.migration_file:
            paths = [Path(p) for p in args.migration_file]
        elif args.alembic_ini:
            versions_dir, revisions = _pending_from_alembic_ini(
                Path(args.alembic_ini), args.from_revision
            )
            paths = resolve_pending_migration_paths(versions_dir, revisions)
        elif args.migrations_dir is not None and args.revisions is not None:
            revisions = [r.strip() for r in args.revisions.split(",") if r.strip()]
            paths = resolve_pending_migration_paths(
                Path(args.migrations_dir), revisions
            )
        else:
            parser.error(
                "provide --migration-file, or --alembic-ini, or "
                "--migrations-dir with --revisions"
            )
            return GATE_EXIT_ERROR
        result = evaluate_migration_paths(paths)
    except Exception as exc:  # noqa: BLE001 - surfaced as a usage/IO error
        print(f"ADDITIVE-ONLY: ERROR\n  {exc}", file=sys.stderr)
        return GATE_EXIT_ERROR

    print(result.report())
    return GATE_EXIT_ACCEPTED if result.accepted else GATE_EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
