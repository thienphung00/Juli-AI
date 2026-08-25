"""Deterministic prompt composer -- issue #1038 (W2-A/P12-3, ADR-072 d.2, d.4).

`compose(workflow_key, version)` is the one place the typed `Playbook`
artifact (#1036) and the version-addressed prose file (#1037) join: it loads
`vN.md` by path, renders the `Playbook` into the prose's single `{playbook}`
slot, and returns the composed system prompt as a plain string. No build
step -- ADR-068 decision 2's "compiled" is satisfied by this static,
reviewed repo artifact; `compose()` is pure string manipulation over files
already in the repo, with no I/O beyond reading the prose file and no
network access. Its signature is a contract (issue #1038): it later doubles
as the eval-harness entry point.

Two namespaces look alike but are not the same thing (ADR-072 decision 2,
also documented on `playbooks/optimize_product.py`):

- `workflow_key` -- the system-wide key (`WORKFLOW_TOOL_CATALOG`, #983's
  cross-validation, the outcome vocabulary). Currently `"optimize_product_2"`.
- the *prompt directory* name -- `services/agent/prompts/<dir>/vN.md`.
  Currently `"optimize_product"`.

`compose()` maps the former to the latter **explicitly**, via
`_WORKFLOW_BINDINGS` below -- never by deriving one spelling from the other,
and never by falling back to a default directory. An unknown `workflow_key`
raises `UnknownWorkflowKeyError` naming it.

`prompt_version(workflow_key, version)` follows the *prompt-directory*
namespace (e.g. `"optimize_product.v1"`, ADR-072 d.4's example) --
deliberately not the `workflow_key` namespace, for the same reason the two
are mapped explicitly rather than derived.

The production version pin (`PRODUCTION_PROMPT_VERSION` below) is a plain
code constant, deliberately not env-configurable in v1 (ADR-072 d.4: "what
runs is what was reviewed"). This module performs no environment-variable
lookups of any kind -- it does not import the `os` module at all --
`TestNoEnvironmentConfiguration` in `tests/unit/test_agent_prompt_compose.py`
enforces that both by an AST/source check (mirroring
`test_agent_tool_registry.py`'s no-marketplace-imports check) and by a
behavioral check that setting an arbitrary environment variable cannot
change which version composes.

Scope note: `prompt_version`/`prompt_sha256` are the two P-CS fields ADR-072
d.4 says a run *records* on `workflow_runs` -- that table does not exist yet
(P-CS is deferred; W3-A's write path). This module only **specifies and
exposes** the two fields as plain functions; it adds no columns, no
migration, and no persistence anywhere.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK

_PROMPTS_ROOT = Path(__file__).resolve().parent

_TEMPLATE_SLOT = "{playbook}"
_LEFTOVER_SLOT_PATTERN = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


class UnknownWorkflowKeyError(ValueError):
    """Raised when a `workflow_key` has no registered prompt binding --
    names the offending key and the known keys. Never silently falls back
    to a default prompt directory."""


class UnreleasedPromptVersionError(ValueError):
    """Raised when the requested version's prose file does not exist on
    disk -- names the `workflow_key` and `version` requested. Never
    silently falls back to a different (e.g. v1) version."""


class ComposeIntegrityError(ValueError):
    """Raised when composition itself would produce output that violates
    the contract -- a prose file missing (or duplicating) its `{playbook}`
    slot, or a leftover unrendered template slot in the composed output.
    Indicates a bug in this module or a malformed prose file, never a
    normal caller input error."""


@dataclass(frozen=True)
class _WorkflowPromptBinding:
    """Explicit `workflow_key` -> (prompt directory, `Playbook`) binding.

    Deliberately explicit (ADR-072 decision 2) rather than derived from
    `workflow_key` by string transformation -- the two namespaces (the
    system-wide workflow key and the prompt directory name) look alike for
    Optimize Product today but are not guaranteed to stay in lockstep for
    future workflows.
    """

    prompt_dir: str
    playbook: Playbook


# The one explicit, visible, tested workflow_key -> prompt-directory mapping
# (ADR-072 decision 2). Add a new entry here for each workflow that lands in
# P13 -- never rename a prompt directory to match a workflow_key, and never
# derive one namespace from the other.
_WORKFLOW_BINDINGS: dict[str, _WorkflowPromptBinding] = {
    OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key: _WorkflowPromptBinding(
        prompt_dir="optimize_product",
        playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
    ),
}

# The production prompt version pin (ADR-072 d.4) -- a code constant,
# deliberately not env-configurable in v1 ("what runs is what was
# reviewed"). Bump a value here, in a reviewed commit, to promote a new
# released version to production; never redirect this via configuration.
PRODUCTION_PROMPT_VERSION: dict[str, int] = {
    OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key: 2,
}


def _binding_for(workflow_key: str) -> _WorkflowPromptBinding:
    try:
        return _WORKFLOW_BINDINGS[workflow_key]
    except KeyError as exc:
        known = sorted(_WORKFLOW_BINDINGS)
        raise UnknownWorkflowKeyError(
            f"no prompt binding registered for workflow_key {workflow_key!r}; "
            f"known workflow_keys: {known}"
        ) from exc


def production_version(workflow_key: str) -> int:
    """The pinned production prompt version for `workflow_key` -- a code
    constant (`PRODUCTION_PROMPT_VERSION` above), never read from the
    environment. Raises `UnknownWorkflowKeyError` naming the key if no
    production pin is registered for it.
    """
    _binding_for(workflow_key)  # fail loudly on the same terms as compose()
    try:
        return PRODUCTION_PROMPT_VERSION[workflow_key]
    except KeyError as exc:
        raise UnknownWorkflowKeyError(
            f"no production prompt version pinned for workflow_key {workflow_key!r}"
        ) from exc


def _prose_path(prompt_dir: str, version: int) -> Path:
    return _PROMPTS_ROOT / prompt_dir / f"v{version}.md"


def _load_prose(workflow_key: str, prompt_dir: str, version: int) -> str:
    path = _prose_path(prompt_dir, version)
    if not path.is_file():
        raise UnreleasedPromptVersionError(
            f"workflow_key {workflow_key!r} has no released prompt version {version} "
            f"(expected prose file at {path})"
        )
    return path.read_text(encoding="utf-8")


def _render_step_row(step: PlaybookStep) -> str:
    tools = ", ".join(f"`{name}`" for name in step.tools)
    policy = step.policy.value.upper()
    return f"| {step.step_id} | {step.intent} | {tools} | {policy} |"


def _render_playbook(playbook: Playbook) -> str:
    """Render the `Playbook`'s steps into the prose's `{playbook}` slot.

    Deterministic and pure: iterates `playbook.steps` in artifact order (a
    tuple, never a set/dict whose iteration order could vary across
    processes), and emits a plain markdown table with no curly braces
    anywhere in a row, so a rendered playbook can never itself be mistaken
    for a leftover template slot by `_LEFTOVER_SLOT_PATTERN`.
    """
    header = "| Step | Intent | Tools | Policy |\n|------|--------|-------|--------|"
    rows = [header] + [_render_step_row(step) for step in playbook.steps]
    return "\n".join(rows)


def compose(workflow_key: str, version: int) -> str:
    """Load `vN.md` for `workflow_key`, render its `Playbook` into the
    prose's single `{playbook}` slot, and return the composed system
    prompt.

    Deterministic: a pure function of the prose file's bytes on disk and
    the `Playbook` artifact's data -- both fixed for a given
    `(workflow_key, version)` pair -- so the same inputs produce
    byte-identical output, including across separate processes.

    Raises `UnknownWorkflowKeyError` if `workflow_key` has no registered
    binding, `UnreleasedPromptVersionError` if `version`'s prose file does
    not exist, and `ComposeIntegrityError` if the prose file's `{playbook}`
    slot is missing/duplicated or a template slot survives rendering. None
    of these silently fall back to a default.
    """
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"version must be a positive int, got {version!r}")

    binding = _binding_for(workflow_key)
    prose = _load_prose(workflow_key, binding.prompt_dir, version)

    slot_count = prose.count(_TEMPLATE_SLOT)
    if slot_count != 1:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} must contain "
            f"exactly one {_TEMPLATE_SLOT!r} slot, found {slot_count}"
        )

    rendered_playbook = _render_playbook(binding.playbook)
    composed = prose.replace(_TEMPLATE_SLOT, rendered_playbook, 1)

    leftover = _LEFTOVER_SLOT_PATTERN.findall(composed)
    if leftover:
        raise ComposeIntegrityError(
            f"composed prompt for workflow_key {workflow_key!r} version {version} still "
            f"contains unrendered template slot(s): {leftover}"
        )

    return composed


def prompt_version(workflow_key: str, version: int) -> str:
    """The version-addressed prompt identifier (ADR-072 d.4), e.g.
    `"optimize_product.v1"` -- follows the *prompt-directory* namespace,
    not the `workflow_key` namespace (see module docstring). Raises
    `UnknownWorkflowKeyError` naming the key if it is not registered.
    """
    binding = _binding_for(workflow_key)
    return f"{binding.prompt_dir}.v{version}"


def prompt_sha256(workflow_key: str, version: int) -> str:
    """SHA-256 hex digest of `compose(workflow_key, version)`'s output --
    the join key for eval scores and the audit answer to "which
    instructions produced this run" (ADR-072 d.4). Recomputed from
    `compose()` on every call rather than cached, so the hash can never
    drift from the composed bytes it claims to describe.
    """
    composed = compose(workflow_key, version)
    return hashlib.sha256(composed.encode("utf-8")).hexdigest()
