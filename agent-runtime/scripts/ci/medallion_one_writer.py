"""Static one-writer enforcement for CDP medallion tables (#608 / ADR-046)."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402

BACKEND_ROOT = REPO_ROOT / "backend" / "src" / "juli_backend"
DATABASE_MODULE_MD = BACKEND_ROOT / "database" / "MODULE.md"
ETL_MODULE_MD = BACKEND_ROOT / "services" / "etl" / "MODULE.md"
REPOS_FILE = BACKEND_ROOT / "repositories" / "repos.py"

REPO_DEFINITIONS_MODULE = "juli_backend.repositories.repos"


@dataclass(frozen=True)
class MedallionWriteRule:
    """One medallion table/layer and its allowed writer module prefixes."""

    layer: str
    table: str
    repo_class: str
    write_methods: frozenset[str]
    allowed_module_prefixes: tuple[str, ...]
    owner_label: str


MEDALLION_WRITE_RULES: tuple[MedallionWriteRule, ...] = (
    MedallionWriteRule(
        layer="bronze",
        table="bronze.order_raw_payloads / bronze.return_raw_payloads",
        repo_class="BronzeOrderRawPayloadsRepo",
        write_methods=frozenset({"append_batch"}),
        allowed_module_prefixes=("juli_backend.services.etl",),
        owner_label="Ingest / ETL bronze writer",
    ),
    MedallionWriteRule(
        layer="bronze",
        table="bronze.return_raw_payloads",
        repo_class="BronzeReturnRawPayloadsRepo",
        write_methods=frozenset({"append_batch"}),
        allowed_module_prefixes=("juli_backend.services.etl",),
        owner_label="Ingest / ETL bronze writer",
    ),
    MedallionWriteRule(
        layer="silver",
        table="silver.orders",
        repo_class="OrdersRepo",
        write_methods=frozenset({"upsert"}),
        allowed_module_prefixes=("juli_backend.services.etl",),
        owner_label="Domain silver upsert service",
    ),
    MedallionWriteRule(
        layer="silver",
        table="silver.returns",
        repo_class="ReturnsRepo",
        write_methods=frozenset({"upsert"}),
        allowed_module_prefixes=("juli_backend.services.etl",),
        owner_label="Domain silver upsert service",
    ),
    MedallionWriteRule(
        layer="gold",
        table="gold.kpi_envelopes",
        repo_class="GoldKpiEnvelopesRepo",
        write_methods=frozenset({"upsert"}),
        allowed_module_prefixes=(
            "juli_backend.services.gold_kpi_envelope_serving",
            "juli_backend.services.analytics_kpi_precompute",
        ),
        owner_label="Shared Compute gold writer (A1; A0 shell via gold_kpi_envelope_serving)",
    ),
    MedallionWriteRule(
        layer="gold",
        table="gold.kpi_envelopes",
        repo_class="AnalyticsKpiEnvelopesRepo",
        write_methods=frozenset({"upsert"}),
        allowed_module_prefixes=(
            "juli_backend.services.gold_kpi_envelope_serving",
            "juli_backend.services.analytics_kpi_precompute",
        ),
        owner_label="Shared Compute gold writer (compat adapter; A1 consolidates)",
    ),
    MedallionWriteRule(
        layer="ops",
        table="ops.analytics_backfill_partitions",
        repo_class="AnalyticsBackfillPartitionsRepo",
        write_methods=frozenset({"mark_complete", "mark_failed"}),
        allowed_module_prefixes=("juli_backend.services.analytics_backfill",),
        owner_label="Backfill / batch partition repo",
    ),
)

_RULE_BY_REPO: dict[str, tuple[MedallionWriteRule, ...]] = {}
for _rule in MEDALLION_WRITE_RULES:
    _RULE_BY_REPO.setdefault(_rule.repo_class, []).append(_rule)


def module_path_from_file(path: Path) -> str:
    rel = path.relative_to(BACKEND_ROOT.parent)
    return str(rel.with_suffix("")).replace("/", ".")


def _is_allowed(module: str, allowed_prefixes: Iterable[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in allowed_prefixes)


class _RepoWriteVisitor(ast.NodeVisitor):
    """Detect repo write method calls and attribute bindings in a module."""

    def __init__(self, *, module: str, source: str) -> None:
        self.module = module
        self.source = source
        self.imported_repos: set[str] = set()
        self.repo_aliases: dict[str, str] = {}
        self.violations: list[str] = []
        self._class_attr_bindings: dict[str, dict[str, str]] = {}
        self._current_class: str | None = None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.endswith("repositories.repos"):
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name in _RULE_BY_REPO:
                    self.imported_repos.add(alias.name)
                    self.repo_aliases[name] = alias.name
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous = self._current_class
        self._current_class = node.name
        self._class_attr_bindings.setdefault(node.name, {})
        self.generic_visit(node)
        self._current_class = previous

    def visit_Assign(self, node: ast.Assign) -> None:
        repo_class = self._repo_from_call(node.value)
        if repo_class is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.repo_aliases[target.id] = repo_class
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and self._current_class is not None
                ):
                    self._class_attr_bindings[self._current_class][target.attr] = repo_class
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            repo_class = self._repo_for_receiver(node.func.value)
            if repo_class is not None:
                self._check_write(repo_class, method, node.lineno)
        self.generic_visit(node)

    def _repo_from_call(self, node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Name) and func.id in _RULE_BY_REPO:
            return func.id
        if isinstance(func, ast.Name) and func.id in self.repo_aliases:
            return self.repo_aliases[func.id]
        return None

    def _repo_for_receiver(self, receiver: ast.AST) -> str | None:
        if isinstance(receiver, ast.Name):
            return self.repo_aliases.get(receiver.id)
        if (
            isinstance(receiver, ast.Attribute)
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id == "self"
            and self._current_class is not None
        ):
            return self._class_attr_bindings.get(self._current_class, {}).get(receiver.attr)
        direct = self._repo_from_call(receiver)
        if direct is not None:
            return direct
        return None

    def _check_write(self, repo_class: str, method: str, lineno: int) -> None:
        rules = _RULE_BY_REPO.get(repo_class, ())
        for rule in rules:
            if method not in rule.write_methods:
                continue
            if _is_allowed(self.module, rule.allowed_module_prefixes):
                return
            self.violations.append(
                f"{self.module}:{lineno}: {repo_class}.{method}() writes {rule.table} "
                f"(owner: {rule.owner_label}); module not in allowed writers "
                f"{list(rule.allowed_module_prefixes)}"
            )
            return


def scan_medallion_write_violations(
    *,
    backend_root: Path | None = None,
    extra_sources: dict[str, str] | None = None,
) -> list[str]:
    """Return violation messages for medallion write calls outside allowed owners."""
    root = backend_root or BACKEND_ROOT
    violations: list[str] = []

    paths = sorted(root.rglob("*.py"))
    if extra_sources:
        for module, source in extra_sources.items():
            violations.extend(_scan_source(module, source))

    for path in paths:
        if path.name == "__init__.py" and path.parent == root:
            continue
        if path.resolve() == REPOS_FILE.resolve():
            continue
        module = module_path_from_file(path)
        violations.extend(_scan_source(module, path.read_text(encoding="utf-8")))

    return sorted(set(violations))


def _scan_source(module: str, source: str) -> list[str]:
    if module == REPO_DEFINITIONS_MODULE:
        return []
    try:
        tree = ast.parse(source, filename=module)
    except SyntaxError as exc:
        return [f"{module}: syntax error — {exc}"]
    visitor = _RepoWriteVisitor(module=module, source=source)
    visitor.visit(tree)
    return visitor.violations


def validate_module_docs() -> list[str]:
    """Ensure MODULE.md files document the one-writer map and Q4 orchestrator hooks."""
    errors: list[str] = []
    if not DATABASE_MODULE_MD.is_file():
        errors.append(f"missing {DATABASE_MODULE_MD}")
        return errors

    db_text = DATABASE_MODULE_MD.read_text(encoding="utf-8")
    required_phrases = (
        "One-writer ownership map",
        "silver.orders",
        "silver.returns",
        "gold.kpi_envelopes",
        "ops.analytics_backfill_partitions",
        "bronze.order_raw_payloads",
        "gold.ml_feature_snapshots",
    )
    for phrase in required_phrases:
        if phrase not in db_text:
            errors.append(f"database/MODULE.md missing required phrase: {phrase!r}")

    q4_keywords = (
        "Shared Compute Orchestrator",
        "bronze",
        "silver",
        "gold",
        "shop-scoped",
        "material trigger",
        "A1",
    )
    for keyword in q4_keywords:
        if keyword not in db_text:
            errors.append(f"database/MODULE.md Q4 section missing keyword: {keyword!r}")

    if not ETL_MODULE_MD.is_file():
        errors.append(f"missing {ETL_MODULE_MD}")
    else:
        etl_text = ETL_MODULE_MD.read_text(encoding="utf-8")
        if "One-writer" not in etl_text and "one-writer" not in etl_text:
            errors.append("services/etl/MODULE.md missing one-writer cross-link")
        if "Shared Compute" not in etl_text:
            errors.append("services/etl/MODULE.md missing Shared Compute orchestrator note")

    return errors


def validate_medallion_one_writer() -> list[str]:
    return sorted(set(scan_medallion_write_violations() + validate_module_docs()))


def main() -> int:
    errors = validate_medallion_one_writer()
    if errors:
        print("medallion_one_writer: FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("medallion_one_writer: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
