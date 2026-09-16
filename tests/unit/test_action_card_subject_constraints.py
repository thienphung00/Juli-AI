"""``action_cards`` subject-scoped identity, added by migration
`061_workflow_and_subject` (#1701, ADR-087 d.1-d.3):
``uq_action_cards_shop_workflow_subject_revision`` (full unique over the
chain) and ``uq_action_cards_active_shop_workflow_subject`` (partial unique,
one live card per subject per workflow).

Postgres-only throughout, on a disposable per-module database created and
torn down here -- the partial unique's ``WHERE status = 'active'`` predicate
is a Postgres-only DDL feature SQLite silently drops, and this migration's
whole coexistence claim rests on a real catalog, not the migration's own
source text. Modeled on
``tests/unit/test_agent_runner_concurrency.py``'s ``_disposable_postgres_url``
pattern (five sibling modules already duplicate this fixture).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.models.models import ActionCard, Shop, User
from juli_backend.orm_base import Base
from juli_backend.repositories.decisions import ActionCardsRepo


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="This module proves Postgres-only partial/full unique constraints; it "
    "skips cleanly without a reachable DATABASE_URL.",
)


@pytest.fixture(scope="module")
def _disposable_postgres_url():
    base_url = _database_url()
    if not base_url.startswith("postgresql"):
        yield None
        return

    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_ac_subject_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        yield disposable_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _schema(_disposable_postgres_url):
    """Create every table once for the module -- `Base.metadata.create_all`,
    not a full Alembic upgrade: this proves the ORM-declared constraints
    (the same declarations the migration also makes), which is what every
    test in this module is actually about."""
    if _disposable_postgres_url is None:
        yield
        return
    engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    Base.metadata.create_all(engine, checkfirst=True)
    engine.dispose()
    yield


@pytest.fixture
def session(_disposable_postgres_url) -> Session:
    engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()
    engine.dispose()


def _seed_shop(session: Session) -> uuid.UUID:
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
    session.add(Shop(id=shop_id, user_id=user_id, shop_name="Subject Constraint Test Shop"))
    session.commit()
    return shop_id


def _new_card(
    shop_id: uuid.UUID,
    *,
    workflow_key: str = "optimize_product_2",
    status: str = "active",
    subject_type: str | None = None,
    subject_id: str | None = None,
    revision: int | None = None,
    supersedes_card_id: uuid.UUID | None = None,
    title: str = "Test card",
) -> ActionCard:
    kwargs: dict = {
        "id": uuid.uuid4(),
        "shop_id": shop_id,
        "workflow_key": workflow_key,
        "priority": 1,
        "severity": "warning",
        "title": title,
        "status": status,
    }
    if subject_type is not None:
        kwargs["subject_type"] = subject_type
    if subject_id is not None:
        kwargs["subject_id"] = subject_id
    if revision is not None:
        kwargs["revision"] = revision
    if supersedes_card_id is not None:
        kwargs["supersedes_card_id"] = supersedes_card_id
    return ActionCard(**kwargs)


class TestOneActiveCardPerSubjectAndChainedRevisions:
    """AC4 (#1701): a second ACTIVE card for the same (shop, workflow,
    subject) is rejected by the partial unique; a chained revision, once the
    predecessor is no longer active, succeeds."""

    def test_one_active_card_per_subject_and_chained_revisions(self, session):
        shop_id = _seed_shop(session)
        first = _new_card(
            shop_id,
            subject_type="product",
            subject_id=str(uuid.uuid4()),
            status="active",
            title="First pass",
        )
        session.add(first)
        session.commit()

        # A second ACTIVE card for the SAME (shop, workflow, subject) is
        # rejected by uq_action_cards_active_shop_workflow_subject -- given a
        # DIFFERENT revision than `first`'s (2, vs `first`'s default of 1) so
        # this collision is isolated to the PARTIAL unique alone. Sharing
        # `first`'s revision would ALSO collide on the full chain unique
        # (`uq_action_cards_shop_workflow_subject_revision`), which would
        # make this assertion pass for the wrong reason -- confirmed by hand
        # while writing this test: dropping only the partial index and
        # re-running with matching revisions left this raising IntegrityError
        # anyway, from the full unique alone.
        collision = _new_card(
            shop_id,
            subject_type=first.subject_type,
            subject_id=first.subject_id,
            status="active",
            revision=2,
            title="Colliding second pass",
        )
        session.add(collision)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Retire the first card, then a chained revision succeeds: same
        # subject, revision 2, supersedes_card_id pointing at the first.
        first.status = "approved"
        session.commit()

        second = _new_card(
            shop_id,
            subject_type=first.subject_type,
            subject_id=first.subject_id,
            status="active",
            revision=2,
            supersedes_card_id=first.id,
            title="Second pass",
        )
        session.add(second)
        session.commit()  # must not raise

        persisted = session.get(ActionCard, second.id)
        assert persisted is not None
        assert persisted.revision == 2
        assert persisted.supersedes_card_id == first.id


class TestFullUniqueCoversTheWholeChain:
    """The full unique on (shop, workflow, subject, revision) is a distinct
    constraint from the partial one above -- proven by showing it rejects a
    DUPLICATE revision even when neither row is active (a case the partial
    unique, filtered to status='active', would not catch)."""

    def test_duplicate_revision_rejected_even_when_both_rows_are_inactive(self, session):
        shop_id = _seed_shop(session)
        subject_id = str(uuid.uuid4())
        first = _new_card(
            shop_id, subject_type="product", subject_id=subject_id, status="dismissed", revision=1
        )
        session.add(first)
        session.commit()

        duplicate = _new_card(
            shop_id, subject_type="product", subject_id=subject_id, status="dismissed", revision=1
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestLegacyUniqueDroppedAndReplacementsPresent:
    """Asserted against the live Postgres catalog (`pg_indexes` /
    `information_schema`), never against the migration's own source text --
    a test that reads the migration file is a test of the test."""

    def test_uq_action_cards_shop_workflow_is_gone_from_the_catalog(self, _disposable_postgres_url):
        engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
        try:
            insp = inspect(engine)
            unique_names = {u["name"] for u in insp.get_unique_constraints("action_cards")}
            index_names = {i["name"] for i in insp.get_indexes("action_cards")}
            assert "uq_action_cards_shop_workflow" not in unique_names
            assert "uq_action_cards_shop_workflow" not in index_names

            assert "uq_action_cards_shop_workflow_subject_revision" in unique_names
            full_unique = next(
                u
                for u in insp.get_unique_constraints("action_cards")
                if u["name"] == "uq_action_cards_shop_workflow_subject_revision"
            )
            assert full_unique["column_names"] == [
                "shop_id",
                "workflow_key",
                "subject_type",
                "subject_id",
                "revision",
            ]

            partial = next(
                i
                for i in insp.get_indexes("action_cards")
                if i["name"] == "uq_action_cards_active_shop_workflow_subject"
            )
            assert partial["unique"] is True
            assert partial["column_names"] == [
                "shop_id",
                "workflow_key",
                "subject_type",
                "subject_id",
            ]
        finally:
            engine.dispose()


class TestCoexistenceWithTheUnmodifiedWriter:
    """The genuine hazard the release-evidence plan names: dropping the
    single-key unique while the one production writer
    (`ActionCardsRepo.upsert` via `services/action_cards/persist.py`, which
    names neither `subject_type` nor `subject_id`) still only ever produces
    the SAME constant default for both columns. Proven here against the
    REAL repository, not a hand-built row -- two concurrent-shaped upserts
    for the SAME (shop, workflow_key) from two different "candidates" must
    still collide into ONE row, exactly like the dropped constraint gave
    them."""

    @pytest.mark.asyncio
    async def test_unmodified_upsert_still_collapses_to_one_row_per_shop_workflow(
        self, _disposable_postgres_url, session
    ):
        shop_id = _seed_shop(session)

        engine = create_async_engine(
            async_database_url(_disposable_postgres_url), poolclass=NullPool
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as async_session:
                repo = ActionCardsRepo(async_session)
                first = await repo.upsert(
                    shop_id=shop_id,
                    workflow_key="optimize_product_2",
                    priority=1,
                    severity="warning",
                    title="Candidate A",
                    description="",
                    recommendation_payload="{}",
                    status="active",
                )
                await async_session.commit()

                # A second scoring pass for the SAME workflow_key -- the one
                # production call shape, naming neither subject_type nor
                # subject_id -- must UPDATE the same row, never insert a
                # second one.
                second = await repo.upsert(
                    shop_id=shop_id,
                    workflow_key="optimize_product_2",
                    priority=1,
                    severity="warning",
                    title="Candidate A, re-scored",
                    description="",
                    recommendation_payload="{}",
                    status="active",
                )
                await async_session.commit()

                assert first.id == second.id
                assert second.title == "Candidate A, re-scored"
        finally:
            await engine.dispose()

        with session.bind.connect() as conn:
            count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM action_cards WHERE shop_id = :shop_id "
                    "AND workflow_key = 'optimize_product_2'"
                ),
                {"shop_id": shop_id},
            ).scalar_one()
        assert count == 1
