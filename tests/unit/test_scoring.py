"""Tests for intelligence/scoring module — Issue #34.

Test mapping (from issue):
  AC1 → test_livestream_score_produces_comparable_grade
  AC2 → test_anomaly_detection_fires_on_deviation
  AC3 → test_retention_curve_minute_granularity
  AC4 → test_comment_sentiment_handles_vietnamese
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.utils.data.models import Creator, Livestream, Order, Shop, User
from src.modules.catalog.domain.intelligence.scoring.scorer import LivestreamScore, score_livestream
from src.modules.catalog.domain.intelligence.scoring.anomaly import Anomaly, detect_anomalies
from src.modules.catalog.domain.intelligence.scoring.retention import RetentionPoint, get_stream_retention
from src.modules.catalog.domain.intelligence.scoring.sentiment import SentimentResult, analyze_comments


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


def _make_order(
    shop_id: uuid.UUID,
    *,
    tiktok_order_id: str,
    total_amount: Decimal = Decimal("60.00"),
    status: str = "COMPLETED",
    created_at: datetime | None = None,
) -> Order:
    now = datetime.utcnow()
    return Order(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_order_id=tiktok_order_id,
        status=status,
        total_amount=total_amount,
        currency="VND",
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
# AC1 — score_livestream produces 0–100 comparable grade
# ===================================================================


class TestLivestreamScoreProducesComparableGrade:
    """AC1: score_livestream(session_id) produces 0–100 grade comparable
    across sessions using weighted metrics."""

    @pytest.mark.asyncio
    async def test_score_returns_grade_between_0_and_100(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        ls = _make_livestream(shop_id, viewer_count=500, order_count=25, revenue=Decimal("1500.00"))
        session.add(ls)
        await session.flush()

        result = await score_livestream(session, ls.id)

        assert isinstance(result, LivestreamScore)
        assert 0 <= result.grade <= 100

    @pytest.mark.asyncio
    async def test_higher_revenue_per_viewer_produces_higher_grade(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)

        low = _make_livestream(
            shop_id, tiktok_id="tls_low",
            viewer_count=500, order_count=10, revenue=Decimal("200.00"),
        )
        high = _make_livestream(
            shop_id, tiktok_id="tls_high",
            viewer_count=500, order_count=50, revenue=Decimal("5000.00"),
        )
        session.add_all([low, high])
        await session.flush()

        score_low = await score_livestream(session, low.id)
        score_high = await score_livestream(session, high.id)

        assert score_high.grade > score_low.grade

    @pytest.mark.asyncio
    async def test_score_includes_breakdown_dict(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        ls = _make_livestream(shop_id)
        session.add(ls)
        await session.flush()

        result = await score_livestream(session, ls.id)

        assert isinstance(result.breakdown, dict)
        assert len(result.breakdown) > 0

    @pytest.mark.asyncio
    async def test_score_with_zero_viewers_returns_zero(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        ls = _make_livestream(
            shop_id, tiktok_id="tls_zero",
            viewer_count=0, order_count=0, revenue=Decimal("0"),
        )
        session.add(ls)
        await session.flush()

        result = await score_livestream(session, ls.id)
        assert result.grade == 0


# ===================================================================
# AC2 — detect_anomalies fires on 2σ deviation
# ===================================================================


class TestAnomalyDetectionFiresOnDeviation:
    """AC2: detect_anomalies(shop_id) fires within 5 minutes of a 2σ
    deviation in revenue, return rate, or cost metrics."""

    @pytest.mark.asyncio
    async def test_no_anomalies_in_stable_data(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        base_time = datetime.utcnow() - timedelta(days=35)

        streams = []
        for i in range(30):
            streams.append(_make_livestream(
                shop_id,
                tiktok_id=f"tls_stable_{i}",
                revenue=Decimal("1000.00"),
                viewer_count=500,
                order_count=20,
                start_time=base_time + timedelta(days=i),
                end_time=base_time + timedelta(days=i, hours=2),
            ))
        session.add_all(streams)
        await session.flush()

        anomalies = await detect_anomalies(session, shop_id)
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_detects_revenue_spike(self, session: AsyncSession):
        """A livestream with 5x typical revenue should trigger anomaly."""
        _, shop_id = await _seed_shop(session)
        base_time = datetime.utcnow() - timedelta(days=35)

        streams = []
        for i in range(30):
            streams.append(_make_livestream(
                shop_id,
                tiktok_id=f"tls_normal_{i}",
                revenue=Decimal("1000.00"),
                viewer_count=500,
                order_count=20,
                start_time=base_time + timedelta(days=i),
                end_time=base_time + timedelta(days=i, hours=2),
            ))
        spike = _make_livestream(
            shop_id,
            tiktok_id="tls_spike",
            revenue=Decimal("10000.00"),
            viewer_count=500,
            order_count=20,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
        )
        session.add_all([*streams, spike])
        await session.flush()

        anomalies = await detect_anomalies(session, shop_id)

        assert len(anomalies) >= 1
        revenue_anomalies = [a for a in anomalies if a.metric == "revenue"]
        assert len(revenue_anomalies) >= 1
        assert isinstance(revenue_anomalies[0], Anomaly)
        assert revenue_anomalies[0].deviation_sigma >= 2.0

    @pytest.mark.asyncio
    async def test_detects_revenue_drop(self, session: AsyncSession):
        """A livestream with near-zero revenue should also trigger anomaly."""
        _, shop_id = await _seed_shop(session)
        base_time = datetime.utcnow() - timedelta(days=35)

        streams = []
        for i in range(30):
            streams.append(_make_livestream(
                shop_id,
                tiktok_id=f"tls_norm_{i}",
                revenue=Decimal("1000.00"),
                viewer_count=500,
                order_count=20,
                start_time=base_time + timedelta(days=i),
                end_time=base_time + timedelta(days=i, hours=2),
            ))
        drop = _make_livestream(
            shop_id,
            tiktok_id="tls_drop",
            revenue=Decimal("10.00"),
            viewer_count=500,
            order_count=1,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
        )
        session.add_all([*streams, drop])
        await session.flush()

        anomalies = await detect_anomalies(session, shop_id)
        assert len(anomalies) >= 1

    @pytest.mark.asyncio
    async def test_moving_average_fallback_under_30_days(self, session: AsyncSession):
        """With <30 days of data, should still run (moving-average fallback)
        and not crash."""
        _, shop_id = await _seed_shop(session)
        base_time = datetime.utcnow() - timedelta(days=10)

        streams = []
        for i in range(5):
            streams.append(_make_livestream(
                shop_id,
                tiktok_id=f"tls_short_{i}",
                revenue=Decimal("1000.00"),
                viewer_count=500,
                order_count=20,
                start_time=base_time + timedelta(days=i),
                end_time=base_time + timedelta(days=i, hours=2),
            ))
        session.add_all(streams)
        await session.flush()

        anomalies = await detect_anomalies(session, shop_id)
        assert isinstance(anomalies, list)

    @pytest.mark.asyncio
    async def test_anomaly_includes_metadata(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        base_time = datetime.utcnow() - timedelta(days=35)

        streams = []
        for i in range(30):
            streams.append(_make_livestream(
                shop_id,
                tiktok_id=f"tls_meta_{i}",
                revenue=Decimal("1000.00"),
                viewer_count=500,
                order_count=20,
                start_time=base_time + timedelta(days=i),
                end_time=base_time + timedelta(days=i, hours=2),
            ))
        spike = _make_livestream(
            shop_id,
            tiktok_id="tls_meta_spike",
            revenue=Decimal("10000.00"),
            viewer_count=500,
            order_count=20,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
        )
        session.add_all([*streams, spike])
        await session.flush()

        anomalies = await detect_anomalies(session, shop_id)
        a = anomalies[0]
        assert hasattr(a, "metric")
        assert hasattr(a, "current_value")
        assert hasattr(a, "mean")
        assert hasattr(a, "deviation_sigma")
        assert hasattr(a, "livestream_id")


# ===================================================================
# AC3 — retention curve at minute granularity
# ===================================================================


class TestRetentionCurveMinuteGranularity:
    """AC3: get_stream_retention(session_id) returns minute-by-minute viewer
    retention curve (derived from post-stream summary data)."""

    @pytest.mark.asyncio
    async def test_returns_list_of_retention_points(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        now = datetime.utcnow()
        ls = _make_livestream(
            shop_id,
            viewer_count=1000,
            start_time=now - timedelta(hours=1),
            end_time=now,
        )
        session.add(ls)
        await session.flush()

        result = await get_stream_retention(session, ls.id)

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(p, RetentionPoint) for p in result)

    @pytest.mark.asyncio
    async def test_minute_granularity_matches_duration(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        now = datetime.utcnow()
        duration_minutes = 90
        ls = _make_livestream(
            shop_id,
            viewer_count=800,
            start_time=now - timedelta(minutes=duration_minutes),
            end_time=now,
        )
        session.add(ls)
        await session.flush()

        result = await get_stream_retention(session, ls.id)

        assert len(result) == duration_minutes

    @pytest.mark.asyncio
    async def test_retention_starts_at_peak_and_decays(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        now = datetime.utcnow()
        ls = _make_livestream(
            shop_id,
            viewer_count=1000,
            start_time=now - timedelta(hours=2),
            end_time=now,
        )
        session.add(ls)
        await session.flush()

        result = await get_stream_retention(session, ls.id)

        assert result[0].viewers <= 1000
        assert result[0].minute == 1
        assert result[-1].viewers <= result[0].viewers

    @pytest.mark.asyncio
    async def test_retention_point_has_minute_field(self, session: AsyncSession):
        _, shop_id = await _seed_shop(session)
        now = datetime.utcnow()
        ls = _make_livestream(
            shop_id,
            viewer_count=500,
            start_time=now - timedelta(minutes=30),
            end_time=now,
        )
        session.add(ls)
        await session.flush()

        result = await get_stream_retention(session, ls.id)

        minutes = [p.minute for p in result]
        assert minutes == list(range(1, 31))


# ===================================================================
# AC4 — comment sentiment handles Vietnamese
# ===================================================================


class TestCommentSentimentHandlesVietnamese:
    """AC4: analyze_comments(session_id) handles Vietnamese text with
    diacritics for sentiment classification."""

    def test_positive_vietnamese_comment(self):
        comments = ["Sản phẩm rất tuyệt vời, tôi rất thích!"]
        result = analyze_comments(comments)
        assert isinstance(result, SentimentResult)
        assert result.positive_count >= 1

    def test_negative_vietnamese_comment(self):
        comments = ["Chất lượng quá tệ, thất vọng hoàn toàn"]
        result = analyze_comments(comments)
        assert result.negative_count >= 1

    def test_mixed_comments(self):
        comments = [
            "Tuyệt vời quá!",
            "Bình thường thôi",
            "Quá tệ, không mua nữa",
        ]
        result = analyze_comments(comments)
        assert result.positive_count >= 1
        assert result.negative_count >= 1
        assert result.total == 3

    def test_handles_diacritics_correctly(self):
        comments_with_diacritics = [
            "Đẹp quá, ưng ý lắm!",
            "Hàng ổn, giao nhanh",
        ]
        result = analyze_comments(comments_with_diacritics)
        assert result.total == 2
        assert result.positive_count + result.negative_count + result.neutral_count == result.total

    def test_empty_comments_list(self):
        result = analyze_comments([])
        assert result.total == 0
        assert result.positive_count == 0
        assert result.negative_count == 0
        assert result.neutral_count == 0

    def test_result_includes_overall_sentiment(self):
        comments = ["Tốt lắm!", "Rất đẹp", "Chất lượng cao"]
        result = analyze_comments(comments)
        assert result.overall in ("positive", "negative", "neutral", "mixed")
