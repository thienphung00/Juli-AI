"""Capture-provider registry for the status record's ``run{}`` envelope (#1438).

``status/issue-<N>.json`` is the only artifact that survives to ``main``. Before
this module it could record only what an agent *typed* — its schema declares
``additionalProperties: false`` at the top level, so there was nowhere to put a
value the harness *observed*. ``gateVersion: 2`` adds a ``run{}`` object for
exactly that, and this module is the seam that fills it.

The seam, not the field, is the deliverable. Six Wave-2 slices each contribute
one block of ``run{}``. If each of them had to edit
``generate_status_records.py`` they would serialize against one another and
every merge would be a conflict on the same function. Instead each slice adds
**one module** to this package:

.. code-block:: python

    # agent-runtime/scripts/ci/capture_providers/tokens.py
    PROVIDER_NAME = "tokens"

    def capture(context: CaptureContext) -> dict[str, Any]:
        ...

``discover_providers()`` finds it by directory listing, so the writer learns
about "providers" and never about token counting, transcript parsing or git.
Write paths stay disjoint; the slices land in parallel.

Fail-closed, always (ADR/#1434 lock 2). A provider that raises, returns a
non-object, fails to import, omits its contract attributes, or collides with
another module's ``PROVIDER_NAME`` raises :class:`CaptureProviderError` naming
the offender. Emitting a record with a silently missing block would make the
absence of evidence indistinguishable from evidence of absence — which is the
whole defect class this envelope exists to close.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Module-level attribute naming the block a provider owns under ``run{}``.
PROVIDER_NAME_ATTR = "PROVIDER_NAME"
#: Module-level callable a provider exposes: ``capture(context) -> dict``.
CAPTURE_ATTR = "capture"


@dataclass(frozen=True)
class CaptureContext:
    """Everything a provider is given, and nothing it should reach around for.

    Providers receive the already-parsed review/validation bodies *and* their
    raw bytes, so a provider that needs to hash or measure the source does not
    re-read the filesystem and risk observing a different file than the record
    it is being written into.
    """

    issue: int
    review: dict[str, Any]
    validation: dict[str, Any]
    review_bytes: bytes
    validation_bytes: bytes


CaptureProvider = Callable[[CaptureContext], dict[str, Any]]


class CaptureProviderError(RuntimeError):
    """A provider could not produce its block. Never swallowed, never skipped.

    Carries :attr:`provider` so the caller can name the offender rather than
    reporting a generic generation failure.
    """

    def __init__(self, provider: str, cause: BaseException | str) -> None:
        self.provider = provider
        super().__init__(f"capture provider {provider!r} failed: {cause}")


_PROVIDERS: dict[str, CaptureProvider] = {}


def register_provider(name: str, provider: CaptureProvider, *, replace: bool = False) -> None:
    """Register ``provider`` as the owner of the ``run[name]`` block.

    Raises ``ValueError`` on a duplicate name unless ``replace`` is set — two
    providers silently sharing a block name would drop one slice's measurement
    on the floor.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("capture provider name must be a non-empty string")
    if not callable(provider):
        raise ValueError(f"capture provider {name!r} must be callable")
    if name in _PROVIDERS and not replace:
        raise ValueError(f"capture provider {name!r} is already registered")
    _PROVIDERS[name] = provider


def unregister_provider(name: str) -> None:
    """Drop ``name`` from the registry if present. Idempotent."""
    _PROVIDERS.pop(name, None)


def registered_providers() -> tuple[str, ...]:
    """Names currently registered, sorted — the block order in ``run{}``."""
    return tuple(sorted(_PROVIDERS))


@contextmanager
def provider_sandbox() -> Iterator[None]:
    """Snapshot the registry, restore it on exit.

    The registry is process-wide, so tests (and one-off tooling) that register a
    probe provider must not leak it into the next record generated in the same
    process.
    """
    saved = dict(_PROVIDERS)
    try:
        yield
    finally:
        _PROVIDERS.clear()
        _PROVIDERS.update(saved)


def capture_run_block(context: CaptureContext) -> dict[str, Any]:
    """Run every registered provider and return the assembled ``run{}`` object.

    Deterministic: providers run in sorted name order and the result is a plain
    dict, so ``generate_status_records.py`` stays byte-idempotent across reruns.
    """
    run: dict[str, Any] = {}
    for name in sorted(_PROVIDERS):
        try:
            block = _PROVIDERS[name](context)
        except Exception as exc:  # noqa: BLE001 — re-raised, named, never swallowed
            raise CaptureProviderError(name, exc) from exc
        if not isinstance(block, dict):
            raise CaptureProviderError(
                name,
                f"returned {type(block).__name__}, expected a JSON object block",
            )
        run[name] = block
    return run


def _load_module(path: Path) -> Any:
    module_name = f"_juli_capture_provider_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CaptureProviderError(path.name, "is not an importable Python module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — re-raised, named, never swallowed
        raise CaptureProviderError(path.name, exc) from exc
    return module


def discover_providers(directory: Path | str | None = None) -> tuple[str, ...]:
    """Import every provider module in ``directory`` and register what it finds.

    Defaults to this package's own directory — the path a Wave-2 slice drops its
    single module into. Returns the discovered names, sorted.

    Discovery is all-or-nothing: every module is validated before anything is
    registered, so a malformed or colliding module leaves the registry exactly
    as it found it rather than half-applied.
    """
    target = Path(directory) if directory is not None else Path(__file__).resolve().parent

    found: dict[str, CaptureProvider] = {}
    origin: dict[str, str] = {}
    for path in sorted(target.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = _load_module(path)
        name = getattr(module, PROVIDER_NAME_ATTR, None)
        if not isinstance(name, str) or not name:
            raise CaptureProviderError(
                path.name,
                f"defines no non-empty {PROVIDER_NAME_ATTR}; a provider module must "
                "name the run{} block it owns",
            )
        capture = getattr(module, CAPTURE_ATTR, None)
        if not callable(capture):
            raise CaptureProviderError(
                name,
                f"module {path.name} defines no callable {CAPTURE_ATTR}(context)",
            )
        if name in origin:
            raise CaptureProviderError(
                name,
                f"claimed by both {origin[name]} and {path.name}; two providers "
                "cannot own one run{} block",
            )
        found[name] = capture
        origin[name] = path.name

    for name, capture in found.items():
        register_provider(name, capture, replace=True)
    return tuple(sorted(found))


__all__ = [
    "CAPTURE_ATTR",
    "PROVIDER_NAME_ATTR",
    "CaptureContext",
    "CaptureProvider",
    "CaptureProviderError",
    "capture_run_block",
    "discover_providers",
    "provider_sandbox",
    "register_provider",
    "registered_providers",
    "unregister_provider",
]
