"""Partial progress is honest outcome data, not a failure (#1383).

ADR-088 introduced `required_steps_unfulfilled` as the signal for a run that
narrated instead of acting even when forced. The first implementation produced
it whenever `required_steps_completed(...)` was False — which is True for two
very different runs:

- one that took **no** qualifying action at all (the defect);
- one that acted on **some** required steps and honestly declined the rest.

ADR-073 decision 2 protects the second by name: "a final_response with only
one, or neither, confirmed is honest outcome data for the execution-quality
metric, not a synthetic failure." Gate #1226 walk run
`675bb11e-3630-4aa4-8950-47837ce9d313` did the listing change and deliberately
declined the price change because the product's total inventory is 0 — a
correct judgement — and was recorded `status=failed`.

The second half of this module covers the opposite miss found while fixing the
first: a compare-before-write refusal was **counted** as a completed required
step, crediting a run for work the guard declined.
"""

from __future__ import annotations

from juli_backend.services.agent.runner.termination import (
    completed_required_steps,
    required_steps_completed,
)

REQUIRED = ("update_product_listing", "update_product_price")


def _tool(name: str, content: dict) -> dict:
    return {"role": "tool", "tool_name": name, "content": content}


def _ok(name: str) -> dict:
    return _tool(name, {"status": "ok"})


class TestPartialProgressIsDistinguishable:
    def test_one_of_two_required_steps_is_partial_not_zero(self):
        """The run gate #1226 actually produced: listing done, price declined."""
        window = [_ok("update_product_listing")]

        assert completed_required_steps(window, REQUIRED) == {"update_product_listing"}
        assert not required_steps_completed(window, REQUIRED), (
            "still not 'did the job' — the partial fact stays recorded honestly"
        )

    def test_no_required_step_is_genuinely_empty(self):
        """The ADR-088 defect signal must survive this change."""
        window = [_ok("get_product_information"), _ok("get_seo_keywords")]

        assert completed_required_steps(window, REQUIRED) == frozenset()
        assert not required_steps_completed(window, REQUIRED)

    def test_both_required_steps_is_complete(self):
        window = [_ok("update_product_listing"), _ok("update_product_price")]

        assert completed_required_steps(window, REQUIRED) == set(REQUIRED)
        assert required_steps_completed(window, REQUIRED)


class TestWorkThatNeverHappenedIsNotProgress:
    """All three payloads name the tool without performing the operation."""

    def test_a_compare_before_write_refusal_is_not_progress(self):
        """#1383's second defect. `{"conflict": True, ...}` carries neither an
        `error` nor a `confirmation` key, so it slipped past both existing
        skips and was counted as completed — crediting the run for a write the
        guard refused."""
        window = [
            _tool(
                "update_product_listing",
                {"conflict": True, "current_values": {"title": "Nồi lẩu điện mini 1.5L"}},
            )
        ]

        assert completed_required_steps(window, REQUIRED) == frozenset(), (
            "a refused write is not a completed required step"
        )

    def test_an_error_envelope_is_not_progress(self):
        window = [_tool("update_product_listing", {"error": {"code": "refused"}})]
        assert completed_required_steps(window, REQUIRED) == frozenset()

    def test_a_declined_confirmation_is_not_progress(self):
        window = [_tool("update_product_listing", {"confirmation": {"decision": "declined"}})]
        assert completed_required_steps(window, REQUIRED) == frozenset()

    def test_a_refused_write_plus_a_real_one_counts_only_the_real_one(self):
        """Non-vacuity: the skip must be selective, not blanket."""
        window = [
            _tool("update_product_listing", {"conflict": True, "current_values": {}}),
            _ok("update_product_price"),
        ]

        assert completed_required_steps(window, REQUIRED) == {"update_product_price"}
