"""Shared utilities for CI generators and validate gates (stdlib only)."""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_RUNTIME_ROOT = REPO_ROOT / "agent-runtime"
ARCHITECTURE_MAP = REPO_ROOT / "docs" / "architecture" / "map.md"
HANDOFFS_DIR = REPO_ROOT / "docs" / "handoffs"
DECISIONS_DIR = REPO_ROOT / "docs" / "adr"
REVIEWS_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "reviews"
INTENT_REVIEWS_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "intent-reviews"
VALIDATION_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "validation"
IMPLEMENTATIONS_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "implementations"
OPTIMIZATION_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "optimization"
RELEASES_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "releases"
STATUS_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "status"
RUNTIME_SCHEMA_VERSION = "1.0.0"
DONE_MD = REPO_ROOT / "done.md"

ISSUE_BRANCH_RE = re.compile(r"(?:feat|fix)/issue-(\d+)", re.IGNORECASE)
# Every row in docs/architecture/map.md writes its module path as a markdown
# link — [`path`](../../path/MODULE.md) | 1 | … — so the link target has to be
# consumed before the tier cell. The previous pattern stopped at the closing
# backtick-bracket and then demanded `|` where the link's `(` actually sits, so
# it matched no row at all and parse_architecture_map returned {} (#1859). The
# regex is widened rather than map.md normalised: the map is the human-authored
# as-built registry and its links are load-bearing for readers, so the parser
# is what should learn the format the tree already uses.
MODULE_ROW_RE = re.compile(
    r"\[`([^`]+)`\](?:\([^)]*\))?\s*\|\s*(\d+)\s*\|",
)
# A documented entry is either a bare identifier — `name` — or a call signature
# — `name(args) -> T`. Dotted spans (`pkg.module`) stay unmatched on purpose:
# they name a location, not a public symbol of this module.
BACKTICK_SYMBOL_RE = re.compile(
    r"`([A-Za-z_][A-Za-z0-9_]*)(?:\([^`]*\))?(?:\s*->[^`]*)?`",
)
# Heading-level aware: a `### Public interface` sub-section ends at the next
# heading of the same or a shallower level, not at the next `## `. The previous
# whole-section pattern was also applied with search(), so only the FIRST
# Public Interface section in a MODULE.md was ever read (#1859).
PUBLIC_SECTION_RE = re.compile(
    r"^(#{2,6})\s+Public\s+Interface[s]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
# `None`, `True` and `False` appear backticked in Public Interface prose
# ("a `None` stop reason stays `None`"). They are language keywords and can
# never be a module's public symbol, so they are never documented entries.
NEVER_A_SYMBOL = frozenset(keyword.kwlist) | {"self", "cls"}
# Module-level bindings that exist in every module by convention and are not
# part of anything's public interface. Documenting them in a MODULE.md would
# add noise, not information, so the gate does not ask for it.
NEVER_AN_EXPORT = frozenset({"logger", "log"})
HANDOFF_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-\d{2}\.md$", re.IGNORECASE)
ADR_FILE_RE = re.compile(r"^(\d{3})-([a-z0-9-]+)\.md$")
REQUIRED_ADR_SECTIONS = ("## Context", "## Decision", "## Rationale", "## Consequences")
BACKEND_SRC_PREFIX = "backend/src/juli_backend/"
BACKEND_MODULE_PREFIXES = (BACKEND_SRC_PREFIX, "backend/", "src/")


def normalize_backend_module_path(file_path: str) -> str:
    """Map on-disk src layout paths to logical ``backend/…`` module paths."""
    normalized = file_path.replace("\\", "/")
    if normalized.startswith(BACKEND_SRC_PREFIX):
        return "backend/" + normalized[len(BACKEND_SRC_PREFIX) :]
    return normalized


def backend_module_root(module_path: str) -> Path:
    """Resolve a logical ``backend/…`` module path to its directory on disk."""
    normalized = module_path.replace("\\", "/")
    if normalized.startswith("backend/"):
        return REPO_ROOT / BACKEND_SRC_PREFIX.rstrip("/") / normalized.removeprefix("backend/")
    return REPO_ROOT / normalized


def _is_backend_module_path(module_path: str) -> bool:
    return any(module_path.startswith(prefix) for prefix in BACKEND_MODULE_PREFIXES)


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


class SchemaValidationError(Exception):
    """Raised when artifact payload fails schema validation."""

    def __init__(self, artifact_type: str, errors: list[str]) -> None:
        self.artifact_type = artifact_type
        self.errors = errors
        msg = f"schema validation failed for {artifact_type} artifact:\n"
        msg += "\n".join(f"  {error}" for error in errors)
        super().__init__(msg)


def load_artifact_schema(artifact_type: str) -> dict[str, Any]:
    """Load the JSON schema for a given artifact type."""
    schema_name_map = {
        "implementation": "implementation-artifact.schema.json",
        "review": "review-artifact.schema.json",
        "intent_review": "intent-review-artifact.schema.json",
        "validation": "validation-artifact.schema.json",
    }
    schema_name = schema_name_map.get(artifact_type)
    if not schema_name:
        raise ValueError(f"unknown artifact type: {artifact_type}")
    schema_path = AGENT_RUNTIME_ROOT / "docs" / "schemas" / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"schema not found: {schema_path}")
    return load_json(schema_path)


def check_token_usage_semantic(token_usage: Any) -> list[str]:
    """Semantic validation of tokenUsage to mirror check_implementation_artifact.

    The schema can only check structure. This checks the semantic constraint:
    - If measured (no 'available' key), total must be > 0 (not 0, not negative)
    - If unmeasured (available: false), total must not be present

    Returns list of error messages (empty when valid).
    """
    errors: list[str] = []
    if not isinstance(token_usage, dict):
        return errors  # Schema handles this

    if "available" in token_usage:
        if token_usage.get("available") is False:
            if "value" in token_usage:
                errors.append(
                    "tokenUsage: carries 'value' alongside available:false — "
                    "the unavailable shape omits the key so a consumer that skips "
                    "the check raises rather than reading a plausible number"
                )
            # Schema handles other validation of unavailable branch
        return errors

    # Measured branch: total must be > 0
    total = token_usage.get("total")
    if isinstance(total, int) and not isinstance(total, bool):
        if total <= 0:
            errors.append(
                "tokenUsage.total is 0, which reads as a measurement and is not one — "
                "record {available: false, reason: '...'} (no 'value' key) when the run "
                "was not measured, or {input, output, total} when it was"
            )
    return errors


def write_json_with_schema_validation(
    path: Path, payload: dict[str, Any], artifact_type: str
) -> None:
    """Write JSON with schema validation. Raises SchemaValidationError if invalid."""
    from json_schema_validate import validate_json_schema

    schema = load_artifact_schema(artifact_type)
    errors = validate_json_schema(payload, schema)

    # Add semantic validation for implementation artifacts
    if not errors and artifact_type == "implementation":
        token_usage = payload.get("tokenUsage")
        if token_usage is not None:
            semantic_errors = check_token_usage_semantic(token_usage)
            if semantic_errors:
                errors.extend([f"tokenUsage: {err}" for err in semantic_errors])

    if errors:
        raise SchemaValidationError(artifact_type, errors)
    write_json(path, payload)


def deep_merge_under(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base; overlay values win at every level."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_under(result[key], value)
        else:
            result[key] = value
    return result


def review_artifact_template(issue: int) -> dict[str, Any]:
    """ADR-003 review artifact skeleton with empty placeholders."""
    return {
        "id": f"review-issue-{issue}",
        "issue": issue,
        "timestamp": utc_now_iso(),
        "reviewedBy": "review skill",
        "status": "PASS",
        "summary": "",
        "criticalFindings": [],
        "modulesTouched": [],
        "interfaceChanges": [],
        "moduleDrift": False,
        "driftDetails": [],
        "testCoverage": {
            "acceptance": {
                "total": 0,
                "mapped": 0,
                "unmapped": [],
                "mappings": [],
            },
            "unit": {"passed": 0, "failed": 0},
        },
        "recommendations": [],
        "approvalReady": True,
        "reviewerSignoff": None,
        "ownerSignoff": None,
        "mlGates": None,
        "priorReviewBlockers": [],
    }


def build_review_artifact(
    issue: int,
    *,
    existing: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fresh: bool = False,
    update_timestamp: bool = True,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble a review artifact without clobbering existing review content."""
    artifact = review_artifact_template(issue)
    if existing and not fresh:
        artifact = deep_merge_under(artifact, existing)
    if overrides:
        artifact = deep_merge_under(artifact, overrides)
    artifact["id"] = f"review-issue-{issue}"
    artifact["issue"] = issue
    if update_timestamp:
        artifact["timestamp"] = utc_now_iso()
    elif existing and existing.get("timestamp"):
        artifact["timestamp"] = existing["timestamp"]
    return finalize_review_artifact(artifact, phase_run_id=phase_run_id)


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
            encoding="utf-8",
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


class ChangedFilesUnresolved(RuntimeError):
    """The changed-file set could not be determined (#1571).

    Distinct from an empty diff *by construction*: ``[]`` means "nothing
    changed", this means "the question could not be answered". The old code
    returned ``[]`` for both, and every diff-driven gate read that as
    "no relevant change -> nothing to check -> PASS".

    Callers must degrade to a recorded failure carrying ``reason`` -- never to a
    silent pass, and never to a guessed diff. This mirrors how the neighbouring
    bootstrap-pin gate degrades (``harness_bootstrap_pin.py``, #1540): two gates
    answering the same question degrade the same way.
    """

    def __init__(self, spec: str, reason: str) -> None:
        super().__init__(f"changed-file set unresolved for {spec}: {reason}")
        self.spec = spec
        self.reason = reason


def _git_capture(args: list[str], repo_root: Path) -> tuple[bool, str, str]:
    """Run a git subcommand, returning ``(ok, stdout, stderr)`` without raising."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:  # includes FileNotFoundError when git is absent
        return False, "", f"git CLI unavailable: {exc}"
    if proc.returncode != 0:
        return False, proc.stdout or "", (proc.stderr or "").strip()
    return True, proc.stdout or "", ""


def _git_diff_names(spec: str, repo_root: Path) -> list[str]:
    ok, out, err = _git_capture(["diff", "--name-only", spec], repo_root)
    if not ok:
        raise ChangedFilesUnresolved(spec, err or "git diff failed")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _merge_base_exists(left: str, right: str, repo_root: Path) -> bool:
    ok, _, _ = _git_capture(["merge-base", left, right], repo_root)
    return ok


def _repo_is_shallow(repo_root: Path) -> bool:
    ok, out, _ = _git_capture(["rev-parse", "--is-shallow-repository"], repo_root)
    return ok and out.strip() == "true"


def _deepen_base(base: str, repo_root: Path) -> tuple[bool, str]:
    """Fetch ``base`` with its history intact.

    Never ``--depth=1``: truncating the base ref is the #1571 defect itself. A
    depth-1 graft leaves ``origin/<base>`` resolvable *by name* while destroying
    the history behind it, so the three-dot diff that follows aborts with "no
    merge base". Deepen on demand instead, and report unresolvability honestly
    when even that fails.
    """
    refspec = f"+refs/heads/{base}:refs/remotes/origin/{base}"
    if _repo_is_shallow(repo_root):
        ok, _, err = _git_capture(
            ["fetch", "--unshallow", "--no-tags", "origin", refspec], repo_root
        )
        if ok:
            return True, ""
    else:
        err = ""
    ok, _, plain_err = _git_capture(["fetch", "--no-tags", "origin", refspec], repo_root)
    return ok, plain_err or err


def _changed_vs_base(spec: str, repo_root: Path, fetch_ref: str | None) -> list[str]:
    if not _merge_base_exists(spec, "HEAD", repo_root):
        # Only touch the network when the question cannot already be answered.
        # A base that already resolves is queried without mutating the
        # repository at all -- a read-only query stays read-only.
        if fetch_ref is None:
            raise ChangedFilesUnresolved(spec, "shares no merge base with HEAD")
        ok, err = _deepen_base(fetch_ref, repo_root)
        if not _merge_base_exists(spec, "HEAD", repo_root):
            if not ok:
                raise ChangedFilesUnresolved(spec, err or "git fetch failed")
            raise ChangedFilesUnresolved(spec, "fetched, but shares no merge base with HEAD")
    return _git_diff_names(f"{spec}...HEAD", repo_root)


def git_changed_files(base_ref: str | None = None, repo_root: Path | None = None) -> list[str]:
    """Return paths changed on this branch vs merge base (or working tree).

    Raises :class:`ChangedFilesUnresolved` when the answer cannot be determined.
    An empty list is reserved for the genuine answer "nothing changed".
    """
    root = repo_root or REPO_ROOT
    if base_ref:
        return _changed_vs_base(base_ref, root, fetch_ref=None)
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        return _changed_vs_base(f"origin/{base}", root, fetch_ref=base)
    return _git_diff_names("HEAD", root)


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
        module_path, tier_str = match.groups()
        module_path = module_path.strip().rstrip("/")
        if not _is_backend_module_path(module_path):
            continue
        # map.md writes both forms — backend/src/juli_backend/services/x and
        # backend/ai/x. Key on the logical backend/… form, which is what
        # module_for_file, resolve_import_to_module and backend_module_root all
        # already speak; keying on the raw form left module_for_file resolving
        # nothing even when the row parsed (#1859).
        module_path = normalize_backend_module_path(module_path)
        short = module_path.removeprefix("backend/").removeprefix("src/").split("/")[0]
        rel = module_path.removeprefix("backend/").removeprefix("src/")
        if "/" in rel:
            short = rel
        modules[module_path] = ModuleInfo(path=module_path, tier=int(tier_str), name=short)
    return modules


def module_for_file(file_path: str, modules: dict[str, ModuleInfo]) -> str | None:
    normalized = normalize_backend_module_path(file_path.replace("\\", "/"))
    if not _is_backend_module_path(normalized):
        return None
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        if normalized == module_path or normalized.startswith(module_path + "/"):
            return module_path
    return None


def path_to_package(module_path: str) -> str:
    return module_path.replace("/", ".")


def strip_markdown_parentheticals(text: str) -> str:
    """Drop ``(…)`` groups that sit outside backticks.

    A Public Interface bullet names its symbol and then, in parentheses, the
    vocabulary that symbol ranges over — ``\u0060LinkReason\u0060 (\u0060pending\u0060 |
    \u0060unavailable\u0060 | \u0060missing\u0060)``. Those parenthesised words are prose, not
    documented symbols, and reading them as symbols manufactured three orphans
    in services/operations alone (#1859). Parentheses *inside* a backtick span
    are part of a call signature and are left untouched.
    """
    out: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char == "`":
            end = text.find("`", i + 1)
            if end == -1:
                out.append(text[i:])
                break
            out.append(text[i : end + 1])
            i = end + 1
            continue
        if char == "(":
            close = _matching_paren(text, i)
            if close is None:
                out.append(char)
                i += 1
                continue
            i = close + 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _matching_paren(text: str, start: int) -> int | None:
    """Index of the ``)`` closing ``text[start]``, ignoring backtick spans."""
    depth = 0
    i = start
    length = len(text)
    while i < length:
        char = text[i]
        if char == "`":
            end = text.find("`", i + 1)
            if end == -1:
                return None
            i = end + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def public_interface_sections(text: str) -> list[str]:
    """Bodies of EVERY Public Interface section, `##` or `###`, in order.

    A MODULE.md acquires further sections as lanes land (services/operations
    carries three today). Reading only the first — the previous behaviour —
    made every symbol after it look undocumented (#1859).
    """
    lines = text.splitlines()
    bodies: list[str] = []
    current: list[str] | None = None
    depth = 0
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading and current is not None and len(heading.group(1)) <= depth:
            bodies.append("\n".join(current))
            current = None
        match = PUBLIC_SECTION_RE.match(line)
        if match:
            depth = len(match.group(1))
            current = []
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        bodies.append("\n".join(current))
    return bodies


def parse_module_md_public_symbols(module_md: Path) -> set[str]:
    if not module_md.exists():
        return set()
    text = module_md.read_text(encoding="utf-8")
    bodies = public_interface_sections(text)
    if not bodies:
        bodies = [text]
    symbols: set[str] = set()
    for body in bodies:
        for declaration in _declaration_spans(body):
            for match in BACKTICK_SYMBOL_RE.finditer(strip_markdown_parentheticals(declaration)):
                name = match.group(1)
                if name in NEVER_A_SYMBOL:
                    continue
                symbols.add(name)
    return symbols


_BULLET_RE = re.compile(r"^\s*[-*]\s")


def _declaration_spans(body: str) -> list[str]:
    """The parts of a Public Interface section that DECLARE a symbol.

    These sections are written as a bullet whose leading backticked span
    names the export and whose trailing clause explains it, and that
    explanation after the em dash is prose: it names database tables, result
    attributes and sibling modules that are not this module's exports. Scanning
    the whole bullet made every such mention a "documented symbol", so the gate
    reported table names like `workflow_outcome_metrics` and attribute names
    like `ratio` as documented-but-nonexistent (#1859). Only the span before
    the first em dash declares.
    """
    spans: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if _BULLET_RE.match(line):
            if current is not None:
                spans.append("\n".join(current))
            current = [line]
        elif current is not None and line.strip():
            current.append(line)
        else:
            if current is not None:
                spans.append("\n".join(current))
                current = None
            # A non-bullet line (a table row, a prose paragraph) carries no
            # explanation dash to split on, so it is scanned whole as before.
            spans.append(line)
    if current is not None:
        spans.append("\n".join(current))
    return [span.split("\u2014", 1)[0] for span in spans]


def ast_public_symbols(py_file: Path) -> set[str]:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return set()
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            # Any module-level binding, whatever it is bound to. The earlier
            # rule counted a name only when the value was a call or a def,
            # so `CARDS_SURFACED = "cards surfaced"` was invisible and the
            # gate reported it as documented-but-nonexistent -- 10 of the 13
            # "orphans" it flagged for services/operations were real, exported
            # constants (#1859).
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            # `APPROVED_STATUSES: frozenset[str] = frozenset({...})` is an
            # AnnAssign, not an Assign; annotating a constant used to delete
            # it from the module's public interface as far as this gate knew.
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                symbols.add(node.target.id)
    return symbols - NEVER_AN_EXPORT


def module_public_symbols_from_code(module_path: str) -> set[str]:
    root = backend_module_root(module_path)
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
    if c in t or t.endswith(c):
        return True
    tokens = [token for token in c.split("_") if len(token) > 3]
    if not tokens:
        return False
    # Require at least two token hits — blocks cosmetic single-token overlaps
    # (e.g. criterion "No TikTok API calls" vs test_has_no_tiktok).
    return sum(1 for token in tokens if token in t) >= 2


def parse_pytest_node(node_id: str) -> tuple[Path, str]:
    """Split a pytest node id into its file path and test name.

    The file path ends at the FIRST "::" — everything after it is class and/or test
    name. Splitting from the right instead folds a class segment into the path
    (``file.py::TestClass``), which never exists on disk, so class-based node ids
    were reported as missing tests (#735). Any parametrisation suffix is dropped so
    the name matches the function definition in the source.
    """
    if "::" not in node_id:
        return REPO_ROOT / node_id, ""
    file_part = node_id.split("::", 1)[0]
    test_name = node_id.rsplit("::", 1)[-1]
    test_name = test_name.split("[", 1)[0]
    return REPO_ROOT / file_part, test_name


JEST_TEST_CALL_RE = re.compile(
    r'\b(?:it|test)\s*\(\s*(["\'])(.+?)\1',
    re.DOTALL,
)


def jest_node_exists(node_id: str) -> bool:
    path, test_name = parse_pytest_node(node_id)
    if not path.exists() or path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        return False
    if not test_name:
        return True
    source = path.read_text(encoding="utf-8")
    return any(match.group(2) == test_name for match in JEST_TEST_CALL_RE.finditer(source))


def pytest_node_exists(node_id: str) -> bool:
    path, test_name = parse_pytest_node(node_id)
    if not path.exists():
        return False
    if path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return jest_node_exists(node_id)
    if not test_name:
        return True
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return False

    def _matches(node: ast.AST) -> bool:
        return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name

    for node in tree.body:
        if _matches(node):
            return True
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if _matches(item):
                    return True
    return False


def review_artifact_path(issue: int) -> Path:
    return REVIEWS_DIR / f"review-issue-{issue}.json"


def intent_review_artifact_path(issue: int) -> Path:
    return INTENT_REVIEWS_DIR / f"intent-review-issue-{issue}.json"


def validation_artifact_path(issue: int) -> Path:
    return VALIDATION_DIR / f"validation-issue-{issue}.json"


def load_review_artifact(issue: int) -> dict[str, Any] | None:
    path = review_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


def load_intent_review_artifact(issue: int) -> dict[str, Any] | None:
    path = intent_review_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


def intent_review_artifact_template(issue: int) -> dict[str, Any]:
    """Intent-review artifact skeleton (Spec fidelity + smells + conventions)."""
    return {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "intent_review",
        "id": f"intent-review-issue-{issue}",
        "issue": issue,
        "timestamp": utc_now_iso(),
        "reviewedBy": "intent-review skill",
        "fixedPoint": "",
        "spec_fidelity": "pass",
        "specFidelityNotes": "",
        "smells": [],
        "convention_notes": [],
        "phaseRunId": None,
    }


def build_intent_review_artifact(
    issue: int,
    *,
    existing: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fresh: bool = False,
    update_timestamp: bool = True,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble an intent-review artifact."""
    artifact = intent_review_artifact_template(issue)
    if existing and not fresh:
        artifact = deep_merge_under(artifact, existing)
    if overrides:
        artifact = deep_merge_under(artifact, overrides)
    artifact["id"] = f"intent-review-issue-{issue}"
    artifact["issue"] = issue
    artifact["artifactType"] = "intent_review"
    if update_timestamp:
        artifact["timestamp"] = utc_now_iso()
    elif existing and existing.get("timestamp"):
        artifact["timestamp"] = existing["timestamp"]
    if artifact.get("spec_fidelity") not in ("pass", "fail"):
        artifact["spec_fidelity"] = "fail"
    artifact.setdefault("smells", [])
    artifact.setdefault("convention_notes", [])
    if phase_run_id:
        artifact["phaseRunId"] = phase_run_id
    elif not artifact.get("phaseRunId"):
        # #1881: same single-helper rule as the review artifact -- no
        # explicit override and nothing already recorded means derive fresh,
        # never leave the template's placeholder ``None`` (schema-invalid) on
        # disk.
        artifact["phaseRunId"] = derive_phase_run_id(issue)
    return artifact


def load_implementation_artifact(issue: int) -> dict[str, Any] | None:
    path = implementation_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


EXECUTOR_DOMAINS = frozenset(
    {"ui-ux", "backend", "data-platform", "machine-learning", "integrations"}
)


#: Why the template says "unavailable" rather than 0 (#1441, #1505). No
#: instrumented token reading is exposed to an executor, so the previous default
#: of ``{"input": 0, "output": 0, "total": 0}`` handed every unmeasured run a
#: number indistinguishable from a measurement — and, once #1441 taught the gate
#: to reject exactly that, made the generator's own default output fail its own
#: gate.
TOKEN_USAGE_UNAVAILABLE_REASON = (
    "no instrumented token reading is exposed to the runner; recorded unavailable "
    "rather than 0 so an unmeasured field cannot read as a measured zero"
)


def unavailable_measurement(field: str, *, reason: str | None = None) -> dict[str, Any]:
    """The unmeasured shape for a scalar measurement (#1732).

    Mirrors :func:`unavailable_token_usage`. A freshly templated artifact has
    measured nothing, so defaulting these to ``0`` made every template
    schema-invalid the moment #1732 gave them a two-shape contract -- and worse,
    a ``0`` that survived was indistinguishable from a real reading.

    ``reason`` overrides the generic "not instrumented" wording for callers
    (e.g. :func:`derive_phase_run_id`) whose unavailable case is not about
    instrumentation at all -- the shape is shared, the sentence should not be.
    """
    return {
        "available": False,
        "reason": reason or f"{field} was not instrumented for this run",
    }


def derive_phase_run_id(issue: int, *, repo_root: Path | None = None) -> str | dict[str, Any]:
    """The single source of ``phaseRunId`` for every artifact template (#1881).

    Before this, each generator invented its own convention (an issue-prefixed
    compact ISO stamp, a bare ``review-issue-<n>`` id, a plain ISO stamp) and
    none of the three ever matched, because the phases genuinely run in
    separate agent sessions with nothing shared between them. Picking *any*
    self-generated value — a timestamp, a random suffix — cannot fix that: the
    two sessions would still need to agree on which value to invent, and they
    have no channel to negotiate one.

    What both sessions *can* independently observe is the git state they are
    each checked out on: the issue number (from the branch or ``--issue``) and
    the HEAD commit under review. An Executor/Meta session writing the
    implementation artifact and a later Review session writing
    intent-review/review/validation read the same on-disk HEAD as long as no
    new commit has landed between them — which is exactly the case the gate
    should treat as one correlated run. A genuinely different HEAD (new
    commits landed, or a different checkout entirely) yields a different id by
    construction, so the gate still fails closed on a real mismatch (#1881 AC2)
    instead of being relaxed.

    Returns the plain ``"<issue>-<short-sha>"`` string, or the repo's
    ``unavailable`` shape (mirroring :func:`unavailable_measurement`) when the
    HEAD sha cannot be resolved at all — never an invented value that would
    silently disagree with the other phase's.
    """
    env = os.environ.get("PHASE_RUN_ID")
    if env:
        return env
    root = repo_root or REPO_ROOT
    ok, out, err = _git_capture(["rev-parse", "--short=12", "HEAD"], root)
    sha = out.strip() if ok else ""
    if not sha:
        return unavailable_measurement(
            "phaseRunId",
            reason=f"git HEAD sha could not be resolved for issue {issue}: {err or 'no output'}",
        )
    return f"{issue}-{sha}"


def unavailable_token_usage(
    reason: str = TOKEN_USAGE_UNAVAILABLE_REASON,
) -> dict[str, Any]:
    """The unmeasured ``tokenUsage`` shape, mirroring ``assemble_evidence.unavailable``.

    Deliberately carries no ``value`` key at all: a consumer that forgets to
    check ``available`` gets a ``KeyError`` rather than a plausible number.
    """
    return {"available": False, "reason": reason}


def _is_unavailable_token_usage(token_usage: Any) -> bool:
    return isinstance(token_usage, dict) and "available" in token_usage


def _merge_implementation_layer(artifact: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge one layer, but replace ``tokenUsage`` wholesale.

    ``tokenUsage`` is a tagged union: ``{input, output, total}`` or
    ``{available, reason}``. Deep-merging a caller's branch onto the template's
    other branch yields the union of both key sets, which matches neither and is
    rejected by the schema and by the gate alike (#1505).
    """
    merged = deep_merge_under(artifact, layer)
    if "tokenUsage" in layer:
        merged["tokenUsage"] = deepcopy(layer["tokenUsage"])
    return merged


def implementation_artifact_template(
    issue: int,
    executor_domain: str,
    *,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Executor Agent implementation artifact skeleton with empty placeholders."""
    if executor_domain not in EXECUTOR_DOMAINS:
        raise ValueError(f"invalid executorDomain: {executor_domain!r}")
    now = utc_now_iso()
    return {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "implementation",
        "issueId": issue,
        "executorDomain": executor_domain,
        "phaseRunId": phase_run_id or derive_phase_run_id(issue),
        "startedAt": now,
        "completedAt": now,
        "executionDurationMs": unavailable_measurement("executionDurationMs"),
        "tokenUsage": unavailable_token_usage(),
        "toolsUsed": [],
        "toolInvocationCount": unavailable_measurement("toolInvocationCount"),
        "contextFilesLoaded": [],
        "skillsLoaded": [],
        "rulesLoaded": [],
        "mcpsUsed": [],
        "filesModified": [],
        "testsAdded": [],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [],
        "implementationSummary": "",
        "assumptions": [],
        "risks": [],
    }


def build_implementation_artifact(
    issue: int,
    executor_domain: str,
    *,
    existing: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fresh: bool = False,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble an implementation artifact without clobbering existing session evidence."""
    artifact = implementation_artifact_template(
        issue,
        executor_domain,
        phase_run_id=phase_run_id,
    )
    for layer in (None if fresh else existing, overrides):
        if layer:
            artifact = _merge_implementation_layer(artifact, layer)
    artifact["issueId"] = issue
    artifact["executorDomain"] = executor_domain
    if phase_run_id:
        artifact["phaseRunId"] = phase_run_id
    elif existing and existing.get("phaseRunId"):
        artifact["phaseRunId"] = existing["phaseRunId"]
    artifact.setdefault("schemaVersion", RUNTIME_SCHEMA_VERSION)
    artifact.setdefault("artifactType", "implementation")
    token_usage = artifact.get("tokenUsage") or {}
    # Only the measured branch gets a derived total. Deriving one for the
    # unavailable branch would read ``total`` as ``None`` and write 0 back,
    # re-creating the sentinel inside a document matching neither oneOf branch.
    if isinstance(token_usage, dict) and not _is_unavailable_token_usage(token_usage):
        input_tokens = int(token_usage.get("input", 0))
        output_tokens = int(token_usage.get("output", 0))
        computed_total = input_tokens + output_tokens
        declared_total = token_usage.get("total")
        if declared_total is None or (computed_total > 0 and int(declared_total) < computed_total):
            token_usage["total"] = computed_total
        artifact["tokenUsage"] = token_usage
    return artifact


_LEGACY_WARNING_DOMAIN_TYPES = {
    "observability": "other",
    "reliability": "other",
    "maintainability": "maintainability",
    "security": "security",
    "architecture": "architecture",
    "performance": "other",
}


def legacy_warning_to_finding(warning: dict[str, Any]) -> dict[str, Any]:
    """Convert a legacy top-level ``warnings[]`` entry to ``criticalFindings`` shape."""
    severity = str(warning.get("severity", "WARNING")).upper()
    if severity not in {"CRITICAL", "WARNING", "INFO"}:
        severity = "WARNING"

    domain = str(warning.get("domain") or warning.get("category") or "").lower()
    finding_type = warning.get("type") or _LEGACY_WARNING_DOMAIN_TYPES.get(domain, "other")

    parts: list[str] = []
    if warning.get("location"):
        parts.append(str(warning["location"]))
    for key in ("message", "description"):
        if warning.get(key):
            parts.append(str(warning[key]))
    if warning.get("rationale"):
        parts.append(f"Rationale: {warning['rationale']}")

    finding: dict[str, Any] = {
        "type": finding_type,
        "severity": severity,
        "description": " — ".join(parts) if parts else "Legacy warning migrated from warnings[]",
    }
    if warning.get("module"):
        finding["module"] = warning["module"]
    if warning.get("actionRequired"):
        finding["actionRequired"] = True
    if warning.get("suggestion"):
        finding["suggestion"] = warning["suggestion"]
    return finding


# #1601: the review-artifact schema defines five finding arrays --
# ``criticalFindings``, ``findings``, ``securityFindings``, ``architectureFindings``,
# and ``maintainabilityFindings``. ``enrich_review_artifact`` derives the latter
# four from ``criticalFindings`` as identity-preserving subsets, so in the
# generated-via-the-pipeline case reading only ``criticalFindings`` changes
# nothing. But nothing enforces that derivation on every writer: a reviewer (or
# a hand-authored artifact) can write straight into ``findings`` -- the name
# that most invites it -- without ever touching ``criticalFindings``, and every
# finding-related gate reads only ``normalize_review_findings``'s output.
# Ordered so ``criticalFindings`` wins identity ties (it is the canonical
# store); the rest is deliberately every other schema-declared *Findings array,
# not a hand-picked subset -- `test_schema_finding_arrays_all_have_a_reader`
# fails if the schema grows a sixth one this tuple doesn't name.
FINDING_ARRAY_KEYS: tuple[str, ...] = (
    "criticalFindings",
    "findings",
    "securityFindings",
    "architectureFindings",
    "maintainabilityFindings",
)


def _finding_identity(finding: dict[str, Any]) -> Any:
    """Identity key for de-duplicating findings across arrays.

    ``id`` wins when present. Otherwise the key is the tuple
    ``(severity, type, description, module)`` -- not ``description`` alone.

    Two findings that merely share description text are not necessarily the
    same finding: different severity, type, or module means a reviewer found
    two distinct things that happen to describe the same symptom (e.g. a
    WARNING maintainability note in one module and a CRITICAL security finding
    in another, both worded "input validation gap"). Matching on description
    alone silently drops whichever one loses the set-membership race --
    including, in the reported case, the CRITICAL.

    The benign case -- ``enrich_review_artifact`` deriving ``findings``/
    ``securityFindings``/``architectureFindings``/``maintainabilityFindings``
    from ``criticalFindings`` as literal copies -- still dedups correctly
    under this key, because a derived copy shares every field (severity,
    type, description, module) with its source by construction, not just its
    description.
    """
    identity = finding.get("id")
    if identity:
        return ("id", identity)
    return (
        "fields",
        finding.get("severity"),
        finding.get("type"),
        finding.get("description"),
        finding.get("module"),
    )


def normalize_review_findings(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge every schema-defined finding array with legacy ``warnings[]`` into
    one canonical, de-duplicated list.

    De-duplication matters because the four non-``criticalFindings`` arrays are
    normally derived *copies* of ``criticalFindings`` entries (same ``id`` and
    fields) -- merging them naively would double-count every finding and
    inflate ``warningCount``/``criticalCount`` in gate output. A finding is
    kept once, at its first occurrence, in ``FINDING_ARRAY_KEYS`` order, keyed
    by ``_finding_identity`` -- which is deliberately *not* description alone,
    so two findings that only share description text (different severity,
    type, or module) are never collapsed into one.
    """
    findings: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for key in FINDING_ARRAY_KEYS:
        for finding in artifact.get(key) or []:
            if not isinstance(finding, dict):
                continue
            identity = _finding_identity(finding)
            if identity in seen:
                continue
            seen.add(identity)
            findings.append(finding)

    legacy = artifact.get("warnings") or []
    for warning in legacy:
        converted = legacy_warning_to_finding(warning)
        identity = _finding_identity(converted)
        if identity in seen:
            continue
        findings.append(converted)
        seen.add(identity)
    return findings


ML_MODULE_PREFIXES = ("backend/src/juli_backend/ai/", "backend/ai/")


def ml_modules_touched(modules: Iterable[str]) -> list[str]:
    """Return module paths under ``backend/ai/`` touched by the change."""
    touched: list[str] = []
    for module in modules:
        normalized = str(module).replace("\\", "/")
        if normalized in {"backend/ai", "backend/src/juli_backend/ai"}:
            touched.append(normalized)
            continue
        if any(normalized.startswith(prefix) for prefix in ML_MODULE_PREFIXES):
            touched.append(normalized)
    return touched


def warning_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("severity") == "WARNING"]


def finding_is_acknowledged(finding: dict[str, Any]) -> bool:
    """A gating WARNING finding is mergeable only after explicit dual signoff."""
    if not finding.get("acceptanceByReviewer"):
        return False
    if not finding.get("ownerAck"):
        return False
    if finding.get("fixedInCommit"):
        return True
    return bool(finding.get("shipAsIsReason"))


def unacknowledged_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in warning_findings(findings) if not finding_is_acknowledged(f)]


NON_OVERRIDABLE_FAIL_PREFIXES = (
    "CRITICAL security finding",
    "production data exposure",
)


def is_overridable_fail_reason(reason: str) -> bool:
    return not any(reason.startswith(prefix) for prefix in NON_OVERRIDABLE_FAIL_PREFIXES)


def overridden_merge_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    """Validate audited hotfix override metadata on a review artifact."""
    override = artifact.get("overriddenMerge")
    if not override:
        return False, ""
    required = ("timestamp", "overriddenBy", "reason", "incidentLink")
    missing = [field for field in required if not override.get(field)]
    if missing:
        return False, f"overriddenMerge missing: {', '.join(missing)}"
    return True, ""


def effective_mandatory_fail_reasons(artifact: dict[str, Any]) -> list[str]:
    """Mandatory fails after applying a valid audited override (hotfix path)."""
    reasons = mandatory_fail_reasons(artifact)
    if not overridden_merge_valid(artifact)[0]:
        return reasons
    return [reason for reason in reasons if not is_overridable_fail_reason(reason)]


def merge_override_active(artifact: dict[str, Any]) -> bool:
    """True when a valid override clears all overridable mandatory fail triggers."""
    if not overridden_merge_valid(artifact)[0]:
        return False
    return bool(mandatory_fail_reasons(artifact)) and not effective_mandatory_fail_reasons(artifact)


def ml_gates_satisfied(artifact: dict[str, Any]) -> tuple[bool, list[str]]:
    """ML-touched reviews must document cold-start handling and promotion gate."""
    touched = ml_modules_touched(artifact.get("modulesTouched") or [])
    if not touched:
        return True, []
    ml_gates = artifact.get("mlGates") or {}
    problems: list[str] = []
    if not ml_gates.get("coldStartThresholdDocumented"):
        problems.append("mlGates.coldStartThresholdDocumented required for ML modules")
    if not ml_gates.get("promotionGateDocumented"):
        problems.append("mlGates.promotionGateDocumented required for ML modules")

    from ml_thresholds import verify_ml_gates_threshold_values  # noqa: PLC0415

    scan_ok, scan_problems, _ = verify_ml_gates_threshold_values(touched)
    if not scan_ok:
        problems.extend(scan_problems)
    return len(problems) == 0, problems


def mandatory_fail_reasons(artifact: dict[str, Any]) -> list[str]:
    """Non-overridable FAIL triggers enforced before merge."""
    reasons: list[str] = []
    findings = normalize_review_findings(artifact)

    for finding in findings:
        if finding.get("type") == "security" and finding.get("severity") == "CRITICAL":
            reasons.append(
                f"CRITICAL security finding (no override): {finding.get('description', '')[:120]}"
            )
        if finding.get("type") in ("production_data_exposure", "data_exposure"):
            reasons.append(
                f"production data exposure (no override): {finding.get('description', '')[:120]}"
            )

    unit = artifact.get("testCoverage", {}).get("unit", {})
    failed = int(unit.get("failed", 0))
    if failed > 0:
        reasons.append(f"test regression: {failed} unit test(s) failed")

    acceptance = artifact.get("testCoverage", {}).get("acceptance", {})
    total = int(acceptance.get("total", 0))
    mapped = int(acceptance.get("mapped", 0))
    if total != mapped:
        reasons.append(f"incomplete acceptance criteria: mapped {mapped}/{total}")
    unmapped = acceptance.get("unmapped") or []
    if unmapped:
        reasons.append(f"unmapped acceptance criteria: {unmapped}")

    for blocker in artifact.get("priorReviewBlockers") or []:
        if not blocker.get("resolved"):
            label = blocker.get("description") or blocker.get("id") or "unknown"
            reasons.append(f"unresolved prior review blocker: {label}")

    ml_ok, ml_problems = ml_gates_satisfied(artifact)
    if not ml_ok:
        reasons.extend(ml_problems)

    return reasons


def warnings_require_signoff(artifact: dict[str, Any]) -> bool:
    """PASS_WITH_WARNINGS requires reviewer + owner signoff and per-finding ack."""
    return artifact.get("status") == "PASS_WITH_WARNINGS"


def reviewer_signoff_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    if not warnings_require_signoff(artifact):
        return True, ""
    signoff = artifact.get("reviewerSignoff") or {}
    if not signoff.get("statement"):
        return False, "reviewerSignoff.statement missing"
    if not signoff.get("timestamp"):
        return False, "reviewerSignoff.timestamp missing"
    if signoff.get("acceptedRisks") is not True:
        return False, "reviewerSignoff.acceptedRisks must be true"
    return True, ""


def owner_signoff_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    if not warnings_require_signoff(artifact):
        return True, ""
    signoff = artifact.get("ownerSignoff") or {}
    if not signoff.get("statement"):
        return False, "ownerSignoff.statement missing"
    if not signoff.get("timestamp"):
        return False, "ownerSignoff.timestamp missing"
    if signoff.get("acknowledged") is not True:
        return False, "ownerSignoff.acknowledged must be true"
    return True, ""


def derive_review_status(
    findings: Iterable[dict[str, Any]],
    artifact: dict[str, Any] | None = None,
) -> str:
    """Compute ADR-003 review status from normalized findings and artifact context."""
    if artifact is not None and mandatory_fail_reasons(artifact):
        return "FAIL"

    findings_list = list(findings)
    if any(f.get("severity") == "CRITICAL" for f in findings_list):
        return "FAIL"
    if any(f.get("actionRequired") for f in findings_list):
        return "FAIL"
    if any(f.get("severity") == "WARNING" for f in findings_list):
        return "PASS_WITH_WARNINGS"
    return "PASS"


def review_status_issues(artifact: dict[str, Any]) -> list[str]:
    """Return human-readable status/findings mismatches without mutating the artifact."""
    issues: list[str] = []
    legacy = artifact.get("warnings") or []
    if legacy:
        issues.append(
            f"legacy warnings[] has {len(legacy)} entr{'y' if len(legacy) == 1 else 'ies'}; "
            "migrate to criticalFindings and set status via generate_review_artifact.py"
        )

    findings = normalize_review_findings(artifact)
    derived = derive_review_status(findings, artifact)
    current = artifact.get("status")
    if current not in {"PASS", "PASS_WITH_WARNINGS", "FAIL"}:
        issues.append(f"invalid status: {current!r}")
    elif current != derived:
        warning_count = sum(1 for f in findings if f.get("severity") == "WARNING")
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        issues.append(
            f"status {current!r} does not match derived {derived!r} "
            f"(warnings={warning_count}, critical={critical_count})"
        )
    return issues


def normalize_review_artifact(
    artifact: dict[str, Any],
    *,
    fix_status: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize findings and optionally align status. Returns (artifact, issues)."""
    artifact["criticalFindings"] = normalize_review_findings(artifact)
    if artifact.get("warnings"):
        artifact.pop("warnings", None)

    if fix_status:
        artifact["status"] = derive_review_status(artifact["criticalFindings"], artifact)
        return artifact, []

    return artifact, review_status_issues(artifact)


def finalize_review_artifact(
    artifact: dict[str, Any],
    *,
    phase_run_id: str | None = None,
    source_implementation: str | None = None,
) -> dict[str, Any]:
    """Normalize findings, align status, and add Meta fields."""
    normalize_review_artifact(artifact, fix_status=True)
    return enrich_review_artifact(
        artifact,
        phase_run_id=phase_run_id,
        source_implementation=source_implementation,
    )


def implementation_artifact_path(issue: int) -> Path:
    return IMPLEMENTATIONS_DIR / f"implementation-issue-{issue}.json"


def enrich_review_artifact(
    artifact: dict[str, Any],
    *,
    phase_run_id: str | None = None,
    source_implementation: str | None = None,
) -> dict[str, Any]:
    """Add Agent Runtime Meta fields; preserve ADR-003 CI gate fields."""
    findings = normalize_review_findings(artifact)
    artifact["criticalFindings"] = findings
    review_failures = sum(
        1
        for finding in findings
        if finding.get("severity") == "CRITICAL" or finding.get("actionRequired")
    )
    if any(f.get("severity") == "CRITICAL" for f in findings):
        aggregate_severity = "critical"
    elif any(f.get("severity") == "WARNING" for f in findings):
        aggregate_severity = "medium"
    elif findings:
        aggregate_severity = "low"
    else:
        aggregate_severity = "none"

    artifact["schemaVersion"] = RUNTIME_SCHEMA_VERSION
    artifact["artifactType"] = "review"
    artifact["reviewStatus"] = artifact.get("status")
    artifact["reviewFailures"] = review_failures
    artifact["findings"] = findings
    artifact["severity"] = aggregate_severity
    artifact["securityFindings"] = [f for f in findings if f.get("type") == "security"]
    artifact["architectureFindings"] = [
        f for f in findings if f.get("type") in ("boundary_violation", "interface_change", "drift")
    ]
    artifact["maintainabilityFindings"] = [
        f for f in findings if f.get("type") in ("test_gap", "other", "drift")
    ]
    artifact["suggestedRemediation"] = [s for f in findings if (s := f.get("suggestion"))]
    artifact.setdefault("staticAnalysisExecuted", True)
    unit = artifact.get("testCoverage", {}).get("unit", {})
    artifact.setdefault("dynamicTestsExecuted", bool(unit.get("passed") or unit.get("failed")))
    if phase_run_id:
        artifact["phaseRunId"] = phase_run_id
    elif not artifact.get("phaseRunId"):
        # #1881: no explicit id and nothing already recorded (a fresh build,
        # not a refresh) -- derive from the single owning helper rather than
        # leaving the field unset, which is how the three competing
        # conventions this issue fixes each got invented independently.
        artifact["phaseRunId"] = derive_phase_run_id(artifact.get("issue", 0))
    if source_implementation:
        artifact["sourceImplementationArtifact"] = source_implementation
    impl_path = implementation_artifact_path(artifact.get("issue", 0))
    if source_implementation is None and impl_path.exists():
        artifact["sourceImplementationArtifact"] = impl_path.relative_to(REPO_ROOT).as_posix()
    return artifact


def enrich_validation_artifact(
    artifact: dict[str, Any],
    issue: int,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add Agent Runtime Meta fields; preserve ADR-003 CI gate fields."""
    failed = artifact.get("failedChecks", 0)
    unit = (review or {}).get("testCoverage", {}).get("unit", {})
    tests_passed = int(unit.get("passed", 0))
    tests_failed = int(unit.get("failed", 0))
    tests_executed = tests_passed + tests_failed
    review_status = (review or {}).get("status")
    warning_gated = review_status == "PASS_WITH_WARNINGS"

    artifact["schemaVersion"] = RUNTIME_SCHEMA_VERSION
    artifact["artifactType"] = "validation"
    artifact["sourceReviewArtifact"] = review_artifact_path(issue).relative_to(REPO_ROOT).as_posix()
    artifact["validationFailures"] = failed
    artifact["readyForShip"] = artifact.get("readyForMerge", False)
    artifact["warningGated"] = warning_gated
    artifact["retryCount"] = 0
    artifact["testsExecuted"] = tests_executed
    artifact["testsPassed"] = tests_passed
    artifact["testsFailed"] = tests_failed
    artifact.setdefault("coveragePercentage", 0)
    artifact.setdefault("benchmarkStatus", "not_run")
    # #1732 governs the *implementation* artifact. The validation artifact's own
    # schema still requires a plain integer here, so the two-shape default does
    # not belong in this builder -- extending it is a separate slice, not a
    # side effect of this one.
    artifact.setdefault("executionDurationMs", 0)
    if review and review.get("phaseRunId"):
        artifact["phaseRunId"] = review["phaseRunId"]
    # Stamp releaseEvidencePlanId from implementation so ADR-035 continuity
    # can verify the written validation artifact (generator runs gates first).
    implementation = load_implementation_artifact(issue)
    if implementation and implementation.get("releaseEvidencePlanId"):
        artifact["releaseEvidencePlanId"] = implementation["releaseEvidencePlanId"]
    return artifact


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


def _is_type_checking_guard(test: ast.expr) -> bool:
    """Whether an ``if`` test is the ``TYPE_CHECKING`` guard.

    Both spellings in the tree are recognised — a bare ``TYPE_CHECKING`` name
    and a qualified ``typing.TYPE_CHECKING`` attribute. A negated guard
    (``if not TYPE_CHECKING:``) is deliberately NOT recognised: it is a
    UnaryOp, so the branch is traversed normally and its imports are kept.
    Failing conservatively here keeps an edge that might be real rather than
    dropping one that is.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def runtime_import_froms(tree: ast.AST) -> Iterator[ast.ImportFrom]:
    """Every ``from X import …`` that actually executes.

    A TYPE_CHECKING import is not a dependency: it never runs, and its whole
    purpose is to express a type relationship WITHOUT creating a runtime one —
    `database/__init__.py` says so in its own docstring, guarding its
    `services.etl` import so `repositories` can finish loading. Counting those
    as edges invented a six-module import cycle (`database` → `services/etl` →
    `integrations/tiktok` → `core/security` → `database`) the moment #1859 made
    `parse_architecture_map` honest enough for `collect_import_graph` to see
    anything at all. Only the guard's ``else`` branch runs, so only that is
    traversed.

    The `from __future__ import annotations` case needs no handling: this
    extractor reads ImportFrom nodes, never annotations, so a stringified
    annotation cannot produce an edge either way — and `__future__` itself
    resolves to no module.
    """
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ImportFrom):
            yield node
            continue
        if isinstance(node, ast.If) and _is_type_checking_guard(node.test):
            stack.extend(node.orelse)
            continue
        stack.extend(ast.iter_child_nodes(node))


def collect_import_graph(modules: dict[str, ModuleInfo]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {m: set() for m in modules}
    for py_file in (REPO_ROOT / "backend").rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        owner = module_for_file(rel, modules)
        if not owner:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in runtime_import_froms(tree):
            if not node.module:
                continue
            imported = resolve_import_to_module(node.module, modules)
            if imported and imported != owner:
                graph[owner].add(imported)
    return graph


def resolve_import_to_module(module_name: str, modules: dict[str, ModuleInfo]) -> str | None:
    logical_name = module_name
    if module_name.startswith("juli_backend."):
        logical_name = "backend." + module_name.removeprefix("juli_backend.")
    dotted = logical_name.replace(".", "/")
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        pkg = path_to_package(module_path)
        if module_name == pkg or module_name.startswith(pkg + "."):
            return module_path
        if logical_name == pkg or logical_name.startswith(pkg + "."):
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
        if rel.startswith("docs/adr/") and ADR_FILE_RE.match(name):
            adrs.append(rel)
    return adrs


def print_check_result(name: str, passed: bool, detail: str = "") -> int:
    status = "PASS" if passed else "FAIL"
    line = f"{name}: {status}"
    if detail:
        line += f" — {detail}"
    print(line)
    return 0 if passed else 1


@dataclass(frozen=True)
class AllowedCycleEdge:
    """One import edge excused from cycle detection, with its evidence."""

    reason: str
    importSites: tuple[str, ...]


_TIKTOK_AUTH_INVERSION = (
    "Real runtime edge, not a TYPE_CHECKING artifact — verified as a top-level "
    "import at each site below. `core/security` owns the TikTok OAuth lifecycle "
    "(credential refresh, token expiry), and the TikTok client and service layers "
    "call back up into it, while `core/security` imports the client to perform the "
    "refresh. That mutual reach is the architectural fact; it predates this gate "
    "being able to see anything at all, and breaking it means moving the refresh "
    "seam, which is an owner decision for another lane, not a harness change. "
    "Named here so the cycle is recorded rather than tolerated in silence."
)

# The MINIMUM feedback arc set: removing exactly these two edges dissolves the
# five-module SCC (`services/etl`, `services/ingestion`, `services/tiktok`,
# `core/security`, `integrations/tiktok`). Enumerating all nine edges inside the
# SCC instead would have hidden any genuinely NEW cycle among those modules, so
# only the back-edges are excused and the rest of the graph stays live.
KNOWN_CYCLE_EDGES: dict[tuple[str, str], AllowedCycleEdge] = {
    ("backend/integrations/tiktok", "backend/core/security"): AllowedCycleEdge(
        reason=_TIKTOK_AUTH_INVERSION,
        importSites=(
            "backend/src/juli_backend/integrations/tiktok/reactive_refresh.py:50 "
            "from juli_backend.core.security import credential_refresh",
        ),
    ),
    ("backend/services/tiktok", "backend/core/security"): AllowedCycleEdge(
        reason=_TIKTOK_AUTH_INVERSION,
        importSites=(
            "backend/src/juli_backend/services/tiktok/app_review_store.py:10 "
            "from juli_backend.core.security.tiktok_oauth",
            "backend/src/juli_backend/services/tiktok/business_advertiser_oauth.py:15 "
            "from juli_backend.core.security.exceptions",
            "backend/src/juli_backend/services/tiktok/credential_binding.py:63 "
            "from juli_backend.core.security",
        ),
    ),
}


def graph_without_allowlisted_edges(
    graph: dict[str, set[str]],
    allowlist: dict[tuple[str, str], AllowedCycleEdge],
) -> dict[str, set[str]]:
    """Drop only the named back-edges; every other edge stays in the graph.

    The allowlist is a parameter, not a module global, so each caller keeps
    its own patchable reference and the two consumers of this graph cannot
    drift apart silently.
    """
    return {
        owner: {target for target in targets if (owner, target) not in allowlist}
        for owner, targets in graph.items()
    }
