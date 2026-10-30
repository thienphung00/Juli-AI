"""Synthetic ``diagnose_optimize`` payloads and a recording products double (P76-5).

Shapes follow the bundled TikTok OAS for ``POST /product/202411/products/diagnose_optimize``
(``tts-openapi-guide/references/oas/paths/product.json``): the client returns the
envelope's ``data`` -- ``diagnoses[]`` of ``{field, diagnosis_results[{code, how_to_solve,
quality_tier}], suggestion}`` plus ``listing_quality``. No real shop, brand or product.
"""

from __future__ import annotations

import threading
from typing import Any

from juli_backend.integrations.tiktok import SandboxWriteResources

#: The draft still has issues: one title code, one image code (TikTok repeats a code
#: across entries sometimes; the parser deduplicates).
SCORED_DATA: dict[str, Any] = {
    "diagnoses": [
        {
            "field": "TITLE",
            "diagnosis_results": [
                {
                    "code": "SEO_DIAGNOSTIC_ITEM",
                    "how_to_solve": "Thêm từ khoá mô tả sản phẩm vào tiêu đề.",
                    "quality_tier": "FAIR",
                }
            ],
        },
        {
            "field": "IMAGE",
            "diagnosis_results": [
                {"code": "MAIN_IMG_NUMBER_LESS_THAN_FIVE", "how_to_solve": "Thêm ảnh."},
                {"code": "MAIN_IMG_NUMBER_LESS_THAN_FIVE", "how_to_solve": "Thêm ảnh."},
            ],
        },
    ],
    "listing_quality": {"current_tier": "FAIR", "remaining_recommendations": 2},
}

#: The draft clears everything TikTok checks.
CLEAN_DATA: dict[str, Any] = {
    "diagnoses": [
        {"field": "TITLE", "diagnosis_results": []},
        {"field": "DESCRIPTION", "diagnosis_results": []},
    ]
}

#: A 200 with no diagnosis block: not a reading, never "0 lỗi".
EMPTY_DATA: dict[str, Any] = {}

#: Free text where a code belongs is not echoed.
NOT_A_CODE_DATA: dict[str, Any] = {
    "diagnoses": [
        {"field": "TITLE", "diagnosis_results": [{"code": "please fix the title"}]},
    ]
}


class DraftScoringProducts:
    """``ProductsResource`` surface the listing write uses: ``diagnose_optimize`` + ``edit``.

    ``diagnose_result`` is returned, or raised when it is an exception; ``block`` makes
    ``diagnose_optimize`` wait (a slow TikTok) until :meth:`release`.
    """

    def __init__(self, diagnose_result: object = None, *, block: bool = False) -> None:
        self.diagnose_result = CLEAN_DATA if diagnose_result is None else diagnose_result
        self.diagnose_calls: list[dict[str, Any]] = []
        self.edit_calls: list[tuple[str, dict[str, Any]]] = []
        self.events: list[str] = []
        #: Own-session copies handed out for scoring, and how many were closed.
        self.copies: list[DraftScoringProducts] = []
        self.closed = 0
        self._gate = threading.Event()
        if not block:
            self._gate.set()

    def release(self) -> None:
        self._gate.set()

    def with_own_session(self) -> _OwnSessionCopy:
        """``ProductsResource.with_own_session``: scoring calls land on the copy."""
        self.copies.append(self)
        return _OwnSessionCopy(self)

    def diagnose_optimize(
        self,
        *,
        product_id: str,
        category_id: str,
        optimization_fields: list[str],
        title: str | None = None,
        description: str | None = None,
        main_images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.events.append("diagnose_optimize")
        self.diagnose_calls.append(
            {
                "product_id": product_id,
                "category_id": category_id,
                "optimization_fields": optimization_fields,
                "title": title,
                "description": description,
                "main_images": main_images,
            }
        )
        self._gate.wait(timeout=5)
        if isinstance(self.diagnose_result, BaseException):
            raise self.diagnose_result
        result: Any = self.diagnose_result
        return result

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.events.append("edit")
        self.edit_calls.append((product_id, body))
        return {}


class _OwnSessionCopy:
    """The own-session copy: forwards the scoring call, records ``close``."""

    def __init__(self, parent: DraftScoringProducts) -> None:
        self._parent = parent

    def diagnose_optimize(self, **kwargs: Any) -> dict[str, Any]:
        return self._parent.diagnose_optimize(**kwargs)

    def close(self) -> None:
        self._parent.closed += 1


def sandbox_resources(products: DraftScoringProducts) -> SandboxWriteResources:
    """A sandbox write bundle holding only ``products`` (the others are unused here)."""
    unused: Any = None
    bound: Any = products
    return SandboxWriteResources(
        inventory=unused, products=bound, fulfillment=unused, promotion=unused
    )
