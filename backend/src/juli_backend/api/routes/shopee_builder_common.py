"""What the Demo (seller) and Ops routes of the P92 builder share: request bodies, the mapping from
the services' refusals to HTTP errors, and one handler per endpoint (the routes only add auth,
tenant scope, audit and the seller's view)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services import shop_inputs
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_builder import catalogue, drafts, keywords, llm, specs
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_recommendations import manual

SORT_PATTERN = "^(" + "|".join(catalogue.SORTS) + ")$"
ItemPath = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\s:]+$")]


class EvaluateBody(BaseModel):
    """1-4 versions of mixed kinds (``kind`` picks the model, see ``shopee_builder.specs``)."""

    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    as_of: date | None = None


class CompareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(
        min_length=specs.MIN_VERSIONS_COMPARE, max_length=specs.MAX_VERSIONS
    )
    as_of: date | None = None


class ChooseBody(BaseModel):
    """ "Chọn": the chosen version becomes a manual card, the others are its versions."""

    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    chosen: int = Field(default=0, ge=0, lt=specs.MAX_VERSIONS)
    primary: bool = False
    #: must be true to save a version that breaks a floor or the spend cap (P91 warning dialog)
    acknowledge_breaches: bool = False
    as_of: date | None = None


class TitleDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: ItemPath
    keywords: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=drafts.MAX_KEYWORDS
    )
    count: int = Field(default=3, ge=drafts.MIN_DRAFTS, le=drafts.MAX_DRAFTS)
    as_of: date | None = None


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: ItemPath
    count: int = Field(default=3, ge=drafts.MIN_DRAFTS, le=drafts.MAX_DRAFTS)
    as_of: date | None = None


class ExclusionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(pattern="^(ngung_ban|qua_tang|phan_phoi|khac)$")
    note: str | None = Field(default=None, max_length=500)


def detail(code: str, message: str, **more: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **more}


def no_data() -> HTTPException:
    return HTTPException(409, detail=detail(manual.ERROR_NO_DATA, "shop has no Shopee numbers"))


def not_found(item_id: str) -> HTTPException:
    return HTTPException(
        404, detail=detail("product_not_found", "Không có sản phẩm này", item_id=item_id)
    )


def refused(exc: ProposalError) -> HTTPException:
    return HTTPException(exc.status, detail=detail(exc.code, exc.detail or exc.code))


def breach_refusal(exc: manual.BreachNotAcknowledged) -> HTTPException:
    return HTTPException(422, detail=detail(exc.code, exc.detail, breaches=exc.breaches))


def llm_off(exc: llm.LLMUnavailable) -> HTTPException:
    return HTTPException(
        503, detail=detail("llm_off", llm.OFF_MESSAGE, reason=exc.reason, hint=exc.detail or None)
    )


def no_valid_draft(exc: drafts.NoValidDraft) -> HTTPException:
    return HTTPException(
        422,
        detail=detail(
            "llm_no_valid_draft",
            "Mô hình trả lời nhưng không có bản nào qua kiểm tra",
            dropped=exc.dropped,
        ),
    )


# ----------------------------------------------------------------------------- handlers


async def h_products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    as_of: date | None,
    q: str | None,
    include_excluded: bool,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    try:
        return await builder.products(
            session,
            shop_id,
            as_of=as_of,
            query=q,
            include_excluded=include_excluded,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except builder.NoShopeeData:
        raise no_data() from None


async def h_variations(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date | None, now: datetime
) -> dict[str, Any]:
    try:
        return await builder.product_variations(session, shop_id, item_id, as_of=as_of, now=now)
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(item_id) from None


async def h_co_purchase(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date | None
) -> dict[str, Any]:
    try:
        return await builder.co_purchase(session, shop_id, item_id, as_of=as_of)
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(item_id) from None


async def h_keywords(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date | None, now: datetime
) -> dict[str, Any]:
    try:
        env, facts = await builder.draft_facts(session, shop_id, item_id, as_of=as_of, now=now)
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(item_id) from None
    return await keywords.keyword_table(
        session, shop_id, item_id, title=facts.title, as_of=env.as_of
    )


async def h_campaigns(
    session: AsyncSession, shop_id: uuid.UUID, *, as_of: date | None, now: datetime
) -> dict[str, Any]:
    try:
        return await builder.ads_campaigns(session, shop_id, as_of=as_of, now=now)
    except builder.NoShopeeData:
        raise no_data() from None


async def h_evaluate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: EvaluateBody | CompareBody,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        return await builder.evaluate_versions(
            session, shop_id, body.versions, as_of=body.as_of, now=now
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except ProposalError as exc:
        raise refused(exc) from None


async def h_choose(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: ChooseBody,
    actor: manual.Actor,
    *,
    now: datetime,
) -> dict[str, Any]:
    if body.chosen >= len(body.versions):
        raise HTTPException(
            422, detail=detail(manual.ERROR_BAD_VARIANT, "chosen must index one of the versions")
        )
    try:
        return await builder.choose(
            session,
            shop_id,
            body.versions,
            body.chosen,
            primary=body.primary,
            acknowledge_breaches=body.acknowledge_breaches,
            actor=actor,
            as_of=body.as_of,
            now=now,
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except manual.BreachNotAcknowledged as exc:
        raise breach_refusal(exc) from None
    except ProposalError as exc:
        raise refused(exc) from None


async def h_title_drafts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: TitleDraftBody,
    client: llm.LLMClient,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        _, facts = await builder.draft_facts(
            session, shop_id, body.item_id, as_of=body.as_of, now=now
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(body.item_id) from None
    try:
        out = await drafts.draft_titles(client, facts, body.keywords, count=body.count)
    except llm.LLMUnavailable as exc:
        raise llm_off(exc) from None
    except drafts.NoValidDraft as exc:
        raise no_valid_draft(exc) from None
    return {"item_id": body.item_id, "current_title": facts.title, "model": client.model, **out}


async def h_cover_drafts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: DraftBody,
    client: llm.LLMClient,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        _, facts = await builder.draft_facts(
            session, shop_id, body.item_id, as_of=body.as_of, now=now
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(body.item_id) from None
    try:
        out = await drafts.draft_overlays(client, facts, count=body.count)
    except llm.LLMUnavailable as exc:
        raise llm_off(exc) from None
    except drafts.NoValidDraft as exc:
        raise no_valid_draft(exc) from None
    return {"item_id": body.item_id, "model": client.model, **out}


async def h_description_drafts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: DraftBody,
    client: llm.LLMClient,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        _, facts = await builder.draft_facts(
            session, shop_id, body.item_id, as_of=body.as_of, now=now
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(body.item_id) from None
    try:
        out = await drafts.draft_descriptions(client, facts, count=body.count)
    except llm.LLMUnavailable as exc:
        raise llm_off(exc) from None
    except drafts.NoValidDraft as exc:
        raise no_valid_draft(exc) from None
    return {"item_id": body.item_id, "model": client.model, **out}


async def get_client(session: AsyncSession, shop_id: uuid.UUID) -> llm.LLMClient:
    """The shop's gated model client, or the 503 "LLM tắt" answer."""
    try:
        return await llm.gated_client(session, shop_id)
    except llm.LLMUnavailable as exc:
        raise llm_off(exc) from None


# -------------------------------------------------------------------------- exclusions


def exclusion_error(exc: shop_inputs.ExclusionError) -> HTTPException:
    return HTTPException(422, detail=detail(exc.code, str(exc)))


async def h_exclusions(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    rows = await shop_inputs.list_exclusions(session, shop_id)
    return {
        "excluded": [r.json() for r in rows],
        "count": len(rows),
        "reasons": [
            {"key": k, "label": v} for k, v in shop_inputs.exclusions.REASON_LABELS.items()
        ],
    }


__all__ = [
    "SORT_PATTERN",
    "ChooseBody",
    "CompareBody",
    "DraftBody",
    "EvaluateBody",
    "ExclusionBody",
    "TitleDraftBody",
    "get_client",
    "h_campaigns",
    "h_choose",
    "h_co_purchase",
    "h_cover_drafts",
    "h_description_drafts",
    "h_evaluate",
    "h_exclusions",
    "h_keywords",
    "h_products",
    "h_title_drafts",
    "h_variations",
]
