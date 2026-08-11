#!/usr/bin/env python3
"""AST guard: fail the build when a credential-shaped key travels in a request
URL / `params=` mapping instead of the request body (#904, ADR-061).

## The incident this exists to catch

`TikTokAuth._token_request` (commit history: `backend/src/juli_backend/
integrations/tiktok/auth.py`, fixed in `bfade493` / issue #896) sent
`app_secret`, `auth_code`, and `refresh_token` as `requests.get(url,
params=payload)` — a GET query string. `requests`/`urllib3` embed the full
request URL, query string included, into `ConnectionError`/`HTTPError`
messages, so a single transport failure or non-2xx response from TikTok would
have written live OAuth credentials into the failure log once structured
logging landed (#902). The sibling Business clients
(`business_account_holder_auth.py`, `business_advertiser_auth.py`) sent the
exact same shape of payload via `requests.post(url, json=payload)` and were
never at risk — the difference was one call invisible to code review and to
every automated check the repo ran at the time: ruff has no rule for *where*
a legitimately-sourced secret is placed in a request, and bandit's S-rules
cover hardcoded secret literals (S105/S106) and missing timeouts (S113), not
this. Issue #904 is the guard that would have caught it.

## What this checks

Walks each file's AST (no import, no execution) looking for credential-shaped
keys (see `CREDENTIAL_KEY_NAMES`) reaching a request URL via three shapes:

1. A `params=` mapping passed to a `requests`/`httpx`-style call
   (`.get/.post/.put/.patch/.delete/.request(...)`) — whether the mapping is
   a dict literal at the call site, or a same-function local variable built
   up via subscript assignment (`params["access_token"] = ...`) or
   `.update(...)`.
2. A `urllib.parse.urlencode(...)` call — the exact query-string-building
   primitive the original bug used for `generate_auth_url`.
3. An f-string or `+` string concatenation that embeds a literal
   `?key=`/`&key=` query fragment directly into a URL.

## Precision: why not bare "key", "auth", or "token"

The issue's own hint list (`secret`, `token`, `key`, `password`,
`authorization`, ...) is not used as bare substrings — a substring match on
"key" or "token" alone produces real false positives *in this exact
codebase*: `client.py`'s pagination cursor (`page_token`, `next_page_token`),
its OAuth *client id* (`app_key`, which is public, not secret — the OAuth
analogue of `client_id`), and unrelated cache/log identifiers
(`workflow_key`, `shop_key`, `envelope_cache_key`, `job_correlation_token`)
all contain one of those substrings but carry no secret. `CREDENTIAL_KEY_NAMES`
is instead a closed set of normalized (lowercased, separators stripped)
*compound* names — `access_token`, `refresh_token`, `api_key`, `app_secret`,
`client_secret`, `password`, `authorization`, `credential(s)`, ... — verified
empty against a full-repo inventory of every `*token*`, `*key*`, `*secret*`,
`*auth*`, `*password*`, `*credential*` string literal before being locked in
(see PR #904 description for the inventory).

`auth_code`/`authorization_code` is deliberately **excluded**, even though the
original incident's commit message names it alongside `app_secret` and
`refresh_token`: the OAuth 2.0 authorization-code grant *requires* the code
to arrive as an inbound `?code=`/`?auth_code=` query parameter on the
provider's browser redirect — that is the spec, not a choice this codebase
makes — and `tests/unit/test_tiktok_business_account_holder_callback.py`
exercises exactly that shape via a test HTTP client
(`client.get(CALLBACK_PATH, params={"auth_code": ...})`) hitting our own
callback route, not a real vendor endpoint. Flagging it would have meant
suppressing every callback test. The regression this check exists to catch
is still caught in full: `app_secret`/`client_secret` alone is unambiguous
and was present in the same violating dict in the original bug.

## Known, legitimate exceptions in this tree

Two vendor APIs require the access token as a query parameter by design
(request-signing scheme), not as a bug:

- `TikTokShopClient._build_params` (non-header-auth endpoints)
- `ZaloOaAdapter._deliver` (Zalo OA message-send endpoint)

Both carry an explicit `# creds-url-guard: allow -- <reason>` suppression
comment (see `SUPPRESSION_RE`) on the flagged line (or the line directly
above it) — the only way to silence a finding. Comment-only suppression with
no reason after `--` does not count.

## Usage

    python agent-runtime/scripts/ci/check_credentials_in_url.py [PATH ...]

With no arguments, scans the same three roots the `lint` CI job already
passes to ruff (`backend/src/juli_backend tests scripts`) — this check is
wired into that same job/step group, not a new one. `tests/fixtures/` is
always skipped in a directory sweep: that directory holds synthetic,
deliberately-violating fixtures for this and other `agent-runtime/scripts/ci`
checkers (this checker's own fixture included), and must never gate CI on
its own account. Unit tests exercise the fixture directly via `scan_file`,
bypassing that skip.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCAN_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "backend" / "src" / "juli_backend",
    REPO_ROOT / "tests",
    REPO_ROOT / "scripts",
)

# Closed set of normalized (lowercase, non-alphanumeric stripped) credential-
# shaped key names. Deliberately excludes bare "key", "auth", and "token" —
# see the "Precision" section of the module docstring.
CREDENTIAL_KEY_NAMES: frozenset[str] = frozenset(
    {
        "secret",
        "appsecret",
        "clientsecret",
        "apisecret",
        "sharedsecret",
        "oauthsecret",
        "shopsecret",
        "token",
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "idtoken",
        "bearertoken",
        "sessiontoken",
        "password",
        "passwd",
        "pwd",
        "authorization",
        "credential",
        "credentials",
        "apikey",
        "secretkey",
        "privatekey",
        "accesskey",
        "signingkey",
        "encryptionkey",
        "clientkey",
    }
)

_HTTP_METHOD_NAMES = frozenset({"get", "post", "put", "patch", "delete", "request"})
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_QUERY_KEY_RE = re.compile(r"[?&]([A-Za-z_][A-Za-z0-9_]*)=")
SUPPRESSION_RE = re.compile(r"#\s*creds-url-guard:\s*allow\s*--\s*\S")


@dataclass(frozen=True)
class CredentialUrlHit:
    file: str
    line: int
    key: str
    rule: str  # "params_mapping" | "urlencode" | "url_literal"


def _normalize_key(raw: str) -> str:
    return _NON_ALNUM_RE.sub("", raw.lower())


def _is_credential_key(raw: str) -> bool:
    return _normalize_key(raw) in CREDENTIAL_KEY_NAMES


def _attach_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]


def _enclosing_scope(node: ast.AST) -> ast.AST:
    """Nearest enclosing function (or the module) — the variable-resolution
    boundary used to resolve a `params=<name>` argument back to its
    assignment, without bleeding across unrelated functions that happen to
    reuse a common local name like `params`."""
    current = getattr(node, "parent", None)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Module):
            return current
        current = getattr(current, "parent", None)
    return node


def _call_func_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_request_like_call(call: ast.Call) -> bool:
    if _call_func_name(call) not in _HTTP_METHOD_NAMES:
        return False
    return any(kw.arg == "params" for kw in call.keywords)


def _is_urlencode_call(call: ast.Call) -> bool:
    return _call_func_name(call) == "urlencode"


def _dict_literal_credential_keys(node: ast.expr | None) -> list[tuple[str, int]]:
    """(key, lineno) pairs for credential-shaped string keys in a Dict literal.

    `**unpack` entries (``key_node is None``) are skipped — they can't be
    inspected statically without resolving the unpacked mapping's origin.
    """
    if not isinstance(node, ast.Dict):
        return []
    hits: list[tuple[str, int]] = []
    for key_node, _value in zip(node.keys, node.values, strict=True):
        if key_node is None:
            continue
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            if _is_credential_key(key_node.value):
                hits.append((key_node.value, key_node.lineno))
    return hits


def _direct_return_name(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The Name in a top-level ``return <Name>`` inside `func`'s own scope, if
    any — the "accumulator dict, returned at the end" shape `_build_params`
    uses. Only a plain `return <Name>` counts; anything else (a computed
    expression, a literal, no return) is out of scope for the one-hop
    resolution below."""
    for node in ast.walk(func):
        if _enclosing_scope(node) is not func:
            continue
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
            return node.value.id
    return None


def _params_mapping_hits(tree: ast.Module, rel_file: str) -> list[CredentialUrlHit]:
    # Pass 0: index every function/method by name and, for each, the Name it
    # `return`s (if a plain `return <Name>`). Lets a one-hop resolution catch
    # `all_params = self._build_params(...); ...(params=all_params)` — the
    # real shape `TikTokShopClient._build_params` uses to assemble
    # `access_token` into the query params for non-header-auth endpoints.
    functions_by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    return_vars: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions_by_name.setdefault(node.name, []).append(node)
            return_name = _direct_return_name(node)
            if return_name:
                return_vars[id(node)] = return_name

    # Pass 1: record every credential-shaped key assigned into a locally
    # named mapping, per enclosing scope — `name[<key>] = value`,
    # `name = {<dict literal>}`, and `name.update(...)` — plus which helper
    # function (if any) a name was assigned from, e.g. `all_params =
    # self._build_params(path, params)`.
    scope_assignments: dict[int, dict[str, list[tuple[str, int]]]] = {}
    call_assignments: dict[int, dict[str, str]] = {}

    def _record(scope_id: int, name: str, key: str, lineno: int) -> None:
        scope_assignments.setdefault(scope_id, {}).setdefault(name, []).append((key, lineno))

    for node in ast.walk(tree):
        scope_id = id(_enclosing_scope(node))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                    and _is_credential_key(target.slice.value)
                ):
                    _record(scope_id, target.value.id, target.slice.value, target.lineno)
                if isinstance(target, ast.Name):
                    for key, lineno in _dict_literal_credential_keys(node.value):
                        _record(scope_id, target.id, key, lineno)
                    if isinstance(node.value, ast.Call):
                        called_name = _call_func_name(node.value)
                        if called_name in functions_by_name:
                            call_assignments.setdefault(scope_id, {})[target.id] = called_name
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
        ):
            name = node.func.value.id
            for arg in node.args:
                for key, lineno in _dict_literal_credential_keys(arg):
                    _record(scope_id, name, key, lineno)
            for kw in node.keywords:
                if kw.arg and _is_credential_key(kw.arg):
                    _record(scope_id, name, kw.arg, node.lineno)

    # Pass 2: find request-like calls and urlencode() calls, resolve their
    # mapping argument against the same-scope assignments recorded above,
    # falling back to one hop through a helper function when the name was
    # assigned from a call to one.
    hits: list[CredentialUrlHit] = []
    seen: set[tuple[int, str, str]] = set()

    def _emit(pairs: list[tuple[str, int]], rule: str) -> None:
        for key, lineno in pairs:
            dedup_key = (lineno, key, rule)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            hits.append(CredentialUrlHit(file=rel_file, line=lineno, key=key, rule=rule))

    def _resolve_name_hits(scope_id: int, name: str) -> list[tuple[str, int]]:
        direct = scope_assignments.get(scope_id, {}).get(name, [])
        if direct:
            return direct
        called_name = call_assignments.get(scope_id, {}).get(name)
        if not called_name:
            return []
        resolved: list[tuple[str, int]] = []
        for func in functions_by_name.get(called_name, []):
            return_var = return_vars.get(id(func))
            if return_var:
                resolved.extend(scope_assignments.get(id(func), {}).get(return_var, []))
        return resolved

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_request_like_call(node):
            params_kw = next(kw for kw in node.keywords if kw.arg == "params")
            value = params_kw.value
            if isinstance(value, ast.Dict):
                _emit(_dict_literal_credential_keys(value), "params_mapping")
            elif isinstance(value, ast.Name):
                scope_id = id(_enclosing_scope(node))
                _emit(_resolve_name_hits(scope_id, value.id), "params_mapping")
        elif _is_urlencode_call(node):
            for arg in node.args:
                _emit(_dict_literal_credential_keys(arg), "urlencode")
            for kw in node.keywords:
                _emit(_dict_literal_credential_keys(kw.value), "urlencode")

    return hits


def _flatten_add_chain(node: ast.expr) -> str | None:
    """Flatten a chain of string ``+`` concatenation into synthetic text, with
    non-string-literal operands replaced by a placeholder. Returns None for
    any shape this can't confidently flatten (kept conservative on purpose)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_add_chain(node.left)
        right = _flatten_add_chain(node.right)
        if left is None or right is None:
            return None
        return left + right
    return "\x00"  # opaque placeholder for any other expression


def _joinedstr_synthetic_text(node: ast.JoinedStr) -> str:
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("\x00")
    return "".join(parts)


def _url_literal_hits(tree: ast.Module, rel_file: str) -> list[CredentialUrlHit]:
    hits: list[CredentialUrlHit] = []
    for node in ast.walk(tree):
        text: str | None = None
        if isinstance(node, ast.JoinedStr):
            text = _joinedstr_synthetic_text(node)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parent = getattr(node, "parent", None)
            if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add):
                continue  # only flatten from the outermost node in the chain
            text = _flatten_add_chain(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent = getattr(node, "parent", None)
            if isinstance(parent, ast.JoinedStr):
                continue  # handled above
            if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add):
                continue  # handled above
            text = node.value
        if not text:
            continue
        for match in _QUERY_KEY_RE.finditer(text):
            key = match.group(1)
            if _is_credential_key(key):
                lineno = getattr(node, "lineno", 0)
                hits.append(
                    CredentialUrlHit(file=rel_file, line=lineno, key=key, rule="url_literal")
                )
    return hits


def _is_suppressed(source_lines: list[str], lineno: int) -> bool:
    """A hit is suppressed by an explicit ``# creds-url-guard: allow -- <reason>``
    comment: an inline trailing comment on the flagged line itself, or
    anywhere in the contiguous block of comment-only lines directly above it
    (covers a multi-line explanation placed above a call site)."""
    if not (1 <= lineno <= len(source_lines)):
        return False
    if SUPPRESSION_RE.search(source_lines[lineno - 1]):
        return True
    idx = lineno - 2  # 0-based index of the line directly above
    while idx >= 0:
        stripped = source_lines[idx].strip()
        if not stripped.startswith("#"):
            break
        if SUPPRESSION_RE.search(source_lines[idx]):
            return True
        idx -= 1
    return False


def scan_file(py_file: Path, *, repo_root: Path = REPO_ROOT) -> list[CredentialUrlHit]:
    """Scan a single Python file, honoring suppression comments. Works on any
    file path, including synthetic fixtures under ``tests/fixtures/`` that a
    directory sweep (`scan_paths`) deliberately skips."""
    try:
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []
    _attach_parents(tree)
    try:
        rel_file = py_file.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel_file = py_file.as_posix()

    raw_hits = _params_mapping_hits(tree, rel_file) + _url_literal_hits(tree, rel_file)
    source_lines = text.splitlines()
    return [hit for hit in raw_hits if not _is_suppressed(source_lines, hit.line)]


def _iter_python_files(paths: list[Path], *, repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for base in paths:
        if base.is_file():
            if base.suffix == ".py":
                files.append(base)
            continue
        if not base.exists():
            continue
        for py_file in sorted(base.rglob("*.py")):
            try:
                rel = py_file.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                rel = py_file.as_posix()
            if "tests/fixtures/" in rel:
                continue
            files.append(py_file)
    return files


def scan_paths(paths: list[Path], *, repo_root: Path = REPO_ROOT) -> list[CredentialUrlHit]:
    hits: list[CredentialUrlHit] = []
    for py_file in _iter_python_files(paths, repo_root=repo_root):
        hits.extend(scan_file(py_file, repo_root=repo_root))
    return hits


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import print_check_result  # noqa: E402

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files/dirs to scan (default: backend/src/juli_backend tests scripts)",
    )
    args = parser.parse_args()

    paths = args.paths or list(DEFAULT_SCAN_PATHS)
    hits = scan_paths(paths)
    for hit in hits:
        print(
            f"credentials_in_url: FAIL — {hit.file}:{hit.line}: credential-shaped key "
            f"{hit.key!r} reaches a request URL/params mapping (rule={hit.rule}); move it "
            "into the request body (json=/data=) or suppress with an explicit "
            "`# creds-url-guard: allow -- <reason>` comment at the call site",
            file=sys.stderr,
        )
    passed = not hits
    if passed:
        detail = "no credential-shaped keys found in a request URL or params= mapping"
    else:
        first = hits[0]
        detail = f"{len(hits)} finding(s); first: {first.file}:{first.line} key={first.key!r}"
    return print_check_result("credentials_in_url", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
