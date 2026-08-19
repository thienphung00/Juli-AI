"""Product-image inspection (issue #1208).

Covers the two halves of the defect this replaced: a playbook step that could
never succeed, and a tool error that escaped the runner. Plus the property the
whole design rests on — the output is an *edit intent*, so image generation can
consume it later without a schema change.
"""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.services.agent.tools.product import (
    INSPECT_PRODUCT_IMAGE_SPEC,
    InspectProductImageInput,
    ProductToolContext,
    handle_inspect_product_image,
)
from juli_backend.services.agent.vision import (
    SEVERITIES,
    VERDICTS,
    normalize_inspection,
)


class _Products:
    def __init__(self, detail: dict[str, Any]) -> None:
        self._detail = detail
        self.calls: list[str] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        self.calls.append(product_id)
        return self._detail


class _Resources:
    def __init__(self, detail: dict[str, Any]) -> None:
        self.products = _Products(detail)


def _detail(**over: Any) -> dict[str, Any]:
    base = {
        "title": "Chai Xịt Thơm Miệng 14mL",
        "description": "Giữ hơi thở thơm mát",
        "main_images": [{"urls": ["https://cdn.example/hero.jpg?sig=abc"], "width": 1200}],
    }
    base.update(over)
    return base


class TestItIsAReadToolThatCanActuallySucceed:
    """`upload_product_image` was WRITE/AUTO and required staged bytes nothing
    ever staged, so the model could call it and it always raised. Its
    replacement must be a READ that works with what the run already has."""

    def test_spec_is_read_and_auto(self):
        assert INSPECT_PRODUCT_IMAGE_SPEC.classification.value == "read"
        assert INSPECT_PRODUCT_IMAGE_SPEC.policy.value == "auto"

    def test_takes_no_parameters(self):
        assert InspectProductImageInput.model_fields == {}

    def test_inspects_the_bound_product_and_returns_findings(self):
        seen: dict[str, Any] = {}

        def inspector(*, image_url: str, title: str, description: str):
            seen.update(image_url=image_url, title=title, description=description)
            return {
                "verdict": "partial",
                "confidence": "high",
                "findings": [
                    {
                        "aspect": "promotional overlay",
                        "observed": "two voucher banners dominate the frame",
                        "conflicts_with": None,
                        "severity": "medium",
                    }
                ],
                "recommended_edits": [
                    {
                        "intent": "declutter",
                        "subject": "voucher banners",
                        "instruction": "crop to the bottle on a clean background",
                        "priority": "high",
                    }
                ],
            }

        resources = _Resources(_detail())
        out = handle_inspect_product_image(
            resources,
            ProductToolContext(product_id="P1", image_inspector=inspector),
            InspectProductImageInput(),
        )

        assert out.inspected is True
        assert out.verdict == "partial"
        assert out.recommended_edits[0].intent == "declutter"
        # The image URL reached the inspector but never the output.
        assert seen["image_url"].startswith("https://cdn.example/")
        assert "cdn.example" not in out.model_dump_json()


class TestMissingInputsDegradeRatherThanRaise:
    """#1208's second half: the old tool raised into the Celery task, the run
    was never written terminal, and the reaper mislabelled it `worker_lost`. A
    missing inspection must be a missing finding, not a dead run."""

    def test_no_inspector_configured_reports_not_inspected(self):
        out = handle_inspect_product_image(
            _Resources(_detail()), ProductToolContext(product_id="P1"), InspectProductImageInput()
        )
        assert out.inspected is False
        assert out.findings == []

    def test_product_with_no_images_reports_not_inspected(self):
        out = handle_inspect_product_image(
            _Resources(_detail(main_images=[])),
            ProductToolContext(product_id="P1", image_inspector=lambda **_: {}),
            InspectProductImageInput(),
        )
        assert out.inspected is False

    def test_image_entry_without_urls_reports_not_inspected(self):
        out = handle_inspect_product_image(
            _Resources(_detail(main_images=[{"width": 800}])),
            ProductToolContext(product_id="P1", image_inspector=lambda **_: {}),
            InspectProductImageInput(),
        )
        assert out.inspected is False


class TestTheUrlIsNeverCached:
    """TikTok CDN URLs are pre-signed and expire. The handler must re-read the
    product each call rather than reuse a URL threaded forward, or a later run
    silently 403s."""

    def test_each_call_refetches_the_product(self):
        resources = _Resources(_detail())
        ctx = ProductToolContext(product_id="P1", image_inspector=lambda **_: {})
        handle_inspect_product_image(resources, ctx, InspectProductImageInput())
        handle_inspect_product_image(resources, ctx, InspectProductImageInput())
        assert resources.products.calls == ["P1", "P1"]


class TestOutputIsAnEditIntentThatCanEvolve:
    """The design's load-bearing property: today's output is already the shape
    a future image generator consumes, so adding generation needs no schema
    migration and no prompt rewrite."""

    def test_edits_carry_an_instruction_and_a_priority(self):
        result = normalize_inspection(
            {
                "verdict": "mismatched",
                "recommended_edits": [
                    {
                        "intent": "replace",
                        "subject": "hero photo",
                        "instruction": "show the mint variant named in the title",
                        "priority": "high",
                    }
                ],
            }
        )
        edit = result["recommended_edits"][0]
        assert set(edit) == {"intent", "subject", "instruction", "priority"}
        assert edit["instruction"]

    def test_none_intent_edits_are_dropped(self):
        """'none' means no change wanted -- carrying it forward would make a
        future generator act on a no-op."""
        result = normalize_inspection(
            {"recommended_edits": [{"intent": "none", "instruction": "nothing"}]}
        )
        assert result["recommended_edits"] == []


class TestModelOutputIsNeverTrusted:
    """The image is seller-controlled, so the inspector's reply is untrusted
    input shaped by us -- not a contract the model gets to define."""

    @pytest.mark.parametrize("garbage", [None, "not json", 42, [], {"verdict": "banana"}])
    def test_unexpected_shapes_degrade_to_a_safe_default(self, garbage):
        result = normalize_inspection(garbage)
        assert result["verdict"] in VERDICTS
        assert result["confidence"] in SEVERITIES
        assert result["findings"] == []

    def test_long_strings_are_clipped_and_lists_capped(self):
        result = normalize_inspection(
            {
                "verdict": "partial",
                "findings": [{"aspect": "a" * 500, "observed": "b" * 5000, "severity": "high"}]
                * 40,
            }
        )
        assert len(result["findings"]) <= 5
        assert len(result["findings"][0]["observed"]) <= 240
        assert len(result["findings"][0]["aspect"]) <= 60

    def test_severity_and_verdict_are_forced_into_the_fixed_vocabulary(self):
        result = normalize_inspection(
            {"verdict": "TOTALLY WRONG", "findings": [{"severity": "catastrophic"}]}
        )
        assert result["verdict"] == "partial"
        assert result["findings"][0]["severity"] == "low"
