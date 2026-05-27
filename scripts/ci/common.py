"""Shared utilities for CI generators and validate gates (stdlib only)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_MAP = REPO_ROOT / "docs" / "architecture" / "map.md"
HANDOFFS_DIR = REPO_ROOT / "docs" / "handoffs"
DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"
REVIEWS_DIR = REPO_ROOT / "artifacts" / "reviews"
VALIDATION_DIR = REPO_ROOT / "artifacts" / "validation"
RELEASES_DIR = REPO_ROOT / "artifacts" / "releases"
DONE_MD = REPO_ROOT / "done.md"

ISSUE_BRANCH_RE = re.compile(r"(?:feat|fix)/issue-(\d+)", re.IGNORECASE)
MODULE_ROW_RE = re.compile(
    r"\[`([^`]+)`]([^)]*MODULE\.md)?\s*\|\s*(\d+)\s*\|",
)
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
PUBLIC_SECTION_RE = re.compile(
    r"##\s+Public\s+Interface[s]?\s*\n(.*?)(?=\n##\s+|\Z)",
    re.DOTALL | re.IGNORECASE,
)
HANDOFF_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-\d{2}\.md$", re.IGNORECASE)
ADR_FILE_RE = re.compile(r"^(\d{3})-([a-z0-9-]+)\.md$")
REQUIRED_ADR_SECTIONS = ("## Context", "## Decision", "## Rationale", "## Consequences")


@dataclass(frozen=True)
class ModuleInfo:
    path: str  # e.g. src/auth
    tier: int
    name: str  # short label from map, e.g. auth


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--issue", type=int, help="GitHub issue number")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args()


def resolve_issue_number(explicit: int | None = None) -> int | None:
    if explicit is not None:
        return explicit
    env_issue = os.environ.get("ISSUE_NUMBER") or os.environ.get("GITHUB_ISSUE_NUMBER")
    if env_issue and env_issue.isdigit():
        return int(env_issue)
    branch = os.environ.get("GITHUB_HEAD_REF") or git_current_branch()
    if branch:
        match = ISSUE_BRANCH_RE.search(branch)
        if match:
            return int(match.group(1))
    return None


def git_current_branch() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_changed_files(base_ref: str | None = None) -> list[str]:
    """Return paths changed on this branch vs merge base (or working tree)."""
    try:
        if base_ref:
            cmd = ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
        else:
            base = os.environ.get("GITHUB_BASE_REF")
            if base:
                subprocess.run(
                    ["git", "fetch", "origin", base, "--depth=1"],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                )
                cmd = ["git", "diff", "--name-only", f"origin/{base}...HEAD"]
            else:
                cmd = ["git", "diff", "--name-only", "HEAD"]
        out = subprocess.check_output(cmd, cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def parse_architecture_map(path: Path | None = None) -> dict[str, ModuleInfo]:
    path = path or ARCHITECTURE_MAP
    modules: dict[str, ModuleInfo] = {}
    if not path.exists():
        return modules
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = MODULE_ROW_RE.search(line)
        if not match:
            continue
        module_path, _, tier_str = match.groups()
        module_path = module_path.strip().rstrip("/")
        if not module_path.startswith("src/"):
            continue
        short = module_path.removeprefix("src/").split("/")[0]
        if "/" in module_path.removeprefix("src/"):
            short = module_path.removeprefix("src/")
        modules[module_path] = ModuleInfo(path=module_path, tier=int(tier_str), name=short)
    return modules


def module_for_file(file_path: str, modules: dict[str, ModuleInfo]) -> str | None:
    normalized = file_path.replace("\\", "/")
    if not normalized.startswith("src/"):
        return None
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        if normalized == module_path or normalized.startswith(module_path + "/"):
            return module_path
    return None


def path_to_package(module_path: str) -> str:
    return module_path.replace("/", ".")


def parse_module_md_public_symbols(module_md: Path) -> set[str]:
    if not module_md.exists():
        return set()
    text = module_md.read_text(encoding="utf-8")
    section = PUBLIC_SECTION_RE.search(text)
    body = section.group(1) if section else text
    symbols: set[str] = set()
    for match in BACKTICK_SYMBOL_RE.finditer(body):
        symbols.add(match.group(1))
    return symbols


def ast_public_symbols(py_file: Path) -> set[str]:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return set()
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if isinstance(node.value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Call)):
                        symbols.add(target.id)
    return symbols


def module_public_symbols_from_code(module_path: str) -> set[str]:
    root = REPO_ROOT / module_path
    if not root.exists():
        return set()
    symbols: set[str] = set()
    for py_file in root.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        symbols |= ast_public_symbols(py_file)
    return symbols


def normalize_label(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_")


def criterion_matches_test(criterion: str, test_name: str) -> bool:
    c = normalize_label(criterion)
    t = normalize_label(test_name)
    if not c or not t:
        return False
    return c in t or t in c or any(
        token in t for token in c.split("_") if len(token) > 3
    )


def parse_pytest_node(node_id: str) -> tuple[Path, str]:
    if "::" not in node_id:
        path = REPO_ROOT / node_id
        return path, ""
    file_part, test_name = node_id.rsplit("::", 1)
    return REPO_ROOT / file_part, test_name


def pytest_node_exists(node_id: str) -> bool:
    path, test_name = parse_pytest_node(node_id)
    if not path.exists():
        return False
    if not test_name:
        return True
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name:
            return True
    return False


def review_artifact_path(issue: int) -> Path:
    return REVIEWS_DIR / f"review-issue-{issue}.json"


def validation_artifact_path(issue: int) -> Path:
    return VALIDATION_DIR / f"validation-issue-{issue}.json"


def load_review_artifact(issue: int) -> dict[str, Any] | None:
    path = review_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == node:
                    break
            sccs.append(component)

    for vertex in graph:
        if vertex not in indices:
            strongconnect(vertex)
    return sccs


def collect_import_graph(modules: dict[str, ModuleInfo]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {m: set() for m in modules}
    for py_file in (REPO_ROOT / "src").rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        owner = module_for_file(rel, modules)
        if not owner:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = resolve_import_to_module(node.module, modules)
                if imported and imported != owner:
                    graph[owner].add(imported)
    return graph


def resolve_import_to_module(module_name: str, modules: dict[str, ModuleInfo]) -> str | None:
    dotted = module_name.replace(".", "/")
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        pkg = path_to_package(module_path)
        if module_name == pkg or module_name.startswith(pkg + "."):
            return module_path
        if dotted.startswith(module_path):
            return module_path
    return None


def handoff_files_on_branch(changed: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for rel in changed:
        if not rel.startswith("docs/handoffs/"):
            continue
        name = Path(rel).name
        if name in {"_bootstrap.md", "parallel-status.md"}:
            continue
        if HANDOFF_FILE_RE.match(name):
            found.append(REPO_ROOT / rel)
    return found


def architectural_change_detected(review: dict[str, Any], changed: Iterable[str]) -> bool:
    for finding in review.get("criticalFindings", []):
        if finding.get("type") == "interface_change":
            return True
    for change in review.get("interfaceChanges", []):
        if change.get("breaking"):
            return True
    if any("docs/architecture/map.md" in c for c in changed):
        return True
    return False


def new_adr_files(changed: Iterable[str]) -> list[str]:
    adrs: list[str] = []
    for rel in changed:
        name = Path(rel).name
        if rel.startswith("docs/decisions/") and ADR_FILE_RE.match(name):
            adrs.append(rel)
    return adrs


def print_check_result(name: str, passed: bool, detail: str = "") -> int:
    status = "PASS" if passed else "FAIL"
    line = f"{name}: {status}"
    if detail:
        line += f" — {detail}"
    print(line)
    return 0 if passed else 1
