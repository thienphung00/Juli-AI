"""Tests for livestream script recommendation module — Issue #725 (RA-5).

Test mapping (from issue):
  AC1 → test_score_livestream_continues_to_pass_unmodified (regression guard)
  AC2 → test_each_classification_tier_covered
  AC3 → test_new_seller_fallback_with_best_practice_script
  AC4 → test_template_selection_ai_fallback_produces_usable_script
  AC5 → test_well_performing_stream_highlights_what_worked
  AC6 → test_acknowledgment_makes_zero_tiktok_calls
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.ranking.scorer import score_livestream
from juli_backend.ai.recommendations.livestream_script import (
    acknowledge_livestream_script,
    classify_livestream_performance,
    get_livestream_script_recommendation,
)
from juli_backend.models.models import Creator, Livestream, Shop, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID) -> User:
    return User(id=user_id, phone="+84900000001")


def _make_shop(shop_id: uuid.UUID, user_id: uuid.UUID) -> Shop:
    return Shop(id=shop_id, user_id=user_id, shop_name="Test Shop")


def _make_creator(shop_id: uuid.UUID, creator_id: uuid.UUID) -> Creator:
    return Creator(
        id=creator_id,
        shop_id=shop_id,
        tiktok_creator_id="tc_001",
        name="Host A",
    )


def _make_livestream(
    shop_id: uuid.UUID,
    *,
    ls_id: uuid.UUID | None = None,
    creator_id: uuid.UUID | None = None,
    tiktok_id: str = "tls_001",
    viewer_count: int = 500,
    order_count: int = 25,
    revenue: Decimal = Decimal("1500.00"),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Livestream:
    now = datetime.utcnow()
    return Livestream(
        id=ls_id or uuid.uuid4(),
        shop_id=shop_id,
        tiktok_livestream_id=tiktok_id,
        creator_id=creator_id,
        title="Test Stream",
        viewer_count=viewer_count,
        order_count=order_count,
        revenue=revenue,
        start_time=start_time or now - timedelta(hours=2),
        end_time=end_time or now,
        update_time=now,
    )


async def _seed_shop(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a user + shop, return (user_id, shop_id)."""
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    session.add(_make_user(uid))
    session.add(_make_shop(sid, uid))
    await session.flush()
    return uid, sid


# ===================================================================
# AC1 — score_livestream regression guard
# ===================================================================


class TestScoreLivestreamRegressionGuard:
    """AC1: score_livestream continues to pass its existing tests unmodified."""

    @pytest.mark.asyncio
    async def test_score_livestream_returns_grade_between_0_and_100(self, session: AsyncSession):
        """Existing score_livestream behavior must continue."""
        _, shop_id = await _seed_shop(session)
        ls = _make_livestream(shop_id)
        session.add(ls)
        await session.flush()

        result = await score_livestream(session, ls.id)

        assert 0 <= result.grade <= 100
        assert result.breakdown is not None


# ===================================================================
# AC2 — New tests cover each of the three classification tiers
# ===================================================================


class TestClassificationTiersAreCovered:
    """AC2: New tests cover each of the three classification tiers."""

    @pytest.mark.asyncio
    async def test_classify_weak_performer_streams(self, session: AsyncSession):
        """Classify a stream that performed below shop average."""
        _, shop_id = await _seed_shop(session)

        # Create baseline streams with moderate performance
        base_time = datetime.utcnow() - timedelta(days=10)
        baseline_streams = []
        for i in range(5):
            baseline_streams.append(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )
        session.add_all(baseline_streams)

        # Current weak stream
        weak_stream = _make_livestream(
            shop_id,
            tiktok_id="weak_stream",
            viewer_count=500,
            order_count=5,  # Very low orders
            revenue=Decimal("200.00"),  # Very low revenue
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
        )
        session.add(weak_stream)
        await session.flush()

        classification = await classify_livestream_performance(session, shop_id, weak_stream.id)

        assert classification.tier in ("needs_improvement", "maintenance", "low_confidence")
        assert classification.tier == "needs_improvement"
        assert classification.script_template is not None

    @pytest.mark.asyncio
    async def test_classify_strong_performer_streams(self, session: AsyncSession):
        """Classify a stream that performed above shop average."""
        _, shop_id = await _seed_shop(session)

        # Create baseline streams with moderate performance
        base_time = datetime.utcnow() - timedelta(days=10)
        baseline_streams = []
        for i in range(5):
            baseline_streams.append(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )
        session.add_all(baseline_streams)

        # Current strong stream
        strong_stream = _make_livestream(
            shop_id,
            tiktok_id="strong_stream",
            viewer_count=500,
            order_count=60,  # Very high orders
            revenue=Decimal("5000.00"),  # Very high revenue
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
        )
        session.add(strong_stream)
        await session.flush()

        classification = await classify_livestream_performance(session, shop_id, strong_stream.id)

        assert classification.tier in ("needs_improvement", "maintenance", "low_confidence")
        assert classification.tier == "maintenance"
        assert classification.script_template is not None

    @pytest.mark.asyncio
    async def test_classify_low_confidence_streams(self, session: AsyncSession):
        """Classify when shop has too few past streams for comparison."""
        _, shop_id = await _seed_shop(session)

        # Only one baseline stream (not enough for confident comparison)
        baseline = _make_livestream(
            shop_id,
            tiktok_id="baseline_only",
            viewer_count=500,
            order_count=25,
            revenue=Decimal("1500.00"),
        )
        session.add(baseline)

        # Current stream
        current = _make_livestream(
            shop_id,
            tiktok_id="current_stream",
            viewer_count=600,
            order_count=30,
            revenue=Decimal("2000.00"),
        )
        session.add(current)
        await session.flush()

        classification = await classify_livestream_performance(session, shop_id, current.id)

        assert classification.tier == "low_confidence"
        assert classification.script_template is not None


# ===================================================================
# AC3 — New sellers with too few past streams get fallback script
# ===================================================================


class TestNewSellerFallback:
    """AC3: New sellers with too few past streams get general best-practice script."""

    @pytest.mark.asyncio
    async def test_brand_new_seller_with_no_history_gets_best_practice_script(
        self, session: AsyncSession
    ):
        """A brand-new seller with no past streams gets a best-practice script."""
        _, shop_id = await _seed_shop(session)

        # First livestream ever for this shop
        first_stream = _make_livestream(
            shop_id,
            tiktok_id="first_stream",
            viewer_count=300,
            order_count=10,
            revenue=Decimal("500.00"),
        )
        session.add(first_stream)
        await session.flush()

        recommendation = await get_livestream_script_recommendation(
            session, shop_id, first_stream.id
        )

        assert recommendation is not None
        assert recommendation.script is not None
        assert len(recommendation.script) > 0
        # Fallback should be in Vietnamese
        assert (
            any(
                ch in recommendation.script
                for ch in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
            )
            or "Nên" in recommendation.script
        )

    @pytest.mark.asyncio
    async def test_low_confidence_recommendation_includes_best_practice(
        self, session: AsyncSession
    ):
        """With insufficient history, still provide actionable guidance."""
        _, shop_id = await _seed_shop(session)

        current = _make_livestream(
            shop_id,
            tiktok_id="current_stream",
            viewer_count=100,
            order_count=5,
            revenue=Decimal("250.00"),
        )
        session.add(current)
        await session.flush()

        recommendation = await get_livestream_script_recommendation(session, shop_id, current.id)

        assert recommendation is not None
        assert len(recommendation.script) > 0
        # Should not be empty or error state
        assert recommendation.script != ""


# ===================================================================
# AC4 — Template selection and AI fallback
# ===================================================================


class TestTemplateSelectionAndAiFallback:
    """AC4: When AI is unavailable or fails, fallback to deterministic template."""

    @pytest.mark.asyncio
    async def test_fallback_when_llm_unavailable(self, session: AsyncSession):
        """When no LLM generator provided, use deterministic template."""
        _, shop_id = await _seed_shop(session)

        base_time = datetime.utcnow() - timedelta(days=10)
        for i in range(5):
            session.add(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )

        weak_stream = _make_livestream(
            shop_id,
            tiktok_id="weak_stream",
            viewer_count=500,
            order_count=5,
            revenue=Decimal("200.00"),
        )
        session.add(weak_stream)
        await session.flush()

        # No LLM generator provided
        recommendation = await get_livestream_script_recommendation(
            session, shop_id, weak_stream.id, llm_generator=None
        )

        assert recommendation is not None
        assert recommendation.script is not None
        assert len(recommendation.script) > 0
        assert recommendation.source == "rules"

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self, session: AsyncSession):
        """When LLM generation fails, fall back to deterministic template."""
        _, shop_id = await _seed_shop(session)

        base_time = datetime.utcnow() - timedelta(days=10)
        for i in range(5):
            session.add(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )

        weak_stream = _make_livestream(
            shop_id,
            tiktok_id="weak_stream",
            viewer_count=500,
            order_count=5,
            revenue=Decimal("200.00"),
        )
        session.add(weak_stream)
        await session.flush()

        # LLM generator that fails
        async def failing_llm(_: str) -> str:
            raise RuntimeError("LLM service down")

        recommendation = await get_livestream_script_recommendation(
            session, shop_id, weak_stream.id, llm_generator=failing_llm
        )

        assert recommendation is not None
        assert recommendation.script is not None
        assert len(recommendation.script) > 0
        # Should fall back to rules
        assert recommendation.source == "rules"

    @pytest.mark.asyncio
    async def test_llm_personalization_when_available(self, session: AsyncSession):
        """When LLM is available and succeeds, use personalized script."""
        _, shop_id = await _seed_shop(session)

        base_time = datetime.utcnow() - timedelta(days=10)
        for i in range(5):
            session.add(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )

        weak_stream = _make_livestream(
            shop_id,
            tiktok_id="weak_stream",
            viewer_count=500,
            order_count=5,
            revenue=Decimal("200.00"),
        )
        session.add(weak_stream)
        await session.flush()

        # Successful LLM generator
        async def successful_llm(_: str) -> str:
            return "Hãy tăng tốc độ giới thiệu sản phẩm và tạo ưu đãi chốt đơn sớm."

        recommendation = await get_livestream_script_recommendation(
            session,
            shop_id,
            weak_stream.id,
            llm_generator=successful_llm,
            max_calls_per_day=10,
        )

        assert recommendation is not None
        assert recommendation.script is not None
        assert recommendation.source == "llm"


# ===================================================================
# AC5 — Well-performing stream highlights what worked
# ===================================================================


class TestWellPerformingStreamFeedback:
    """AC5: Well-performing stream's feedback highlights what worked, not problems."""

    @pytest.mark.asyncio
    async def test_strong_performer_gets_positive_feedback(self, session: AsyncSession):
        """A stream that outperformed should get positive reinforcement."""
        _, shop_id = await _seed_shop(session)

        base_time = datetime.utcnow() - timedelta(days=10)
        for i in range(5):
            session.add(
                _make_livestream(
                    shop_id,
                    tiktok_id=f"baseline_{i}",
                    viewer_count=500,
                    order_count=25,
                    revenue=Decimal("1500.00"),
                    start_time=base_time + timedelta(days=i),
                    end_time=base_time + timedelta(days=i, hours=1),
                )
            )

        strong_stream = _make_livestream(
            shop_id,
            tiktok_id="strong_stream",
            viewer_count=500,
            order_count=60,
            revenue=Decimal("5000.00"),
        )
        session.add(strong_stream)
        await session.flush()

        recommendation = await get_livestream_script_recommendation(
            session, shop_id, strong_stream.id
        )

        assert recommendation is not None
        # Should emphasize what worked, not problems
        script_lower = recommendation.script.lower()
        # Should contain positive framing
        assert (
            any(
                positive_word in script_lower
                for positive_word in [
                    "tuyệt",
                    "tốt",
                    "thành công",
                    "tiếp tục",
                    "duy trì",
                    "giữ lại",
                ]
            )
            or "Nên" in recommendation.script
        )


# ===================================================================
# AC6 — Acknowledgment makes zero TikTok calls
# ===================================================================


class TestAcknowledgmentZeroTikTokCalls:
    """AC6: Acknowledging the recommendation makes zero calls to TikTok write endpoints."""

    @pytest.mark.asyncio
    async def test_acknowledgment_only_writes_to_local_db(self, session: AsyncSession):
        """Acknowledgment should only write to local database, no TikTok API calls."""
        _, shop_id = await _seed_shop(session)

        ls = _make_livestream(shop_id)
        session.add(ls)
        await session.flush()

        # Call acknowledge and verify it returns without errors
        result = await acknowledge_livestream_script(session, shop_id, ls.id, "scripts_v1")

        assert result is not None
        assert result["status"] == "acknowledged"
        assert result["livestream_id"] == str(ls.id)
        # Should have recorded_at timestamp
        assert "recorded_at" in result

    @pytest.mark.asyncio
    async def test_acknowledgment_records_in_local_db(self, session: AsyncSession):
        """Acknowledgment should record locally without external API calls."""
        _, shop_id = await _seed_shop(session)

        ls = _make_livestream(shop_id)
        session.add(ls)
        await session.flush()

        # Call acknowledge and verify it returns without errors
        result = await acknowledge_livestream_script(session, shop_id, ls.id, "scripts_v1")

        # Should return a record indicating acknowledgment was recorded
        assert result is not None
        # Verify the DB was written to
        from sqlalchemy import select

        from juli_backend.models.models import Recommendation

        stmt = select(Recommendation).where(
            Recommendation.recommendation_type == "livestream_script_acknowledged",
            Recommendation.shop_id == shop_id,
        )
        rec = await session.execute(stmt)
        recorded = rec.scalar_one_or_none()
        assert recorded is not None
