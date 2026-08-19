"""Budget gate -- issue #1039 (W2-A/P12-4, ADR-072 decision 6, gate 2 of 4).

ADR-072 d.6: "Composed system prompt <= 3,000 tokens (tiktoken-measured...)".
This module asserts that ceiling exactly once, as the single named
constant `PROMPT_TOKEN_BUDGET_CEILING` below -- never re-asserted as a bare
literal anywhere else in this gate.

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

`compose("optimize_product_2", 1)` measures **2,967** proxy tokens against
this module's 3,000-token ceiling -- raw `v1.md` measures 2,687, so the
`{playbook}` slot's rendered content costs 280 tokens once joined with the
real `OPTIMIZE_PRODUCT_PLAYBOOK`. That leaves **28 tokens of headroom**:
tight, but `v1.md` is immutable post-release (ADR-072 d.4) and this
`Playbook` is a frozen, reviewed artifact (#1036), so no further margin is
expected to be needed. This number is independently confirmed by two prior
agents (per the #1039 issue thread) and reproduced by this module's own
`test_composed_prompt_token_estimate_matches_the_recorded_measurement`.

## Retiring #1037's proxy ceiling (issue #1039 acceptance criterion)

#1037 shipped a **proxy** budget test (`RAW_PROMPT_TOKEN_CEILING = 2720` in
`tests/unit/test_agent_prompt_optimize_product_v1_contract.py`) measuring
the raw, un-rendered `v1.md` file alone, as a stand-in for the real gate --
`compose()` did not exist yet in that slice. That proxy is **retired** in
this same change (the raw-file ceiling test and constant are removed from
that file, with a docstring note pointing here) so the two ceilings can
never drift apart and disagree about the same file: this module is now the
single source of truth for the ADR-072 d.6 budget.

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
  estimate is at or under 3,000. The proxy over-counts (rounds up, ~4
  characters/token), so a proxy pass is a safe, conservative upper bound.
- **What this gate does NOT prove:** the composed prompt's *true* GPT
  tokenizer count is at or under 3,000 under every encoding. An
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

import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.prompts.composer import compose
from juli_backend.services.agent.sanitize.caps import estimate_tokens

#: ADR-072 d.6's ceiling -- the single named constant this whole gate exists
#: to assert. Never scatter a second "3000" literal anywhere else in this
#: module or elsewhere in the test suite for this gate.
PROMPT_TOKEN_BUDGET_CEILING = 3000

#: Updated 2026-08-19 (#1208): 2967 -> 2972 when Optimize Product's step 4/4.5
#: changed from `upload_product_image` to `inspect_product_image`, whose intent
#: line is longer. Headroom is now **28 tokens** against a 3000 ceiling -- the
#: next prose change to v1.md or the Playbook is very likely to breach it, so
#: raising the ceiling (or shortening a step intent) is the next decision, not
#: an emergency today.
#:
#: Recorded measurement (see module docstring "Measured headroom") -- the
#: real composed prompt's proxy token count against the real, released
#: v1.md + OPTIMIZE_PRODUCT_PLAYBOOK pair, independently confirmed twice
#: per the #1039 issue thread. Asserted directly below so a silent drift
#: in either input is caught even if it happens to stay under the ceiling.
RECORDED_COMPOSED_TOKEN_MEASUREMENT = 2972
RECORDED_HEADROOM = PROMPT_TOKEN_BUDGET_CEILING - RECORDED_COMPOSED_TOKEN_MEASUREMENT

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PYPROJECT_PATH = REPO_ROOT / "backend" / "pyproject.toml"
BACKEND_CONSTRAINTS_PATH = REPO_ROOT / "backend" / "constraints.txt"


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
# The real gate: the composed prompt's single-call proxy estimate is at/
# under the ceiling.
# ---------------------------------------------------------------------------


def test_composed_prompt_is_at_or_under_the_token_budget_ceiling():
    composed = compose(WORKFLOW_KEY, 1)
    _assert_composed_prompt_within_budget(composed, ceiling=PROMPT_TOKEN_BUDGET_CEILING)


def test_the_ceiling_is_a_single_named_constant_not_a_bare_literal():
    assert isinstance(PROMPT_TOKEN_BUDGET_CEILING, int)
    assert PROMPT_TOKEN_BUDGET_CEILING == 3000


def test_composed_prompt_token_estimate_matches_the_recorded_measurement():
    """Pins the real measured value (module docstring) so a silent drift in
    v1.md's prose or the Playbook's rendered size is caught even while
    still under budget -- not just a >= 0 sanity check."""
    composed = compose(WORKFLOW_KEY, 1)
    estimated = estimate_tokens(composed)
    assert estimated == RECORDED_COMPOSED_TOKEN_MEASUREMENT, (
        f"composed prompt now measures {estimated} tokens, but this module "
        f"records {RECORDED_COMPOSED_TOKEN_MEASUREMENT} as the real, "
        "independently-confirmed measurement -- if v1.md or the Playbook "
        "changed intentionally, update this recorded value and the "
        "headroom note in the module docstring together"
    )
    assert RECORDED_HEADROOM == 28


# ---------------------------------------------------------------------------
# Mutation proof: an over-budget *composition* is caught -- without editing
# the real, immutable v1.md (ADR-072 d.4). A synthetic oversized Playbook is
# swapped in via the same monkeypatch seam test_agent_prompt_compose.py
# already uses (`_WORKFLOW_BINDINGS`), so compose() runs its real rendering
# path end to end and this gate's check runs against real compose() output,
# not a hand-built string standing in for one.
# ---------------------------------------------------------------------------


def _oversized_playbook() -> Playbook:
    """A Playbook with one step whose `intent` is padded far past any
    realistic prose length -- large enough that joining it into v1.md's
    real `{playbook}` slot alone pushes the composed total over the
    3,000-token ceiling, without touching v1.md itself.
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
        binding = compose_module._binding_for(WORKFLOW_KEY)
        monkeypatch.setitem(
            compose_module._WORKFLOW_BINDINGS,
            WORKFLOW_KEY,
            compose_module._WorkflowPromptBinding(
                prompt_dir=binding.prompt_dir, playbook=_oversized_playbook()
            ),
        )

        # compose() itself still succeeds -- rendering a large intent string
        # is not a ComposeIntegrityError, it is a budget problem, which is
        # exactly the gap this gate exists to catch (compose() has no
        # opinion on prompt size; only this gate does).
        oversized_composed = compose(WORKFLOW_KEY, 1)
        assert estimate_tokens(oversized_composed) > PROMPT_TOKEN_BUDGET_CEILING

        with pytest.raises(AssertionError, match="over the 3000-token ceiling"):
            _assert_composed_prompt_within_budget(
                oversized_composed, ceiling=PROMPT_TOKEN_BUDGET_CEILING
            )

    def test_the_real_v1_md_file_is_untouched_by_the_oversized_playbook_mutation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The mutation above swaps the *Playbook*, never the prose file --
        confirms v1.md's real bytes never move during the mutation proof."""
        binding = compose_module._binding_for(WORKFLOW_KEY)
        v1_path = compose_module._prose_path(binding.prompt_dir, 1)
        before = v1_path.read_bytes()

        monkeypatch.setitem(
            compose_module._WORKFLOW_BINDINGS,
            WORKFLOW_KEY,
            compose_module._WorkflowPromptBinding(
                prompt_dir=binding.prompt_dir, playbook=_oversized_playbook()
            ),
        )
        compose(WORKFLOW_KEY, 1)

        after = v1_path.read_bytes()
        assert before == after


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
