"""Manual refresh pipeline: optional poll → scoring → persist → emission budget — ADR-021, #1289.

As of #1289, the pipeline applies the emission/surfacing budget (emission_budget.py)
immediately after persisting scoring results, on the same refresh run — matching the
continuous-trigger path (cdp_speed.decision_rules_scoring_stage). This ensures
manually-refreshed shops' cards surface properly in the public Demo API
(GET /v1/demo/decisions, which gates on surfaced_at IS NOT NULL).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.emission_budget import apply_emission_budget
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.tiktok.credential_binding import make_binding_verifier

logger = logging.getLogger(__name__)


def _poll_env_ready() -> dict[str, str] | None:
    """Return poll env vars when Fujiwa poll prerequisites are configured."""
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


async def maybe_poll_tiktok_data(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Run Fujiwa poll when TikTok + Redis credentials are configured AND the shop
    owns the production-read credential; otherwise skip."""
    env = _poll_env_ready()
    if env is None:
        logger.info(
            "action_card_refresh_poll_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "missing_tiktok_or_redis_env",
            },
        )
        return

    # Resolve the production-read credential and check if this shop owns it.
    # Only the production-read shop should poll; other refreshes skip polling.
    from juli_backend.core.security.credential_resolver import (
        resolve_production_read_credential,
    )

    try:
        production_credential = await resolve_production_read_credential(session)
    except Exception:
        # If resolution fails (e.g., no production credential exists), skip polling.
        logger.info(
            "action_card_refresh_poll_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "shop_has_no_pollable_credential",
            },
        )
        return

    # Only poll if the requested shop owns the production-read credential.
    if production_credential.shop_id != shop_id:
        logger.info(
            "action_card_refresh_poll_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "not_production_read_shop",
            },
        )
        return

    import redis

    from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
    from juli_backend.integrations.tiktok import RateLimiter, TikTokAuth
    from juli_backend.services.etl.consumer import EtlConsumer
    from juli_backend.services.ingestion import make_etl_handoff
    from juli_backend.workers.services.polling import FujiwaPollConfig, run_fujiwa_poll_cycle

    async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
        logger.error(
            "action_card_refresh_etl_dlq",
            extra={
                "shop_id": str(shop_id),
                "channel": channel,
                "shop_key": shop_key,
                "payload_bytes": len(payload),
            },
        )

    consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
    handoff = make_etl_handoff(consumer)
    tiktok_auth = TikTokAuth(
        app_key=env["app_key"],
        app_secret=env["app_secret"],
        base_url=os.getenv(
            "TIKTOK_API_BASE_URL",
            "https://open-api.tiktokglobalshop.com",
        ),
    )
    oauth_service = TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=env["redirect_uri"],
        app_secret=env["app_secret"],
        binding_verifier=make_binding_verifier(
            app_key=env["app_key"], app_secret=env["app_secret"]
        ),
    )
    rate_limiter = RateLimiter(redis.from_url(env["redis_url"]))

    await run_fujiwa_poll_cycle(
        session=session,
        config=FujiwaPollConfig(app_key=env["app_key"], app_secret=env["app_secret"]),
        oauth_service=oauth_service,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
    )


async def run_action_card_refresh(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    poll: bool = True,
    poll_hook: Any | None = None,
) -> list[ActionCard]:
    """Execute one manual refresh cycle for a shop: poll → score → persist → emit budget.

    Applies the emission/surfacing budget immediately after persisting the candidates,
    on the same refresh run (#1289). This ensures manually-refreshed shops' cards
    surface properly in the public Demo API (list_surfaced_decisions gates on
    surfaced_at IS NOT NULL). Matches the continuous-trigger path's wiring
    (cdp_speed.decision_rules_scoring_stage).

    The persisted candidates are committed on their own durability boundary before
    the emission budget runs (dual cadence: recomputation and surfacing are
    independently gated). An emission-budget failure does not roll back the
    candidates already persisted.
    """
    if poll:
        runner = poll_hook or maybe_poll_tiktok_data
        await runner(session, shop_id)

    result = await run_daily_scoring_for_shop(session, shop_id)
    persisted_cards = await persist_scoring_result(session, shop_id, result)

    logger.info(
        "action_card_refresh_persisted",
        extra={
            "shop_id": str(shop_id),
            "persisted_card_count": len(persisted_cards),
        },
    )

    # Commit the persisted candidates on their own boundary, independent of
    # the emission budget below. This is the dual-cadence guarantee: a
    # recomputation must be durable even when the surfacing decision that
    # follows it fails. Matches decision_rules_scoring_stage (#716, B-4).
    await session.commit()

    try:
        outcome = await apply_emission_budget(session, shop_id)
    except Exception:
        logger.exception(
            "action_card_refresh_emission_failed",
            extra={
                "shop_id": str(shop_id),
            },
        )
        # Roll back only the emission budget's own (uncommitted) writes —
        # the candidates committed above are untouched. Re-raise: this is
        # containment of the *data*, not suppression of the *failure*.
        await session.rollback()
        raise

    logger.info(
        "action_card_refresh_emission_applied",
        extra={
            "shop_id": str(shop_id),
            "surfaced_count": len(outcome.surfaced),
            "suppressed_count": sum(len(cards) for cards in outcome.suppressed.values()),
        },
    )

    return persisted_cards
