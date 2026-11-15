"""What the Demo (seller) and Ops routes of the P92 builder share: request bodies, the mapping from
the services' refusals to HTTP errors, and one handler per endpoint (the routes only add auth,
tenant scope, audit and the seller's view)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services import shop_inputs
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_builder import catalogue, drafts, keywords, llm, specs
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_recommendations import manual

SORT_PATTERN = "^(" + "|".join(catalogue.SORTS) + ")$"
ItemPath = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\s:]+$")]


class _BuilderVersions(BaseModel):
    """The builder takes no spec of a removed kind (Ẩn / đưa lại listing, Listing combo mới)."""

    @field_validator("versions", check_fields=False)
    @classmethod
    def _no_removed_kinds(cls, versions: list[specs.VersionSpec]) -> list[specs.VersionSpec]:
        for v in versions:
            if v.kind in specs.REMOVED_BUILDER_KINDS:
                raise ValueError(f"the builder no longer offers {v.kind}")
        return versions


class EvaluateBody(_BuilderVersions):
    """1-4 versions of mixed kinds (``kind`` picks the model, see ``shopee_builder.specs``)."""

    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    as_of: date | None = None


class CompareBody(_BuilderVersions):
    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(
        min_length=specs.MIN_VERSIONS_COMPARE, max_length=specs.MAX_VERSIONS
    )
    as_of: date | None = None


class ChooseBody(_BuilderVersions):
    """ "Chọn": the chosen version becomes a manual card, the others are its versions."""

    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    chosen: int = Field(default=0, ge=0, lt=specs.MAX_VERSIONS)
    primary: bool = False
    #: must be true to save a version that breaks a floor or the spend cap (P91 warning dialog)
    acknowledge_breaches: bool = False
    as_of: date | None = None


class GroupBody(_BuilderVersions):
    """ "Chạy cùng nhau": the ticked versions (indexes into ``versions``) become one group of the
    plan with one period (at least 3 days)."""

    model_config = ConfigDict(extra="forbid")
    versions: list[specs.VersionSpec] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    members: list[int] = Field(min_length=1, max_length=specs.MAX_VERSIONS)
    days: int = Field(default=7, ge=1, le=1000)
    start: date | None = None
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
    #: P100 S2-D: on the sample shop, False serves the pre-written titles and True runs the one
    #: live draft a product allows. Every other shop ignores it (every call is live).
    regenerate: bool = False


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


async def h_group(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: GroupBody,
    actor: manual.Actor,
    *,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations import plans

    try:
        return await builder.run_together(
            session,
            shop_id,
            body.versions,
            body.members,
            days=body.days,
            start=body.start,
            acknowledge_breaches=body.acknowledge_breaches,
            actor=actor,
            as_of=body.as_of,
            now=now,
            audience=audience,
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except manual.BreachNotAcknowledged as exc:
        raise breach_refusal(exc) from None
    except plans.PlanBreachNotAcknowledged as exc:
        raise HTTPException(
            422, detail=detail(exc.code, exc.detail, breaches=exc.breaches)
        ) from None
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


async def h_sample_title_drafts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    body: TitleDraftBody,
    *,
    user_id: uuid.UUID | None,
    now: datetime,
    refuse_quota: Callable[[], Awaitable[HTTPException]],
) -> dict[str, Any]:
    """P100 S2-D: Tiêu đề drafts on the sample shop -- the seeded titles first (no LLM call),
    then at most ``SAMPLE_LIVE_TITLES_PER_PRODUCT`` live draft per product; after that
    ``refuse_quota()`` (403 ``sample_llm_quota``). Every title passes ``drafts.screen_titles``."""
    from juli_backend.services.sample_shop import content_specs as cs

    try:
        _, facts = await builder.draft_facts(
            session, shop_id, body.item_id, as_of=body.as_of, now=now
        )
    except builder.NoShopeeData:
        raise no_data() from None
    except LookupError:
        raise not_found(body.item_id) from None
    kws = [k.strip() for k in body.keywords if k.strip()][: drafts.MAX_KEYWORDS]
    seeded = await cs.latest_title(session, shop_id, body.item_id, source=cs.SOURCE_SEEDED)
    live = await cs.latest_title(session, shop_id, body.item_id, source=cs.SOURCE_LLM)
    if not body.regenerate and (seeded is not None or live is not None):
        # Owner 2026-11-15 (option A): the pre-written titles stay, and the AI draft, once made,
        # sits beside them -- a live draft never replaces the seeded set.
        used = await cs.live_titles_used(session, shop_id, body.item_id)
        return _sample_titles(
            body.item_id,
            facts,
            kws,
            seeded,
            live,
            live_left=cs.SAMPLE_LIVE_TITLES_PER_PRODUCT - used,
        )
    await lock_product(session, shop_id, body.item_id)
    if await cs.live_titles_used(session, shop_id, body.item_id) >= (
        cs.SAMPLE_LIVE_TITLES_PER_PRODUCT
    ):
        raise await refuse_quota()
    client = await get_client(session, shop_id)
    try:
        out = await drafts.draft_titles(client, facts, kws, count=body.count)
    except llm.LLMUnavailable as exc:
        raise llm_off(exc) from None
    except drafts.NoValidDraft as exc:
        raise no_valid_draft(exc) from None
    row = cs.llm_title_row(
        shop_id,
        body.item_id,
        current_title=facts.title,
        keywords=kws,
        drafts=out["drafts"],
        model=client.model,
        user_id=user_id,
        now=now,
    )
    session.add(row)
    await session.flush()
    return _sample_titles(body.item_id, facts, kws, seeded, row, live_left=0)


def _sample_titles(
    item_id: str,
    facts: Any,
    kws: list[str],
    seeded: Any,
    live: Any,
    *,
    live_left: int,
) -> dict[str, Any]:
    """The sample shop's titles: the seeded set, then the live AI set (each screened on its own,
    each draft tagged with its ``source``). ``source`` of the answer is the newest set's."""
    shown: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for row, tag in ((seeded, "seeded"), (live, "llm")):
        if row is None:
            continue
        items = [
            {"title": c.get("title", ""), "note": c.get("note", "")}
            for c in ((row.spec or {}).get("candidates") or (row.spec or {}).get("drafts") or [])
        ]
        passed, lost = drafts.screen_titles(items, facts, kws)
        seen = {d["title"] for d in shown}
        shown.extend({**d, "source": tag} for d in passed if d["title"] not in seen)
        dropped.extend(lost)
    try:
        out = drafts.title_result(shown, dropped)
    except drafts.NoValidDraft as exc:
        raise no_valid_draft(exc) from None
    newest = live if live is not None else seeded
    return {
        "item_id": item_id,
        "current_title": facts.title,
        "model": (newest.spec or {}).get("model"),
        "source": "llm" if live is not None else "seeded",
        "live_left": max(0, live_left),
        **out,
    }


async def lock_product(session: AsyncSession, shop_id: uuid.UUID, item_id: str) -> None:
    """Serialise the quota check per (shop, product) for this transaction (Postgres only)."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"sample_title:{shop_id}:{item_id}"},
    )


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
    "h_group",
    "h_keywords",
    "h_products",
    "h_title_drafts",
    "h_variations",
]
