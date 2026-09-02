"""Capture provider (#1442): the environment a run actually executed in.

Eight sessions diagnosed environment drift as a code bug. Two mechanisms did
most of that damage and this block exists to make both of them unmissable in
the one artifact that survives to ``main``:

* **Resolution.** One editable ``.pth`` decides where ``juli_backend`` imports
  from. When it points at a different checkout, the agent edits correct code,
  the test still fails, and nothing in the failure output says "you are running
  someone else's source" -- it reads as an ordinary assertion failure.
* **Base distance.** A base 17 commits behind ``origin/main`` broke ~61 tests
  through an Alembic ``ResolutionError``. ``checkout_preflight`` only fires at
  >=50 commits or >=7 days, so 17 was invisible; the number itself is the fact
  that was missing.

Two rules shape the shape of this block.

**A wrong resolution is fatal; an unknown one is merely recorded.** Resolving
outside the checkout that owns this file raises :class:`EnvironmentDriftError`,
which the registry turns into a ``CaptureProviderError`` and which aborts
record generation -- a record asserting a green run against code from another
tree is worse than no record. Failing to import ``juli_backend`` at all is not
fatal: it is recorded as ``resolved: null`` with the import error, which is
explicit rather than silent, and record generation does not require the backend
to be installed in the generating interpreter.

**Never publish a number that was not observed.** CI checks this repo out
shallow for every pytest job, and ``git rev-list --count HEAD..origin/main``
answers a shallow clone with a number that means nothing. So shallowness is
detected first and ``behindOriginMain`` is left ``null`` beside a
``baseDistanceUnavailable`` reason. A confident ``0`` there would recreate the
exact false-assurance this slice removes.

Stdlib only, by constraint: this module is imported by ``discover_providers``
during CI record generation, where nothing but the standard library and the
already-installed backend can be assumed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "environment"

#: Package whose import resolution decides whether a run tested its own code.
TRACKED_MODULE = "juli_backend"
#: Path of the exact-pin lock, relative to the repo root.
CONSTRAINTS_RELPATH = Path("backend") / "constraints.txt"
#: Where the tracked module must live inside the checkout, relative to the root.
MODULE_RELPATH = Path("backend") / "src" / TRACKED_MODULE

_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")
_NORMALIZE_RE = re.compile(r"[-_.]+")

_UNSET = object()

GitRunner = Callable[..., "str | None"]


class EnvironmentDriftError(RuntimeError):
    """The run is executing against code outside the checkout that owns it."""


def _normalize(name: str) -> str:
    """PEP 503 canonical form, so ``SQLAlchemy`` and ``sqlalchemy`` are one."""
    return _NORMALIZE_RE.sub("-", name).lower()


def _repo_root() -> Path:
    """The checkout owning *this file* -- never the process's cwd.

    Deriving the root from ``__file__`` is the point: a sub-agent invoked with
    a stale cwd would otherwise validate the wrong tree and report agreement.
    """
    return Path(__file__).resolve().parents[4]


def _resolve_module_file() -> Path | None:
    """Import the tracked module and return the file it actually came from."""
    import importlib

    module = importlib.import_module(TRACKED_MODULE)
    origin = getattr(module, "__file__", None)
    return Path(origin).resolve() if origin else None


def _run_git(*args: str, cwd: Path) -> str | None:
    """Run one git command, returning trimmed stdout or ``None`` on failure."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # git absent from PATH
        return None
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    return output or None


def _installed_versions() -> dict[str, str]:
    """Canonical-name -> version for every distribution in this interpreter."""
    versions: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"] if distribution.metadata else None
        if not name:
            continue
        version = distribution.version
        if version:
            versions.setdefault(_normalize(name), version)
    return versions


def _module_resolution(resolved: Path | None, repo_root: Path, error: str | None) -> dict[str, Any]:
    expected = (repo_root / MODULE_RELPATH).resolve()
    if resolved is None:
        return {
            "module": TRACKED_MODULE,
            "resolved": None,
            "expectedPrefix": str(expected),
            "insideRepo": False,
            "error": error or f"{TRACKED_MODULE} exposes no __file__",
        }
    if not resolved.is_relative_to(expected):
        raise EnvironmentDriftError(
            f"{TRACKED_MODULE} resolves to {resolved}, outside the checkout under test; "
            f"expected it under {expected}. The run would test code from another "
            "tree, so every pass and every failure below it is unattributable. "
            "Fix the editable install or pin PYTHONPATH to this checkout."
        )
    return {
        "module": TRACKED_MODULE,
        "resolved": str(resolved),
        "expectedPrefix": str(expected),
        "insideRepo": True,
        "error": None,
    }


def _git_block(git: GitRunner) -> dict[str, Any]:
    shallow = git("rev-parse", "--is-shallow-repository") == "true"
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")

    behind: int | None = None
    unavailable: str | None = None
    if shallow:
        # CI checks out shallow for every pytest job; the count below would
        # answer with a number derived from a truncated history.
        unavailable = "shallow-clone"
    else:
        raw = git("rev-list", "--count", "HEAD..origin/main")
        if raw is None:
            unavailable = "no-origin-main"
        elif raw.isdigit():
            behind = int(raw)
        else:
            unavailable = f"unparseable-count:{raw}"

    return {
        "head": head,
        "branch": branch,
        "shallow": shallow,
        "behindOriginMain": behind,
        "baseDistanceUnavailable": unavailable,
    }


def _dependency_block(
    constraints_text: str, installed: Mapping[str, str], constraints_path: Path
) -> dict[str, Any]:
    drift: list[dict[str, str]] = []
    missing: list[str] = []
    pinned = 0
    matched = 0

    lookup = {_normalize(name): version for name, version in installed.items()}

    for line in constraints_text.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            # Blank, a comment, or a pip-compile `# via ...` continuation.
            continue
        match = _PIN_RE.match(line.strip())
        if match is None:
            continue
        name, want = match.group(1), match.group(2)
        pinned += 1
        have = lookup.get(_normalize(name))
        if have is None:
            missing.append(name)
        elif have != want:
            drift.append({"package": name, "pinned": want, "installed": have})
        else:
            matched += 1

    drift.sort(key=lambda entry: _normalize(entry["package"]))
    missing.sort(key=_normalize)
    return {
        "constraints": str(constraints_path),
        "pinned": pinned,
        "matched": matched,
        "drift": drift,
        "missing": missing,
    }


def fingerprint(
    *,
    repo_root: Path | str | None = None,
    module_file: Path | str | None = _UNSET,  # type: ignore[assignment]
    git: GitRunner | None = None,
    constraints_text: str | None = None,
    installed_versions: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Build the ``environment`` block.

    Every input has a real default and a keyword seam. The seams exist so the
    tests can plant a drifted environment the machine running them does not
    have -- a fingerprint that can only be checked against a healthy machine
    proves nothing about the unhealthy one.
    """
    root = _repo_root() if repo_root is None else Path(repo_root).resolve()

    resolution_error: str | None = None
    if module_file is _UNSET:
        try:
            resolved = _resolve_module_file()
        except Exception as exc:  # noqa: BLE001 - recorded, see module docstring
            resolved = None
            resolution_error = f"{type(exc).__name__}: {exc}"
    else:
        resolved = Path(module_file).resolve() if module_file is not None else None

    # Checked before anything else reads the disk: a resolution into another
    # tree is the failure that most needs naming, and a second problem in this
    # same environment must not get to mask it in the error message.
    module_resolution = _module_resolution(resolved, root, resolution_error)

    runner: GitRunner
    if git is None:

        def runner(*args: str) -> str | None:
            return _run_git(*args, cwd=root)

    else:
        runner = git

    constraints_path = root / CONSTRAINTS_RELPATH
    if constraints_text is None:
        try:
            constraints_text = constraints_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EnvironmentDriftError(
                f"cannot read the dependency lock at {constraints_path}: {exc}"
            ) from exc

    installed = _installed_versions() if installed_versions is None else installed_versions

    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": str(Path.cwd() if cwd is None else Path(cwd)),
        "repoRoot": str(root),
        "moduleResolution": module_resolution,
        "git": _git_block(runner),
        "dependencies": _dependency_block(constraints_text, installed, constraints_path),
    }


def capture(context: CaptureContext) -> dict[str, Any]:
    """Return the environment fingerprint observed at record-generation time.

    The context deliberately carries no environment state, so this provider
    reads the live interpreter, the installed distributions and git itself.
    That is not reaching around the context -- the context's warning is about
    re-reading the review/validation bodies, which this never touches.
    """
    return fingerprint()
