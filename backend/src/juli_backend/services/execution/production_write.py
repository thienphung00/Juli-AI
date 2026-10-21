"""A seller's own-shop write resources, behind every ADR-085 gate (fast track P61-B, D71.2).

``sandbox_guard.py`` builds the sandbox merchant's write resources; this module
is its production twin. It builds nothing by itself deciding: the resolver
(``production_write_resolver.resolve_write_capability``) decides, per mutation,
whether a write may reach the seller's shop at all, and only its production
marker -- issued after the global flag, this shop's enable row, the per-mutation
authorization, the RLS boot check, the red-team attestation and the kill switch
all passed, and after the authorization was consumed and the allowed attempt
audited -- may be turned into resources here.

The credential is the shop's OWN (``resolve_write_credential_for_shop``), and it
is checked again here against the shop the capability was issued for: a
credential that belongs to any other shop is refused before a client exists.
The client carries ``ProductionWriteGuard``: the listing edit, the cover upload
and the reads around them, nothing else (no price, D13).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import is_production_write_enabled
from juli_backend.core.security import resolve_write_credential_for_shop
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionWriteClientFactory,
    ProductionWriteResources,
    refuse_reviewer_production_write,
)
from juli_backend.models.models import ProductionWriteShop

#: The ``capability`` value of the resolver's production marker.
PRODUCTION_WRITE_CAPABILITY = "production_write"


class ProductionWriteBindingError(RuntimeError):
    """The capability, the shop and the credential do not all name the same shop."""


def is_production_capability(value: object) -> bool:
    """Whether ``value`` is the resolver's production marker (every gate passed)."""
    return isinstance(value, Mapping) and value.get("capability") == PRODUCTION_WRITE_CAPABILITY


async def is_shop_production_write_enabled(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    """Whether the owner turned production writes on for this shop (``production_write_shops``)."""
    found = await session.execute(
        select(ProductionWriteShop.shop_id).where(ProductionWriteShop.shop_id == shop_id)
    )
    return found.scalar_one_or_none() is not None


async def production_write_possible(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    """Whether this shop's writes are routed to its own shop rather than the sandbox.

    The routing half of the gate set only (global flag AND the shop's enable
    row). The remaining gates are refusals the resolver raises per mutation; a
    caller uses this to refuse a request that must never reach production
    (a price write, a product create) before an authorization is consumed.
    """
    if not is_production_write_enabled():
        return False
    return await is_shop_production_write_enabled(session, shop_id)


async def load_production_write_resources(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    capability: Mapping[str, Any],
    app_key: str,
    app_secret: str,
    factory: ProductionWriteClientFactory | None = None,
) -> ProductionWriteResources:
    """The guarded own-shop write resources for ``shop_id``, from the resolver's marker."""
    # P64 (D73 Q6 layer 2): never for a partner reviewer request, before any credential read.
    refuse_reviewer_production_write("load_production_write_resources")
    if not is_production_capability(capability):
        raise ProductionWriteBindingError(
            "Production write resources need the resolver's production capability"
        )
    if str(capability.get("shop_id")) != str(shop_id):
        raise ProductionWriteBindingError(
            f"Production capability was issued for shop {capability.get('shop_id')}, "
            f"not for shop {shop_id}"
        )
    credential = await resolve_write_credential_for_shop(session, shop_id)
    if credential.shop_id != shop_id or not credential.merchant_authorization_id:
        raise ProductionWriteBindingError(
            f"The write credential resolved for shop {shop_id} does not belong to it"
        )
    config = ClientFactoryConfig(
        app_key=app_key,
        app_secret=app_secret,
        access_token=credential.access_token,
        merchant_auth_id=credential.merchant_authorization_id,
        shop_cipher=credential.shop_cipher,
        credential_capability=credential.capability,
    )
    return (factory or ProductionWriteClientFactory()).create_resources(config)


#: The listing fields a production listing edit can change, and how their value
#: reads off a ``products.get_details`` payload. The same fields and rules as the
#: agent's ``services/agent/runner/write_capture.py`` (``LISTING_OPERATION``),
#: restated here because ``services/execution`` must not import
#: ``services/agent`` (``agent`` already depends on ``execution``; the reverse
#: edge is a dependency cycle). ``tests/unit/test_p61b_production_write.py`` pins
#: the two equal.
LISTING_WRITE_TOOL_NAME = "update_product_listing"
LISTING_FIELDS: tuple[str, ...] = ("title", "description", "main_images")
AFTER_SOURCE_READ_BACK = "read_back"
AFTER_SOURCE_INTENDED = "intended"


def _image_uris(raw: Mapping[str, Any]) -> list[str]:
    uris: list[str] = []
    for image in raw.get("main_images") or []:
        if isinstance(image, Mapping):
            if image.get("uri"):
                uris.append(str(image["uri"]))
        elif image:
            uris.append(str(image))
    return uris


def listing_field_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The current value of each listing field, from a detail read."""
    return {
        "title": raw.get("title"),
        "description": raw.get("description"),
        "main_images": _image_uris(raw),
    }


def _same(left: Any, right: Any) -> bool:
    def norm(value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    return bool(norm(left) == norm(right))


def diff_listing_write(
    *, before: Mapping[str, Any], after: Mapping[str, Any], intended: Mapping[str, Any]
) -> list[tuple[str, Any, Any, str]]:
    """``(field, before, after, after_source)`` for every listing field the edit
    changed: the read-back first, the value Juli sent when the read-back still
    shows the old one (a listing edit under TikTok review)."""
    old_values, new_values = listing_field_values(before), listing_field_values(after)
    sent_values = dict(intended)
    if "main_images" in sent_values:
        sent_values["main_images"] = _image_uris(sent_values)
    writes: list[tuple[str, Any, Any, str]] = []
    for field in LISTING_FIELDS:
        old, new = old_values.get(field), new_values.get(field)
        if not _same(old, new):
            writes.append((field, old, new, AFTER_SOURCE_READ_BACK))
            continue
        sent = sent_values.get(field)
        if sent is not None and not _same(old, sent):
            writes.append((field, old, sent, AFTER_SOURCE_INTENDED))
    return writes


async def record_listing_write_values(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID,
    tool_call_id: str,
    tiktok_product_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    intended: Mapping[str, Any],
) -> int:
    """Persist the before/after values of one production listing edit (P8-C's
    ``run_write_values``), in the caller's transaction. Returns the rows written.
    Recorded under the agent's listing operation name, so a "Hoàn tác" reads one
    shape whichever path wrote."""
    from juli_backend.models.run_changes import RunWriteValue

    writes = diff_listing_write(before=before, after=after, intended=intended)
    for field, old, new, source in writes:
        session.add(
            RunWriteValue(
                shop_id=shop_id,
                workflow_run_id=workflow_run_id,
                tool_call_id=tool_call_id,
                tool_name=LISTING_WRITE_TOOL_NAME,
                tiktok_product_id=tiktok_product_id,
                field=field,
                before_value=old,
                after_value=new,
                after_source=source,
            )
        )
    await session.flush()
    return len(writes)


__all__ = [
    "PRODUCTION_WRITE_CAPABILITY",
    "ProductionWriteBindingError",
    "is_production_capability",
    "is_shop_production_write_enabled",
    "load_production_write_resources",
    "production_write_possible",
    "diff_listing_write",
    "listing_field_values",
    "record_listing_write_values",
]
