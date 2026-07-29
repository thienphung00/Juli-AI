#!/usr/bin/env python3
"""Best-effort static scan for hardcoded application Redis key prefixes (#560 / MMU-12)."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "docs" / "architecture" / "ownership-registry.yml"
DEFAULT_SCAN_ROOT = REPO_ROOT / "backend" / "src" / "juli_backend"

JULI_MODULE_PREFIX_RE = re.compile(r"^juli:[a-z][a-z0-9_-]*:")
PREFIX_LITERAL_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z0-9_*]+)+:?$")
KEY_BUILDER_NAME_RE = re.compile(r"(?:^|_)(?:key|prefix)(?:_|$)", re.IGNORECASE)
KEY_LIKE_ASSIGNMENT_RE = re.compile(r"(?:KEY|PREFIX)", re.IGNORECASE)

# Postgres/event id prefixes — not Redis application keys.
EXCLUDED_PREFIXES = frozenset(
    {
        "enc:v1:",
        "wh:",
        "sync:",
        "hash:",
    }
)


@dataclass(frozen=True)
class PrefixHit:
    file: str
    line: int
    prefix: str
    pattern: str


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load ownership-registry.yml; install PyYAML or use backend dev env"
        ) from exc
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("ownership registry root must be a mapping")
    return loaded


def load_ownership_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or REGISTRY_PATH
    return _load_yaml(registry_path.read_text(encoding="utf-8"))


def load_redis_key_policy(registry_path: Path | None = None) -> dict[str, Any]:
    registry = load_ownership_registry(registry_path)
    policy = (registry.get("metadata") or {}).get("redisKeyPolicy") or {}
    if not isinstance(policy, dict):
        raise ValueError("metadata.redisKeyPolicy must be a mapping")
    return policy


def registered_patterns(registry: dict[str, Any]) -> list[str]:
    return [
        str(entry.get("pattern"))
        for entry in registry.get("redisNamespaces") or []
        if entry.get("pattern")
    ]


def legacy_allowlist(registry: dict[str, Any]) -> list[str]:
    policy = (registry.get("metadata") or {}).get("redisKeyPolicy") or {}
    raw = policy.get("legacyAllowlist") or []
    return [str(item) for item in raw]


def prefix_to_pattern(prefix: str) -> str:
    """Normalize a literal or f-string static prefix to a registry-style glob."""
    normalized = prefix.rstrip(":")
    if "{" in normalized:
        normalized = normalized.split("{", 1)[0].rstrip(":")
    segments = [segment for segment in normalized.split(":") if segment]
    if not segments:
        return normalized
    return ":".join(segments) + ":*"


def _literal_prefix(value: str) -> str | None:
    if not value or value in EXCLUDED_PREFIXES:
        return None
    if JULI_MODULE_PREFIX_RE.match(value):
        return value.split("{", 1)[0] if "{" in value else value
    if PREFIX_LITERAL_RE.match(value.rstrip("*")):
        return value if value.endswith(":") else f"{value}:"
    return None


def _fstring_static_prefix(node: ast.JoinedStr) -> str | None:
    if not node.values:
        return None
    first = node.values[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    text = first.value
    if not text:
        return None
    return _literal_prefix(text if text.endswith(":") else f"{text.rstrip(':')}:")


def _is_key_builder_context(node: ast.AST, tree: ast.AST) -> bool:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return bool(KEY_BUILDER_NAME_RE.search(node.name))
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and KEY_LIKE_ASSIGNMENT_RE.search(target.id):
                return True
    return False


def _walk_context(parents: list[ast.AST], tree: ast.AST) -> bool:
    for parent in reversed(parents):
        if _is_key_builder_context(parent, tree):
            return True
    return False


def _extract_from_node(
    node: ast.AST,
    *,
    rel_file: str,
    parents: list[ast.AST],
    tree: ast.AST,
) -> list[PrefixHit]:
    hits: list[PrefixHit] = []

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if _walk_context(parents, tree):
            prefix = _literal_prefix(node.value if node.value.endswith(":") else f"{node.value}:")
            if prefix:
                hits.append(
                    PrefixHit(
                        file=rel_file,
                        line=getattr(node, "lineno", 0),
                        prefix=prefix,
                        pattern=prefix_to_pattern(prefix),
                    )
                )

    if isinstance(node, ast.JoinedStr):
        in_key_builder = _walk_context(parents, tree)
        if in_key_builder:
            prefix = _fstring_static_prefix(node)
            if prefix:
                hits.append(
                    PrefixHit(
                        file=rel_file,
                        line=getattr(node, "lineno", 0),
                        prefix=prefix,
                        pattern=prefix_to_pattern(prefix),
                    )
                )

    return hits


def _iter_with_parents(tree: ast.AST) -> list[tuple[ast.AST, list[ast.AST]]]:
    stack: list[tuple[ast.AST, list[ast.AST]]] = [(tree, [])]
    ordered: list[tuple[ast.AST, list[ast.AST]]] = []
    while stack:
        node, parents = stack.pop()
        ordered.append((node, parents))
        child_parents = [*parents, node]
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_parents))
    return ordered


def extract_prefix_hits(py_file: Path, repo_root: Path) -> list[PrefixHit]:
    rel_file = py_file.resolve().relative_to(repo_root.resolve()).as_posix()
    try:
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
    except SyntaxError:
        return []

    hits: list[PrefixHit] = []
    for node, parents in _iter_with_parents(tree):
        hits.extend(
            _extract_from_node(node, rel_file=rel_file, parents=parents, tree=tree)
        )

    # Uppercase module constants like CACHE_KEY_PREFIX = "analytics:kpi_envelope:"
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if not KEY_LIKE_ASSIGNMENT_RE.search(target.id):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                prefix = _literal_prefix(
                    value.value if value.value.endswith(":") else f"{value.value}:"
                )
                if prefix:
                    hits.append(
                        PrefixHit(
                            file=rel_file,
                            line=node.lineno,
                            prefix=prefix,
                            pattern=prefix_to_pattern(prefix),
                            )
                    )
    return hits


def iter_python_files(scan_root: Path) -> list[Path]:
    if not scan_root.exists():
        return []
    return sorted(path for path in scan_root.rglob("*.py") if path.is_file())


def prefix_is_allowed(pattern: str, registry: dict[str, Any]) -> bool:
    if JULI_MODULE_PREFIX_RE.match(pattern) or JULI_MODULE_PREFIX_RE.match(
        pattern.rstrip("*")
    ):
        return True
    for allowed in (*registered_patterns(registry), *legacy_allowlist(registry)):
        if fnmatch.fnmatch(pattern, allowed):
            return True
        if fnmatch.fnmatch(pattern.rstrip("*"), allowed):
            return True
    return False


def collect_unknown_prefixes(
    scan_root: Path,
    registry_path: Path | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[PrefixHit]:
    registry = load_ownership_registry(registry_path)
    unknown: list[PrefixHit] = []
    seen: set[tuple[str, str]] = set()

    for py_file in iter_python_files(scan_root):
        for hit in extract_prefix_hits(py_file, repo_root):
            key = (hit.file, hit.pattern)
            if key in seen:
                continue
            seen.add(key)
            if not prefix_is_allowed(hit.pattern, registry):
                unknown.append(hit)
    return unknown


def validate_scan(
    scan_root: Path,
    registry_path: Path | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[bool, list[str]]:
    unknown = collect_unknown_prefixes(
        scan_root, registry_path, repo_root=repo_root
    )
    if not unknown:
        return True, []
    errors = [
        f"{hit.file}:{hit.line}: unregistered Redis prefix {hit.prefix!r} "
        f"(pattern {hit.pattern!r}; register in ownership-registry.yml or use juli:<module>:)"
        for hit in unknown
    ]
    return False, errors


def run_check(
    *,
    scan_root: Path | None = None,
    registry_path: Path | None = None,
    strict: bool = False,
    repo_root: Path = REPO_ROOT,
) -> tuple[bool, str, list[str]]:
    root = (scan_root or DEFAULT_SCAN_ROOT).resolve()
    reg_path = registry_path or REGISTRY_PATH
    passed, errors = validate_scan(root, reg_path, repo_root=repo_root)
    if passed:
        return True, "Redis key prefixes respected", []
    detail = f"{len(errors)} unregistered prefix(es); first: {errors[0]}"
    if strict:
        return False, detail, errors
    return True, f"WARN — {detail}", errors


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import print_check_result  # noqa: E402

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scan-root",
        type=Path,
        default=DEFAULT_SCAN_ROOT,
        help="Directory root to scan (defaults to backend/src/juli_backend)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="Path to ownership-registry.yml",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when unregistered prefixes are found",
    )
    args = parser.parse_args()

    passed, detail, errors = run_check(
        scan_root=args.scan_root,
        registry_path=args.registry,
        strict=args.strict,
    )
    if errors and not args.strict:
        for err in errors[:10]:
            print(f"redis_key_prefixes: WARN — {err}", file=sys.stderr)
        if len(errors) > 10:
            print(
                f"redis_key_prefixes: WARN — … and {len(errors) - 10} more",
                file=sys.stderr,
            )
    return print_check_result("redis_key_prefixes", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
