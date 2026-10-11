"""P15 content analysis of seller-uploaded videos and LIVE recordings (D24.19, D24.20).

Contract: ``fasttrack/contracts/p15-content-analysis.md``.

- ``config`` -- limits, models, paths, the default monthly cap (environment).
- ``storage`` -- temporary files on the VPS disk, the signed upload token, the sweep.
- ``uploads`` -- upload slots, chunks, the seller-facing view.
- ``media`` -- ffprobe / ffmpeg (read only, ``-f mov``, local files only).
- ``cuts`` -- scene cuts (port of the content engine's ``reference_analyze.py``).
- ``openai_media`` -- transcription and keyframe vision (OpenAI).
- ``scoring`` -- the ONE structured-output call over derived signals, the result.
- ``costs`` -- the per-shop monthly OpenAI cap.
- ``pipeline`` -- one analysis end to end; ``product_info`` -- product name /
  brand / images / SEO words.
- ``context`` -- best / weakest analyses as context for Juli soạn.

The package root re-exports what ``api`` and ``workers`` use (the import
boundary allows them the public root only). ``content_cards`` imports
``context`` lazily, inside the run, so there is no import cycle.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.content_analysis import (
    context,
    costs,
    media,
    pipeline,
    storage,
    uploads,
)
from juli_backend.services.content_analysis.config import AnalysisSettings, settings
from juli_backend.services.content_analysis.openai_media import (
    OpenAITranscriber,
    OpenAIVision,
    ProviderError,
)
from juli_backend.services.content_analysis.pipeline import (
    STATUS_PROCESSING,
    STATUS_QUEUED,
    Collaborators,
)
from juli_backend.services.content_analysis.product_info import TikTokProductReader
from juli_backend.services.content_analysis.scoring import OpenAIScorer
from juli_backend.services.content_cards.guardrails import ContentRules


async def seller_rules(session: AsyncSession, shop_id: uuid.UUID) -> ContentRules:
    """The seller's tone and banned words (the content runs' reader of Quy tắc)."""
    from juli_backend.services.content_cards.driver import load_rules

    return await load_rules(session, shop_id, discount_cap_pct=None)


__all__ = [
    "STATUS_PROCESSING",
    "STATUS_QUEUED",
    "AnalysisSettings",
    "Collaborators",
    "OpenAIScorer",
    "OpenAITranscriber",
    "OpenAIVision",
    "ProviderError",
    "TikTokProductReader",
    "context",
    "costs",
    "media",
    "pipeline",
    "seller_rules",
    "settings",
    "storage",
    "uploads",
]
