"""Budget gate -- issue #1039 (W2-A/P12-4, ADR-072 decision 6, gate 2 of 4),
parametrised per workflow by issue #1705 (W9-A/P-SHARED-5).

ADR-072 d.6: "Composed system prompt <= 3,000 tokens (tiktoken-measured...)".
That ceiling is declared exactly once in the whole repository, as
`composer.PROMPT_TOKEN_BUDGET_CEILING`, and imported here -- since #1705 it
lives next to the composition it constrains rather than in this gate, because
a workflow may register a different ceiling on its own prompt binding and the
default has to be somewhere both the binding and this gate can read it. This
module never re-asserts the number as a bare literal.

## Per workflow, against that workflow's own ceiling (#1705)

Each registered workflow is its own pytest parameter, measured at its own
pinned production version against `token_budget_ceiling(workflow_key)` -- the
value on its binding. A workflow whose prompt is over budget fails its own
case naming itself; it can never be averaged away by another workflow's
headroom, and a second workflow is covered the moment its binding is
registered, with no edit here.

## Single-call measurement -- not a sum of separately-measured parts

Per issue #1039's own second comment (superseding #1037's proxy, see
below): the gate measures `compose(workflow_key, version)`'s **rendered**
output in **one** `estimate_tokens()` call. It does not measure the raw
prose and the rendered playbook table separately and sum them --
`ceil(a/4) + ceil(b/4) >= ceil((a+b)/4)` always, so a summed measurement
would only ever *over*-estimate relative to a single-call measurement on
the concatenated text; the single-call number here is the tighter, more
accurate one, and it is the number this gate asserts against.

## Measured headroom (record, per issue #1039 acceptance criterion)

`RECORDED_COMPOSED_TOKEN_MEASUREMENT` below records, per workflow, the real
composed prompt's proxy token count at its pinned production version, so a
silent drift in either input is caught even while still under the ceiling.
Updated 2026-09-22 (#1705): Optimize Product's production pin moves from v3
to v4, whose composed bytes differ because the workflow-invariant prose of
Sections 1, 2, 3 and 8 now arrives from `prompts/shared/<section>/v1.md`.
v4 measures **2,944** proxy tokens against the 3,000 ceiling -- **56 tokens
of headroom**, six more than v3's 50, because v4's file header comment is
shorter than v3's and the extracted prose is otherwise near-identical.

## Retiring #1037's proxy ceiling (issue #1039 acceptance criterion)

#1037 shipped a **proxy** budget test (`RAW_PROMPT_TOKEN_CEILING = 2720` in
`tests/unit/test_agent_prompt_optimize_product_v1_contract.py`) measuring
the raw, un-rendered `v1.md` file alone, as a stand-in for the real gate --
`compose()` did not exist yet in that slice. That proxy is **retired** (the
raw-file ceiling test and constant were removed from that file, with a
docstring note pointing here) so the two ceilings can never drift apart and
disagree about the same file.

## The known ADR divergence -- recorded here, not adapted around silently

`tiktoken` is not a declared dependency of this backend: it appears in
neither `backend/pyproject.toml` nor `backend/constraints.txt` (verified
directly against both files by `TestTiktokenDependencyClosureAssumption`
below). Adding it would require a `constraints.txt` regeneration and risks
the confirmed CI failure mode where a package imports locally but is
missing from CI's exact pinned install closure.

**Decision: this gate measures against `estimate_tokens`
(`services/agent/sanitize/caps.py`)**, the repo's existing deterministic,
stdlib-only token estimate -- a conservative (rounds *up*, per that
module's docstring) character-count proxy already relied on by ADR-070's
per-tool-result ceiling. This is a real, intentional divergence from
ADR-072 d.6's literal "tiktoken-measured" wording:

- **What this gate actually proves:** the composed prompt's *proxy* token
  estimate is at or under the registered ceiling. The proxy over-counts
  (rounds up, ~4 characters/token), so a proxy pass is a safe, conservative
  upper bound.
- **What this gate does NOT prove:** the composed prompt's *true* GPT
  tokenizer count is at or under that ceiling under every encoding. An
  independent one-off `o200k_base` check (outside this test suite, not
  reproducible in CI, `tiktoken` never added to any dependency file) put
  the pre-trim prompt's real count at ~3,510 against a proxy estimate of
  ~3,656 -- the proxy over-counted there too, i.e. it failed safe for that
  encoding, but that is one data point under one encoding, not a
  universal property of the proxy across every possible tokenizer.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

import juli_backend.services.agent.playbooks as playbooks_module
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.prompts.composer import (
    PROMPT_TOKEN_BUDGET_CEILING,
    compose,
    production_version,
    registered_workflow_keys,
    token_budget_ceiling,
)
from juli_backend.services.agent.sanitize.caps import estimate_tokens

#: The real composed prompt's proxy token count at each workflow's pinned
#: production version (see module docstring "Measured headroom"). Asserted
#: directly below so a silent drift in the prose, a shared section or the
#: `Playbook` is caught even if it stays under the ceiling.
RECORDED_COMPOSED_TOKEN_MEASUREMENT: dict[str, int] = {
    "optimize_product_2": 2944,
}

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PYPROJECT_PATH = REPO_ROOT / "backend" / "pyproject.toml"
BACKEND_CONSTRAINTS_PATH = REPO_ROOT / "backend" / "constraints.txt"

_WORKFLOW_KEYS = list(registered_workflow_keys())


def _assert_composed_prompt_within_budget(composed: str, *, ceiling: int) -> int:
    """The gate's actual check: `compose()`'s output measured in a single
    `estimate_tokens()` call, asserted against `ceiling`. Returns the
    measured estimate so callers can also report/record it.

    Deliberately takes the already-composed string, never raw prose and a
    rendered playbook fragment as two separate arguments -- there must be
    no code path in this module that measures parts and sums them.
    """
    estimated = estimate_tokens(composed)
    assert estimated <= ceiling, (
        f"composed prompt estimates to {estimated} tokens (single-call "
        f"estimate_tokens measurement), over the {ceiling}-token ceiling "
        "(ADR-072 d.6)"
    )
    return estimated


# ---------------------------------------------------------------------------
# The real gate, once per registered workflow against its own ceiling.
# ---------------------------------------------------------------------------


def test_the_gate_has_a_case_for_every_registered_workflow():
    """A parametrisation that collected nothing would pass in silence."""
    assert _WORKFLOW_KEYS, "the budget gate collected no workflow cases"


@pytest.mark.parametrize("workflow_key", _WORKFLOW_KEYS)
def test_composed_prompt_is_at_or_under_the_token_budget_ceiling(workflow_key: str):
    composed = compose(workflow_key, production_version(workflow_key))
    _assert_composed_prompt_within_budget(composed, ceiling=token_budget_ceiling(workflow_key))


def test_the_ceiling_is_a_single_named_constant_not_a_bare_literal():
    assert isinstance(PROMPT_TOKEN_BUDGET_CEILING, int)
    assert PROMPT_TOKEN_BUDGET_CEILING == 3000


@pytest.mark.parametrize("workflow_key", _WORKFLOW_KEYS)
def test_every_registered_workflow_has_a_ceiling_at_or_under_the_adr_default(workflow_key: str):
    """A binding may narrow the ADR-072 d.6 budget for its own workflow; it
    may not quietly widen it. Raising the architectural ceiling is an ADR
    amendment, not a registry edit."""
    assert token_budget_ceiling(workflow_key) <= PROMPT_TOKEN_BUDGET_CEILING


@pytest.mark.parametrize("workflow_key", _WORKFLOW_KEYS)
def test_composed_prompt_token_estimate_matches_the_recorded_measurement(workflow_key: str):
    """Pins the real measured value (module docstring) so a silent drift in
    the prose, a shared section or the `Playbook`'s rendered size is caught
    even while still under budget -- not just a <= ceiling check."""
    assert workflow_key in RECORDED_COMPOSED_TOKEN_MEASUREMENT, (
        f"workflow_key {workflow_key!r} is registered but this gate records no "
        "measured token count for it; measure the composed prompt and record it "
        "here in the same reviewed commit that registers the binding"
    )
    recorded = RECORDED_COMPOSED_TOKEN_MEASUREMENT[workflow_key]
    estimated = estimate_tokens(compose(workflow_key, production_version(workflow_key)))
    assert estimated == recorded, (
        f"composed prompt for {workflow_key!r} now measures {estimated} tokens, but "
        f"this module records {recorded} as the real measurement -- if the prose, a "
        "shared section or the Playbook changed intentionally, update this recorded "
        "value and the headroom note in the module docstring together"
    )


def test_the_recorded_measurements_name_no_unregistered_workflow():
    """The reverse direction: a recorded number for a workflow that is no
    longer registered is a measurement nothing checks."""
    assert set(RECORDED_COMPOSED_TOKEN_MEASUREMENT) == set(_WORKFLOW_KEYS)


def test_optimize_products_recorded_headroom_is_the_documented_number():
    headroom = PROMPT_TOKEN_BUDGET_CEILING - RECORDED_COMPOSED_TOKEN_MEASUREMENT[WORKFLOW_KEY]
    assert headroom == 56


# ---------------------------------------------------------------------------
# Mutation proof: an over-budget *composition* is caught -- without editing
# the real, immutable prose files (ADR-072 d.4). A synthetic oversized
# Playbook is swapped into the playbook registry `compose()` really resolves
# through, so compose() runs its real rendering path end to end and this
# gate's check runs against real compose() output, not a hand-built string.
# ---------------------------------------------------------------------------


def _oversized_playbook() -> Playbook:
    """A Playbook with one step whose `intent` is padded far past any
    realistic prose length -- large enough that joining it into the real
    `{playbook}` slot alone pushes the composed total over the ceiling,
    without touching any prose file.
    """
    padded_step = dataclasses.replace(
        OPTIMIZE_PRODUCT_PLAYBOOK.steps[0],
        intent=OPTIMIZE_PRODUCT_PLAYBOOK.steps[0].intent + " x" * 4000,
    )
    return dataclasses.replace(
        OPTIMIZE_PRODUCT_PLAYBOOK,
        steps=(padded_step,) + OPTIMIZE_PRODUCT_PLAYBOOK.steps[1:],
    )


class TestSyntheticOverBudgetCompositionIsCaught:
    def test_an_oversized_playbook_composes_over_the_ceiling_and_is_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setitem(
            playbooks_module._PLAYBOOK_REGISTRY, WORKFLOW_KEY, _oversized_playbook()
        )

        # compose() itself still succeeds -- rendering a large intent string
        # is not a ComposeIntegrityError, it is a budget problem, which is
        # exactly the gap this gate exists to catch (compose() has no
        # opinion on prompt size; only this gate does).
        oversized_composed = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))
        assert estimate_tokens(oversized_composed) > token_budget_ceiling(WORKFLOW_KEY)

        with pytest.raises(AssertionError, match="over the 3000-token ceiling"):
            _assert_composed_prompt_within_budget(
                oversized_composed, ceiling=token_budget_ceiling(WORKFLOW_KEY)
            )

    def test_the_real_prose_files_are_untouched_by_the_oversized_playbook_mutation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The mutation above swaps the *Playbook*, never a prose file --
        confirms the released bytes never move during the mutation proof."""
        import juli_backend.services.agent.prompts.composer as compose_module

        prompt_dir = compose_module._binding_for(WORKFLOW_KEY).prompt_dir
        path = compose_module._prose_path(prompt_dir, production_version(WORKFLOW_KEY))
        before = path.read_bytes()

        monkeypatch.setitem(
            playbooks_module._PLAYBOOK_REGISTRY, WORKFLOW_KEY, _oversized_playbook()
        )
        compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))

        assert path.read_bytes() == before


def test_synthetic_over_budget_text_is_caught_by_the_same_estimator():
    # ~4 chars/token proxy (see caps.py) -- comfortably over the 3,000-token
    # ceiling at 4 * 3,001 characters, built deterministically (no
    # randomness, no wall-clock read).
    oversized_text = "x" * (4 * (PROMPT_TOKEN_BUDGET_CEILING + 1))
    with pytest.raises(AssertionError):
        _assert_composed_prompt_within_budget(oversized_text, ceiling=PROMPT_TOKEN_BUDGET_CEILING)


def test_synthetic_at_budget_text_is_not_caught_by_the_same_estimator():
    at_budget_text = "x" * (4 * PROMPT_TOKEN_BUDGET_CEILING)
    # Must not raise.
    _assert_composed_prompt_within_budget(at_budget_text, ceiling=PROMPT_TOKEN_BUDGET_CEILING)


# ---------------------------------------------------------------------------
# The ADR divergence is grounded in fact, not assertion: tiktoken really is
# absent from both dependency-closure sources, checked directly against the
# real files.
# ---------------------------------------------------------------------------


class TestTiktokenDependencyClosureAssumption:
    def test_tiktoken_is_not_declared_in_backend_pyproject_toml(self):
        text = BACKEND_PYPROJECT_PATH.read_text(encoding="utf-8")
        assert "tiktoken" not in text.lower()

    def test_tiktoken_is_not_pinned_in_backend_constraints_txt(self):
        text = BACKEND_CONSTRAINTS_PATH.read_text(encoding="utf-8")
        assert "tiktoken" not in text.lower()

    def test_estimator_source_module_imports_no_tiktoken_or_vendor_tokenizer(self):
        # AST-based (mirrors composer.py's own no-environ check in
        # test_agent_prompt_compose.py), over the real production module
        # estimate_tokens is imported from.
        caps_module_path = (
            REPO_ROOT
            / "backend"
            / "src"
            / "juli_backend"
            / "services"
            / "agent"
            / "sanitize"
            / "caps.py"
        )
        tree = ast.parse(caps_module_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        offending = {m for m in imported_modules if "tiktoken" in m.lower()}
        assert not offending, f"caps.py must not import a vendor tokenizer: {offending}"
