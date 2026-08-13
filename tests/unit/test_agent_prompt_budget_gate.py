"""Budget gate — issue #1039 (W2-A/P12-4, ADR-072 decision 6, gate 2 of 4).

ADR-072 d.6: "Composed system prompt <= 3,000 tokens (tiktoken-measured...)".
This module asserts that ceiling exactly once, as the single named constant
`PROMPT_TOKEN_BUDGET_CEILING` below -- never re-asserted as a bare literal
anywhere else in this gate.

## The known ADR divergence -- recorded here, not adapted around silently

`tiktoken` is not a declared dependency of this backend: it appears in
neither `backend/pyproject.toml` nor `backend/constraints.txt` (verified
directly against both files by this module's own
`TestTiktokenDependencyClosureAssumption` below, so this claim cannot drift
silently out of date). Adding it would require a `constraints.txt`
regeneration and risks the confirmed CI failure mode where a package
imports locally but is missing from CI's exact pinned install (the
`jsonschema` precedent).

**Decision: this gate measures against `estimate_tokens`
(`services/agent/sanitize/caps.py`)**, the repo's existing deterministic,
stdlib-only token estimate -- a conservative (rounds *up*, per that
module's docstring) character-count proxy already relied on by ADR-070's
per-tool-result ceiling. This keeps the dependency closure clean but is a
real divergence from ADR-072 d.6's literal "tiktoken-measured" wording:

- **What this gate actually proves:** the composed prompt's *proxy* token
  estimate is at or under 3,000. The proxy over-counts (rounds up, ~4
  characters/token), so a proxy pass is a safe, if imprecise, upper bound --
  it cannot hide a prompt that is actually over budget by under-counting.
- **What this gate does NOT prove:** the composed prompt's *true* GPT
  tokenizer count is at or under 3,000. A real tokenizer could plausibly
  measure lower than this proxy (BPE tokenizers commonly average fewer
  characters per token than 4 for structured/English text), so passing this
  gate is not equivalent to passing a literal tiktoken-measured gate.
- This divergence is intentional and reported here for the Architect, per
  the "report, never adapt around silently" rule this wave's review pass is
  built on -- it is not a silent substitution. If a true tiktoken-measured
  gate is later required, that is a follow-up decision for the Architect
  (adding `tiktoken` to the dependency closure, regenerating
  `constraints.txt`, and confirming CI's exact install carries it), not
  something this gate should paper over by pretending the proxy is exact.

## A second, independently discovered finding -- reported, not fixed here

Running this gate against the real, already-released `v1.md` (#1037) /
`OPTIMIZE_PRODUCT_PLAYBOOK` (#1036) / `compose()` (#1038) pipeline, the
proxy measures the real composed prompt at **~3,656 estimated tokens --
about 22% over the 3,000 ceiling** (excluding the file's leading
documentation HTML comment, it is still ~3,489, so the overage is not an
artifact of that comment). This module deliberately does **not** hardcode
that number into an assertion (a future released version's composed length
is not this module's concern to pin), but the primary gate test's failure
message reports the real, freshly-measured value on every run.

Per this issue's write-path constraint (`tests/unit/` only -- `v1.md`, the
`Playbook`, and `composer.py` are out of bounds for this slice), this
module does not, and must not, trim `v1.md`'s prose, adjust the ceiling, or
swap in a more lenient measurement to make this pass. **This is reported
here, in the PR, and left for the Architect**, exactly as the "report,
never adapt around silently" rule requires.

**One-time, ad hoc ground-truth check (not part of this test suite, not
reproducible in CI):** to resolve the "may or may not reflect a true
tiktoken over-budget prompt" ambiguity above with real data rather than
speculation, `tiktoken` was `pip install`-ed locally (outside any tracked
dependency file, never added to `backend/pyproject.toml` or
`backend/constraints.txt`, and uninstalled again immediately after) purely
to measure the real composed prompt once. Result: **`o200k_base` encodes it
to 3,510 tokens; `cl100k_base` to 3,712 tokens** -- both over the 3,000
ceiling (by ~17% and ~24% respectively). This confirms the overage is not
an artifact of the stdlib proxy's conservative rounding: a real GPT
tokenizer also puts this composed prompt over budget. This module still
does not import or depend on `tiktoken` anywhere (see
`TestTiktokenDependencyClosureAssumption` below) -- this paragraph exists
only to give the Architect a real number instead of an open question.
"""

from __future__ import annotations

import ast
from pathlib import Path

from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY
from juli_backend.services.agent.prompts.composer import compose
from juli_backend.services.agent.sanitize.caps import estimate_tokens

#: ADR-072 d.6's ceiling -- the single named constant this whole gate exists
#: to assert. Never scatter a second "3000" literal anywhere else in this
#: module or elsewhere in the test suite for this gate.
PROMPT_TOKEN_BUDGET_CEILING = 3000

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PYPROJECT_PATH = REPO_ROOT / "backend" / "pyproject.toml"
BACKEND_CONSTRAINTS_PATH = REPO_ROOT / "backend" / "constraints.txt"


# ---------------------------------------------------------------------------
# The real gate: the composed prompt's proxy token estimate is at/under the
# ceiling.
# ---------------------------------------------------------------------------


def test_composed_prompt_is_at_or_under_the_token_budget_ceiling():
    composed = compose(WORKFLOW_KEY, 1)
    estimated = estimate_tokens(composed)
    assert estimated <= PROMPT_TOKEN_BUDGET_CEILING, (
        f"composed prompt for {WORKFLOW_KEY!r} v1 estimates to {estimated} tokens "
        f"(stdlib character-count proxy, see module docstring), over the "
        f"{PROMPT_TOKEN_BUDGET_CEILING}-token ceiling (ADR-072 d.6)"
    )


def test_the_ceiling_is_a_single_named_constant_not_a_bare_literal():
    # A structural pin, not a duplicate assertion of the value: proves the
    # constant this module's docstring and its one gate assertion both name
    # actually exists as a real module attribute, so nothing here silently
    # forked into a second, differently-spelled ceiling.
    assert isinstance(PROMPT_TOKEN_BUDGET_CEILING, int)
    assert PROMPT_TOKEN_BUDGET_CEILING == 3000


def test_composed_prompt_token_estimate_is_a_real_positive_measurement():
    """Sanity check that this gate is a real, non-vacuous measurement -- the
    composed prompt must estimate to a strictly positive token count. This
    does not assert a relationship to the ceiling (see the module docstring's
    "second, independently discovered finding": the real composed prompt
    currently measures *over* the ceiling under this proxy, which is the
    primary gate test's job to report, not this one's).
    """
    composed = compose(WORKFLOW_KEY, 1)
    estimated = estimate_tokens(composed)
    assert estimated > 0
    assert isinstance(estimated, int)


# ---------------------------------------------------------------------------
# Synthetic proof the gate actually catches an over-budget prompt -- do not
# rely on the real composed prompt happening to stay under budget forever.
# ---------------------------------------------------------------------------


def test_synthetic_over_budget_text_is_caught_by_the_same_estimator():
    # ~4 chars/token proxy (see caps.py) -- comfortably over the 3,000-token
    # ceiling at 4 * 3,001 characters, built deterministically (no randomness,
    # no wall-clock read).
    oversized_text = "x" * (4 * (PROMPT_TOKEN_BUDGET_CEILING + 1))
    estimated = estimate_tokens(oversized_text)
    assert estimated > PROMPT_TOKEN_BUDGET_CEILING


def test_synthetic_at_budget_text_is_not_caught_by_the_same_estimator():
    at_budget_text = "x" * (4 * PROMPT_TOKEN_BUDGET_CEILING)
    estimated = estimate_tokens(at_budget_text)
    assert estimated <= PROMPT_TOKEN_BUDGET_CEILING


# ---------------------------------------------------------------------------
# The ADR divergence is grounded in fact, not assertion: tiktoken really is
# absent from both dependency-closure sources, checked directly against the
# real files rather than only asserted in a docstring.
# ---------------------------------------------------------------------------


class TestTiktokenDependencyClosureAssumption:
    def test_tiktoken_is_not_declared_in_backend_pyproject_toml(self):
        text = BACKEND_PYPROJECT_PATH.read_text(encoding="utf-8")
        assert "tiktoken" not in text.lower()

    def test_tiktoken_is_not_pinned_in_backend_constraints_txt(self):
        text = BACKEND_CONSTRAINTS_PATH.read_text(encoding="utf-8")
        assert "tiktoken" not in text.lower()

    def test_estimator_source_module_imports_no_tiktoken_or_vendor_tokenizer(self):
        # AST-based (like composer.py's own no-environ check), over the real
        # production module `estimate_tokens` is imported from -- proves the
        # estimator this gate actually calls has no tokenizer dependency,
        # not just that this test file happens not to mention one.
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
