"""Q5 (batch-1124-c-data, decision #67): analytical reads bind the read engine when
``DATABASE_READ_URL`` is set; unset = the request's own session; writes through it raise."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.database import read_engine
from juli_backend.database.read_engine import ReadOnlySessionError, read_session
from juli_backend.database.tenant_context import clear_tenant_context, set_tenant_context
from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.orm_base import Base
from juli_backend.services.metrics import query as q

SHOP = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
USER = uuid.UUID("00000000-0000-4000-8000-0000000000cc")


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(read_engine.READ_URL_ENV, raising=False)
    read_engine.reset_read_engine_for_tests()
    clear_tenant_context()
    yield
    read_engine.reset_read_engine_for_tests()
    clear_tenant_context()


@pytest.fixture
async def primary(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'primary.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ShopeeShopMetricsDaily.__table__])
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def _replica_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'replica.db'}"


async def test_unset_uses_the_request_session_and_one_engine(primary: AsyncSession) -> None:
    set_tenant_context(SHOP, USER)
    assert read_engine.read_session_factory() is None
    async with read_session(primary) as s:
        assert s is primary


async def test_set_binds_the_read_engine(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    async with read_session(primary) as s:
        assert s is not primary
        assert read_engine.is_read_session(s)
        assert str(s.get_bind().url).endswith("replica.db")
        # a read session handed back in is used as it is
        async with read_session(s) as again:
            assert again is s


async def test_a_write_through_the_read_session_raises(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    async with read_session(primary) as s:
        s.add(ShopeeShopMetricsDaily(shop_id=SHOP, day=date(2026, 3, 1), order_type="confirmed"))
        with pytest.raises(ReadOnlySessionError) as flush_exc:
            await s.flush()
        assert "read session" in str(flush_exc.value)
        s.expunge_all()
        with pytest.raises(ReadOnlySessionError) as exec_exc:
            await s.execute(sa.delete(ShopeeShopMetricsDaily))
        assert "read session" in str(exec_exc.value)


async def test_a_request_that_wrote_reads_from_the_primary(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    primary.add(ShopeeShopMetricsDaily(shop_id=SHOP, day=date(2026, 3, 1), order_type="confirmed"))
    await primary.flush()
    assert read_engine.wrote(primary)
    async with read_session(primary) as s:
        assert s is primary


async def test_mark_wrote_pins_the_primary(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    read_engine.mark_wrote(primary)
    async with read_session(primary) as s:
        assert s is primary


async def test_no_tenant_in_context_never_opens_an_unscoped_replica_read(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    async with read_session(primary) as s:
        assert s is primary


async def test_the_read_session_gets_the_request_tenant_gucs(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    applied: list[tuple[object, object]] = []

    async def spy(session: AsyncSession, shop_id: object, user_id: object, **_: object) -> None:
        applied.append((shop_id, user_id))

    monkeypatch.setattr(read_engine, "_apply_tenant_context_to_session", spy)
    async with read_session(primary) as s:
        assert s is not primary
    assert applied == [(SHOP, USER)]


def test_a_postgres_read_engine_starts_every_transaction_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_engine(url: str, **kwargs: object) -> object:
        captured.update(url=url, **kwargs)
        return create_async_engine("sqlite+aiosqlite://")

    monkeypatch.setattr(read_engine, "create_api_engine", fake_engine)
    monkeypatch.setenv(read_engine.READ_URL_ENV, "postgresql://ro@replica.example:5432/db")
    assert read_engine.read_session_factory() is not None
    assert str(captured["url"]).startswith("postgresql+asyncpg://")
    assert captured["connect_args"] == {"server_settings": {"default_transaction_read_only": "on"}}


async def test_query_reads_through_the_read_session(
    primary: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(read_engine.READ_URL_ENV, _replica_url(tmp_path))
    set_tenant_context(SHOP, USER)
    seen: list[AsyncSession] = []

    class Spy(q.MemoryRowSource):
        async def rows(self, session: AsyncSession | None, read: q.Read) -> list[Mapping[str, Any]]:
            assert session is not None
            seen.append(session)
            return []

    monkeypatch.setattr(q, "SQL_SOURCE", Spy())
    from juli_backend.services.shopee_analytics import facts_source

    async def no_data(*_: object) -> frozenset[date]:
        return frozenset()

    monkeypatch.setattr(facts_source, "data_days", no_data)
    await q.query(
        primary, SHOP, ["gmv"], scope=q.Scope.shop(), window=(date(2026, 3, 1),) * 2,
        mode="stored",
    )  # fmt: skip
    assert seen and seen[0] is not primary
    assert read_engine.is_read_session(seen[0])
