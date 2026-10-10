"""The seller's analysed videos as context for Juli soạn (fast track P15, D24.19).

A content run's drafter sees, next to TikTok's numbers, the analysis of the
seller's BEST and WEAKEST analysed video (or LIVE) of the product: what their
hook, product timing, CTA and pacing were. Best / weakest are by the TikTok
rate the run itself read (video CTR / LIVE CTOR) when the upload names its
Phân tích row; uploads without a row (from a content run) are used as "đã tải
lên" when fewer than two rows match. Only the derived result is sent -- never a
transcript dump, never media.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.services.content_analysis.pipeline import STATUS_DONE

MAX_LOADED = 10
MAX_IN_PROMPT = 2


def ref_hash(content_ref: str | None) -> str | None:
    """``video:<id>`` → the 12-char ref the content tools give the same row."""
    if not content_ref or ":" not in content_ref:
        return None
    kind, raw_id = content_ref.split(":", 1)
    return hashlib.sha256(f"{kind}:{raw_id}".encode()).hexdigest()[:12]


def summary(row: ContentAnalysis) -> dict[str, Any]:
    result = row.result or {}
    hook = result.get("hook") or {}
    cta = result.get("cta") or {}
    pacing = result.get("pacing") or {}
    return {
        "ref": ref_hash(row.content_ref),
        "kind": row.kind,
        "mở_đầu": " — ".join(p for p in (hook.get("label"), hook.get("reason")) if p),
        "sản_phẩm_xuất_hiện": result.get("product_line"),
        "lời_kêu_gọi": cta.get("line"),
        "nhịp_cắt": pacing.get("line"),
        "vấn_đề": [i.get("text") for i in (result.get("issues") or [])[:3] if isinstance(i, dict)],
    }


async def load_summaries(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_product_id: str, kind: str
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ContentAnalysis)
            .where(
                ContentAnalysis.shop_id == shop_id,
                ContentAnalysis.tiktok_product_id == tiktok_product_id,
                ContentAnalysis.kind == kind,
                ContentAnalysis.status == STATUS_DONE,
            )
            .order_by(ContentAnalysis.created_at.desc())
            .limit(MAX_LOADED)
        )
    ).scalars()
    return [summary(row) for row in rows]


def pick(
    summaries: Sequence[Mapping[str, Any]],
    rate_by_ref: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    """Best and weakest by the TikTok rate; the latest unranked uploads fill the rest."""

    def rate(s: Mapping[str, Any]) -> float | None:
        ref = s.get("ref")
        value = rate_by_ref.get(ref) if ref else None
        return float(value) if value is not None else None

    ranked = sorted((s for s in summaries if rate(s) is not None), key=lambda s: -(rate(s) or 0))
    chosen: list[tuple[str, Mapping[str, Any]]] = []
    if ranked:
        chosen.append(("tốt nhất", ranked[0]))
    if len(ranked) > 1:
        chosen.append(("yếu nhất", ranked[-1]))
    for s in summaries:
        if len(chosen) >= MAX_IN_PROMPT:
            break
        if rate(s) is None:
            chosen.append(("đã tải lên", s))
    return [{"nhóm": group, **_public(s)} for group, s in chosen[:MAX_IN_PROMPT]]


def _public(s: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in s.items() if k not in ("ref", "kind") and v}


__all__ = ["load_summaries", "pick", "ref_hash", "summary"]
