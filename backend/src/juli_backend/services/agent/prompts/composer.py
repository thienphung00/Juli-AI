"""Deterministic prompt composer -- issue #1038 (W2-A/P12-3, ADR-072 d.2, d.4),
extended by issue #1705 (W9-A/P-SHARED-5) with shared sections and a prompt
binding registry with one entry per workflow.

`compose(workflow_key, version)` is the one place three repo artifacts join:
the version-addressed workflow prose file (`<prompt_dir>/vN.md`, #1037), the
workflow-invariant **shared sections** (`shared/<name>/vN.md`, #1705), and the
typed `Playbook` the runtime actually executes (#1036, resolved through
#1702's playbook registry). It returns the composed system prompt as a plain
string. No build step -- ADR-068 decision 2's "compiled" is satisfied by these
static, reviewed repo artifacts; `compose()` is pure string manipulation over
files already in the repo, with no I/O beyond reading those files and no
network access. Its signature is a contract (issue #1038): it later doubles as
the eval-harness entry point.

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

## The prompt binding registry (#1705)

`_WORKFLOW_BINDINGS` is ONE explicit dict literal, `workflow_key ->
_WorkflowPromptBinding`, holding everything about a workflow that is a
property of its *prompt*: which directory its prose lives in, which released
version production is pinned to (ADR-072 d.4), and the token ceiling its
composition must stay under (d.6). Registering a second workflow is one
import plus one entry -- no discovery, no import-time self-registration, no
entry-point scan. That is deliberately the same shape as #1702's playbook
registry (`services/agent/playbooks/__init__.py`), and for the same reason:
the registered set stays readable in one place and diffable in one line, and
import order cannot change it.

It is a **separate** map from that playbook registry, and stays separate
(ADR-072 d.2). The playbook is the safety surface -- frozen data a prompt
optimizer may never mutate -- and it is keyed in the `workflow_key`
namespace; the prompt binding is the tuning surface's address, and it is
keyed by `workflow_key` onto the *prompt-directory* namespace. Merging them
would be exactly the derivation d.2 forbids. What #1705 does remove is the
*duplication*: the binding no longer carries its own `Playbook` reference.
`compose()` resolves the playbook through `playbooks.get_playbook()`, so the
playbook the model is shown and the playbook the executor enforces are the
same object by construction, which is what "one artifact, three consumers"
(d.2) means.

## Shared sections (#1705, ADR-072 d.1's extraction trigger)

ADR-072 d.1 shipped Optimize Product as a monolithic prose file with an
explicit trigger: "when a second workflow's prompt lands, sections shared by
both are extracted so that no behavior rule ever lives in more than one
file." `SHARED_SECTIONS` below is that extraction. Each shared section is
version-addressed by path exactly like a workflow prose file
(`shared/<name>/vN.md`) and referenced from a prose file by a
`{shared_<name>_v<N>}` slot, so a prose version names the exact bytes it
composes from and ADR-072 d.4's immutability survives extraction: editing a
released shared section is as forbidden as editing a released `vN.md`, and
the per-workflow golden snapshots catch it. A change adds
`shared/<name>/v<N+1>.md` and a new prose version that points at it.

A prose file either uses **no** shared section (the pre-extraction released
versions -- `optimize_product/v1.md` through `v3.md`, still on disk and still
composing byte-identically) or **exactly one version of every** registered
shared section. A file that references some but not all raises
`ComposeIntegrityError` naming the missing ones: the whole point of the
extraction is that a workflow cannot quietly opt out of a behaviour rule.

The production version pin lives on each binding (`production_version` below)
and is a plain code constant, deliberately not env-configurable in v1
(ADR-072 d.4: "what runs is what was reviewed"). This module performs no
environment-variable lookups of any kind -- it does not import the `os`
module at all -- `TestNoEnvironmentConfiguration` in
`tests/unit/test_agent_prompt_compose.py` enforces that both by an AST/source
check (mirroring `test_agent_tool_registry.py`'s no-marketplace-imports
check) and by a behavioral check that setting an arbitrary environment
variable cannot change which version composes.

Scope note: `prompt_version`/`prompt_sha256` are the two P-CS fields ADR-072
d.4 says a run *records* on `workflow_runs`. This module only **specifies and
exposes** the two fields as plain functions; it adds no columns, no
migration, and no persistence anywhere.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from juli_backend.services.agent import playbooks as playbooks_registry
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY

_PROMPTS_ROOT = Path(__file__).resolve().parent

_SHARED_ROOT_DIRNAME = "shared"

_TEMPLATE_SLOT = "{playbook}"
_LEFTOVER_SLOT_PATTERN = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

#: Any `{shared_...}`-shaped slot, registered or not. Matched deliberately
#: wider than the registered set so an unregistered slot is reported by name
#: instead of surviving as a generic "leftover slot".
_SHARED_SLOT_PATTERN = re.compile(r"\{shared_[a-z0-9_]+\}")

#: ADR-072 d.6's ceiling: "Composed system prompt <= 3,000 tokens". Declared
#: here, next to the composition it constrains, rather than in the gate that
#: asserts it -- a workflow that needs a different ceiling overrides it on its
#: own binding, and `tests/unit/test_agent_prompt_budget_gate.py` imports this
#: name rather than restating the number.
PROMPT_TOKEN_BUDGET_CEILING = 3000


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
    slot, a prose file that references some but not all of the registered
    shared sections, an unregistered `{shared_*}` slot, a shared section
    file that is missing or itself carries a template slot, or a leftover
    unrendered template slot in the composed output. Indicates a bug in
    this module or a malformed prose file, never a normal caller input
    error."""


@dataclass(frozen=True)
class _SharedSection:
    """One workflow-invariant prompt section, version-addressed by path.

    `name` is both the slot's middle word and its directory name; `version`
    is the released revision, exactly as for a workflow prose file. Nothing
    derives one namespace from another here: the slot spelling and the path
    spelling are two renderings of the same two fields.
    """

    name: str
    version: int

    @property
    def slot(self) -> str:
        """The literal slot text a prose file writes to pull this section
        in, e.g. `"{shared_source_roles_v1}"`."""
        return f"{{shared_{self.name}_v{self.version}}}"

    @property
    def relative_path(self) -> Path:
        return Path(_SHARED_ROOT_DIRNAME) / self.name / f"v{self.version}.md"


#: The registered shared sections (#1705). ONE explicit literal, one line per
#: section, no discovery -- the shape #1702's playbook registry set. The four
#: here are the ones ADR-072 d.1 names as workflow-invariant: role, mandate,
#: source-role rules and prohibitions.
#:
#: Adding a *revision* of a section means adding its `vN+1` entry here AND
#: moving every workflow prose file to a new version pointing at it; the
#: per-workflow snapshot goldens fail loudly until both happen, which is how
#: ADR-072 d.4's immutability is enforced across a shared file.
SHARED_SECTIONS: tuple[_SharedSection, ...] = (
    _SharedSection(name="role", version=1),
    _SharedSection(name="mandate", version=1),
    _SharedSection(name="source_roles", version=1),
    _SharedSection(name="prohibitions", version=1),
)

#: Every registered shared section's name, in registry order. A prose file
#: that uses shared sections at all must reference exactly one version of
#: each of these.
SHARED_SECTION_NAMES: tuple[str, ...] = tuple(section.name for section in SHARED_SECTIONS)

_SHARED_SECTIONS_BY_SLOT: dict[str, _SharedSection] = {
    section.slot: section for section in SHARED_SECTIONS
}


@dataclass(frozen=True)
class _WorkflowPromptBinding:
    """One workflow's prompt registration -- everything about a workflow that
    is a property of its prompt rather than of its playbook.

    - `prompt_dir` -- the prompt-directory name. Deliberately explicit
      (ADR-072 decision 2) rather than derived from `workflow_key` by string
      transformation: the two namespaces look alike for Optimize Product
      today but are not guaranteed to stay in lockstep.
    - `production_version` -- the released version production composes
      (ADR-072 d.4). A code constant, never environment-configurable; bump it
      in a reviewed commit to promote a new version.
    - `token_budget_ceiling` -- the composed-prompt token ceiling this
      workflow must stay under, defaulting to ADR-072 d.6's 3,000. Per
      workflow because a workflow with a longer playbook or a larger worked
      example is a different budget question from Optimize Product's.

    Deliberately does NOT carry a `Playbook`: `compose()` resolves that
    through #1702's playbook registry so the prompt and the executor cannot
    be shown two different playbooks for one workflow (module docstring).
    """

    prompt_dir: str
    production_version: int
    token_budget_ceiling: int = PROMPT_TOKEN_BUDGET_CEILING


#: The one explicit, visible, tested `workflow_key` -> prompt binding map
#: (ADR-072 decision 2). Add one entry here for each workflow that lands --
#: never rename a prompt directory to match a workflow_key, and never derive
#: one namespace from the other.
_WORKFLOW_BINDINGS: dict[str, _WorkflowPromptBinding] = {
    WORKFLOW_KEY: _WorkflowPromptBinding(
        prompt_dir="optimize_product",
        production_version=4,
    ),
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


def registered_workflow_keys() -> tuple[str, ...]:
    """Every `workflow_key` with a registered prompt binding, sorted.

    Read at call time, never snapshotted at import, so a test that registers
    a second binding is driving the same map production reads. This is what
    the three per-workflow gates (snapshot, budget, playbook consistency)
    parametrise over.
    """
    return tuple(sorted(_WORKFLOW_BINDINGS))


def production_version(workflow_key: str) -> int:
    """The pinned production prompt version for `workflow_key` -- a code
    constant on its binding, never read from the environment. Raises
    `UnknownWorkflowKeyError` naming the key if it is not registered.
    """
    return _binding_for(workflow_key).production_version


def token_budget_ceiling(workflow_key: str) -> int:
    """The composed-prompt token ceiling registered for `workflow_key`
    (ADR-072 d.6, defaulting to `PROMPT_TOKEN_BUDGET_CEILING`). Raises
    `UnknownWorkflowKeyError` naming the key if it is not registered.
    """
    return _binding_for(workflow_key).token_budget_ceiling


def released_versions(workflow_key: str) -> tuple[int, ...]:
    """Every released prose version for `workflow_key`, ascending.

    Derived from the prose files actually on disk rather than from a
    hand-kept list, so a version added without its golden snapshot fails the
    snapshot gate instead of being silently unguarded. Raises
    `UnknownWorkflowKeyError` naming the key if it is not registered.
    """
    binding = _binding_for(workflow_key)
    directory = _PROMPTS_ROOT / binding.prompt_dir
    versions = []
    for path in directory.glob("v*.md"):
        suffix = path.stem[1:]
        if suffix.isdigit():
            versions.append(int(suffix))
    return tuple(sorted(versions))


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


def shared_section_text(name: str, version: int) -> str:
    """The prose of one shared section, with trailing newlines stripped.

    Stripped so a section's own file can end with a newline (as every text
    file should) without that newline becoming a blank line in every
    composed prompt that pulls it in -- the substitution is into a slot that
    already sits on its own line. Deterministic: a pure function of the
    file's bytes.

    Raises `ComposeIntegrityError` if the file is absent or itself contains a
    template slot: shared sections are leaves, never nested compositions, so
    a composed prompt's provenance is always exactly two files deep.
    """
    path = _PROMPTS_ROOT / _SHARED_ROOT_DIRNAME / name / f"v{version}.md"
    if not path.is_file():
        raise ComposeIntegrityError(
            f"shared prompt section {name!r} version {version} is registered but its "
            f"file is missing (expected {path})"
        )
    text = path.read_text(encoding="utf-8")
    nested = _LEFTOVER_SLOT_PATTERN.findall(text)
    if nested:
        raise ComposeIntegrityError(
            f"shared prompt section {name!r} version {version} contains template "
            f"slot(s) {nested}; shared sections are leaves and are never themselves "
            "composed from other files"
        )
    return text.rstrip("\n")


def _render_shared_sections(workflow_key: str, version: int, prose: str) -> str:
    """Replace every `{shared_<name>_v<N>}` slot in `prose` with its section.

    A prose file that references no shared section is returned unchanged --
    that is the pre-extraction released versions (module docstring), not an
    error. A file that references any shared section must reference exactly
    one version of every registered section; anything else raises
    `ComposeIntegrityError` naming what is wrong.
    """
    found = _SHARED_SLOT_PATTERN.findall(prose)
    if not found:
        return prose

    unregistered = sorted(set(found) - set(_SHARED_SECTIONS_BY_SLOT))
    if unregistered:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} references "
            f"unregistered shared section slot(s) {unregistered}; registered slots are "
            f"{sorted(_SHARED_SECTIONS_BY_SLOT)}"
        )

    duplicated = sorted({slot for slot in found if found.count(slot) > 1})
    if duplicated:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} repeats "
            f"shared section slot(s) {duplicated}; each shared section is composed in "
            "exactly once"
        )

    referenced_names = [_SHARED_SECTIONS_BY_SLOT[slot].name for slot in found]
    repeated_names = sorted({name for name in referenced_names if referenced_names.count(name) > 1})
    if repeated_names:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} references "
            f"more than one version of shared section(s) {repeated_names}"
        )

    missing = [name for name in SHARED_SECTION_NAMES if name not in referenced_names]
    if missing:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} composes from "
            f"shared sections but omits {missing}; a prompt uses every registered shared "
            f"section or none of them (registered sections: {list(SHARED_SECTION_NAMES)})"
        )

    rendered = prose
    for slot in found:
        section = _SHARED_SECTIONS_BY_SLOT[slot]
        rendered = rendered.replace(slot, shared_section_text(section.name, section.version), 1)
    return rendered


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
    """Load `vN.md` for `workflow_key`, splice in the shared sections it
    names, render the workflow's registered `Playbook` into the prose's
    single `{playbook}` slot, and return the composed system prompt.

    Deterministic: a pure function of the prose file's bytes, the shared
    section files' bytes, and the `Playbook` artifact's data -- all fixed for
    a given `(workflow_key, version)` pair -- so the same inputs produce
    byte-identical output, including across separate processes.

    Raises `UnknownWorkflowKeyError` if `workflow_key` has no registered
    prompt binding, `UnregisteredWorkflowError` (from the playbook registry)
    if it has a binding but no registered `Playbook`,
    `UnreleasedPromptVersionError` if `version`'s prose file does not exist,
    and `ComposeIntegrityError` if the prose file's `{playbook}` slot is
    missing/duplicated, its shared section references are incomplete or
    unregistered, or a template slot survives rendering. None of these
    silently fall back to a default.
    """
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"version must be a positive int, got {version!r}")

    binding = _binding_for(workflow_key)
    prose = _load_prose(workflow_key, binding.prompt_dir, version)
    composed = _render_shared_sections(workflow_key, version, prose)

    slot_count = composed.count(_TEMPLATE_SLOT)
    if slot_count != 1:
        raise ComposeIntegrityError(
            f"prompt file for workflow_key {workflow_key!r} version {version} must contain "
            f"exactly one {_TEMPLATE_SLOT!r} slot, found {slot_count}"
        )

    rendered_playbook = _render_playbook(playbooks_registry.get_playbook(workflow_key))
    composed = composed.replace(_TEMPLATE_SLOT, rendered_playbook, 1)

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
