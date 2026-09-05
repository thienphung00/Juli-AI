"""Serving KPI envelope repositories (``repositories/analytics.py``, #606).

``gold.kpi_envelopes`` is the source of truth; ``AnalyticsKpiEnvelopesRepo``
is a legacy-shaped adapter over it and must never touch the legacy table.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from juli_backend.models.models import AnalyticsKpiEnvelope, GoldKpiEnvelope
from juli_backend.repositories import AnalyticsKpiEnvelopesRepo, GoldKpiEnvelopesRepo
from juli_backend.services.gold_kpi_envelope_contract import build_honest_unavailable_shell_payload

COMPUTED_AT = datetime(2026, 7, 30, 6, 0, tzinfo=UTC)


def payload_for(shop_id):
    return build_honest_unavailable_shell_payload(shop_id=shop_id, computed_at=COMPUTED_AT)


async def count_rows(session, model, shop_id) -> int:
    stmt = select(func.count()).select_from(model).where(model.shop_id == shop_id)
    return (await session.execute(stmt)).scalar_one()


def test_gold_model_is_keyed_by_shop_in_the_gold_schema():
    table = GoldKpiEnvelope.__table__
    assert {c.name for c in table.primary_key.columns} == {"shop_id"}
    assert table.schema == "gold"
    assert {"shop_id", "computed_at", "envelope_version", "payload"} <= set(table.columns.keys())


class TestGoldKpiEnvelopesRepo:
    async def test_get_is_none_before_any_upsert(self, session, shop):
        assert await GoldKpiEnvelopesRepo(session).get(shop.id) is None

    async def test_upsert_then_get_round_trips_the_payload(self, session, shop):
        repo = GoldKpiEnvelopesRepo(session)
        payload = payload_for(shop.id)

        row = await repo.upsert(
            shop_id=shop.id, envelope_version=1, payload=payload, computed_at=COMPUTED_AT
        )

        fetched = await repo.get(shop.id)
        assert fetched is not None and fetched.shop_id == shop.id
        assert fetched.payload == payload
        assert row.shop_id == shop.id

    async def test_second_upsert_replaces_in_place_one_row_per_shop(self, session, shop):
        repo = GoldKpiEnvelopesRepo(session)
        await repo.upsert(
            shop_id=shop.id, envelope_version=1, payload={"kpis": {}}, computed_at=COMPUTED_AT
        )

        await repo.upsert(
            shop_id=shop.id,
            envelope_version=2,
            payload={"kpis": {"gmv": 1}},
            computed_at=COMPUTED_AT,
        )

        assert await count_rows(session, GoldKpiEnvelope, shop.id) == 1
        fetched = await repo.get(shop.id)
        assert (fetched.envelope_version, fetched.payload) == (2, {"kpis": {"gmv": 1}})


class TestAnalyticsKpiEnvelopesAdapter:
    async def test_writes_and_reads_gold_never_the_legacy_table(self, session, shop):
        repo = AnalyticsKpiEnvelopesRepo(session)
        payload = payload_for(shop.id)

        await repo.upsert(
            shop_id=shop.id,
            kind="analytics",
            envelope_version=1,
            payload=payload,
            computed_at=COMPUTED_AT,
        )

        assert await count_rows(session, GoldKpiEnvelope, shop.id) == 1
        assert await count_rows(session, AnalyticsKpiEnvelope, shop.id) == 0
        fetched = await repo.get_by_kind(shop.id, "analytics")
        assert fetched is not None and fetched.payload["kpis"] == payload["kpis"]
        assert fetched.kind == "analytics"

    async def test_legacy_id_is_deterministic_per_shop(self, session, shop):
        repo = AnalyticsKpiEnvelopesRepo(session)
        await repo.upsert(
            shop_id=shop.id,
            kind="analytics",
            envelope_version=1,
            payload={"kpis": {}},
            computed_at=COMPUTED_AT,
        )

        first = await repo.get_by_kind(shop.id, "analytics")
        second = await repo.get_by_kind(shop.id, "analytics")

        assert first.id == second.id

    @pytest.mark.parametrize("kind", ["orders", "returns", ""])
    async def test_only_the_analytics_kind_exists_after_the_cutover(self, session, shop, kind):
        repo = AnalyticsKpiEnvelopesRepo(session)

        assert await repo.get_by_kind(shop.id, kind) is None
        with pytest.raises(ValueError, match="unsupported envelope kind after gold cutover"):
            await repo.upsert(
                shop_id=shop.id, kind=kind, envelope_version=1, payload={}, computed_at=COMPUTED_AT
            )

    async def test_list_is_the_single_row_or_empty(self, session, shop):
        repo = AnalyticsKpiEnvelopesRepo(session)
        assert await repo.list(shop.id) == []

        await repo.upsert(
            shop_id=shop.id,
            kind="analytics",
            envelope_version=1,
            payload={"kpis": {}},
            computed_at=COMPUTED_AT,
        )

        assert len(await repo.list(shop.id)) == 1
        assert await repo.list(shop.id, limit=0) == []
