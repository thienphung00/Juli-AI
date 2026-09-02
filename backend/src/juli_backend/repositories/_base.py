"""The one shape every repository in this package follows.

Read this before adding or editing a repository. The rules are short, and the
rest of the package is just these rules applied to one aggregate at a time.

* **A repository borrows the caller's ``AsyncSession``.** It ``flush()``es so
  generated ids and server defaults become visible, and it never ``commit()``s
  or ``rollback()``s. The transaction belongs to the service or request that
  opened the session; a repository that commits steals that decision.
* **Tenant scoping is structural, not remembered.** Anything that lives under a
  shop extends :class:`ShopScopedRepo`, and every read and write goes through
  :meth:`ShopScopedRepo._scoped`, so ``shop_id`` cannot be forgotten. A
  hand-written ``Model.shop_id == shop_id`` in a subclass is the bug class this
  base removes (ADR-046, #28).
* **``get`` raises, ``find`` returns ``None``.** The verb tells the caller what
  to expect. :class:`NotFound` messages name the entity and its id, and nothing
  else -- never a token, never a payload.
* **Time is naive UTC at the persistence edge.** Timestamp columns are declared
  ``TIMESTAMP WITHOUT TIME ZONE``; asyncpg rejects an aware datetime there at
  flush time, while SQLite and psycopg2 silently accept it (#1138). Use
  :func:`utc_now_naive` for every ``now`` a repository writes.
* **Upsert is idempotent and refuses stale data.** :meth:`ShopScopedRepo.upsert`
  matches on the natural key in ``_lookup_attrs``, skips the write when the
  incoming ``update_time`` is not newer than the stored one, and survives a
  concurrent insert of the same key. Subclasses declare the key; they do not
  reimplement the loop.

Repositories are thin by design. Business rules (what a status transition
means, which merchant owns which capability) live in the service layer and
arrive here already decided.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from juli_backend.database.exceptions import NotFound

EntityT = TypeVar("EntityT")


def utc_now_naive() -> datetime:
    """Current UTC time with the tzinfo stripped, ready for a naive column (#1138)."""
    return datetime.now(UTC).replace(tzinfo=None)


class SessionRepo:
    """Base for every repository: holds the session and the query helpers.

    The helpers exist so subclasses read as *what* they fetch, not *how*
    SQLAlchemy returns it. ``execute(...).scalar_one_or_none()`` written out
    thirty times is thirty places to get the result-unwrapping wrong.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _add(self, entity: EntityT) -> EntityT:
        """Stage ``entity`` and flush so its id and server defaults are populated."""
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def _one_or_none(self, stmt: Select[tuple[EntityT]]) -> EntityT | None:
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _all(self, stmt: Select[tuple[EntityT]]) -> list[EntityT]:
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _exists(self, stmt: Select[Any]) -> bool:
        result = await self._session.execute(stmt.limit(1))
        return result.first() is not None


class ShopScopedRepo(SessionRepo, Generic[EntityT]):
    """Repository for an entity that belongs to exactly one shop.

    Subclasses set ``_model`` and, when the entity is synced from an external
    source, ``_lookup_attrs`` -- the column(s) forming the natural key that
    :meth:`upsert` matches on. Everything else is inherited.
    """

    _model: ClassVar[type[Any]]
    _lookup_attrs: ClassVar[tuple[str, ...]] = ()

    # -- query building -----------------------------------------------------

    def _scoped(self, shop_id: uuid.UUID, *criteria: Any) -> Select[tuple[EntityT]]:
        """``SELECT`` on ``_model`` filtered to ``shop_id`` plus any extra criteria."""
        return select(self._model).where(self._model.shop_id == shop_id, *criteria)

    async def _paginate(
        self,
        stmt: Select[tuple[EntityT]],
        *,
        sort_column: InstrumentedAttribute[Any],
        after: uuid.UUID | None,
        limit: int,
    ) -> list[EntityT]:
        """Keyset pagination: ``sort_column`` descending, ``id`` descending as tiebreak.

        ``after`` is the id of the last row the caller already has. An unknown
        cursor is treated as "no cursor" rather than an error, so a client
        holding a cursor to a since-deleted row still gets the first page.
        """
        if after is not None:
            cursor = await self._session.get(self._model, after)
            if cursor is not None:
                cursor_sort_value = getattr(cursor, sort_column.key)
                stmt = stmt.where(
                    or_(
                        sort_column < cursor_sort_value,
                        and_(sort_column == cursor_sort_value, self._model.id < cursor.id),
                    )
                )
        stmt = stmt.order_by(sort_column.desc(), self._model.id.desc()).limit(limit)
        return await self._all(stmt)

    # -- reads --------------------------------------------------------------

    async def list(
        self,
        shop_id: uuid.UUID,
        *,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[EntityT]:
        """Newest first, keyset-paginated on ``(created_at, id)``."""
        return await self._paginate(
            self._scoped(shop_id),
            sort_column=self._model.created_at,
            after=after,
            limit=limit,
        )

    async def get(self, shop_id: uuid.UUID, entity_id: uuid.UUID) -> EntityT:
        """Return the entity or raise :class:`NotFound`.

        A row that exists under a *different* shop is reported as missing, not
        as forbidden: the caller learns nothing about other tenants' ids.
        """
        entity = await self._session.get(self._model, entity_id)
        if entity is None or entity.shop_id != shop_id:
            raise NotFound(f"{self._model.__name__} {entity_id} not found")
        return entity

    # -- writes -------------------------------------------------------------

    async def upsert(self, *, shop_id: uuid.UUID, **values: Any) -> EntityT:
        """Insert or update by natural key, refusing to overwrite newer data.

        ``values`` must contain every column in ``_lookup_attrs``. When a row
        with that key exists and carries an ``update_time`` at or after the
        incoming one, the stored row is returned untouched -- a redelivered or
        out-of-order sync message must not roll a record backwards.

        The insert runs inside a savepoint so a concurrent writer landing the
        same key first turns into an update instead of a failed transaction.
        """
        if not self._lookup_attrs:
            raise NotImplementedError(f"{type(self).__name__} does not support upsert")

        natural_key = self._natural_key(values)
        match_stmt = self._scoped(
            shop_id,
            *(getattr(self._model, name) == value for name, value in natural_key.items()),
        )

        existing = await self._one_or_none(match_stmt)
        if existing is not None:
            return await self._apply_if_newer(existing, values)

        entity = self._model(id=uuid.uuid4(), shop_id=shop_id, **values)
        try:
            async with self._session.begin_nested():
                self._session.add(entity)
                await self._session.flush()
        except IntegrityError:
            existing = await self._one_or_none(match_stmt)
            if existing is None:
                raise
            return await self._apply_if_newer(existing, values)
        return entity

    def _natural_key(self, values: Mapping[str, Any]) -> dict[str, Any]:
        missing = [name for name in self._lookup_attrs if values.get(name) in (None, "")]
        if missing:
            raise ValueError(
                f"{type(self).__name__}.upsert requires {', '.join(self._lookup_attrs)}; "
                f"missing {', '.join(missing)}"
            )
        return {name: values[name] for name in self._lookup_attrs}

    async def _apply_if_newer(self, existing: EntityT, values: Mapping[str, Any]) -> EntityT:
        if _incoming_is_stale(existing, values):
            return existing
        for name, value in values.items():
            setattr(existing, name, value)
        await self._session.flush()
        return existing


def _incoming_is_stale(existing: Any, values: Mapping[str, Any]) -> bool:
    incoming = values.get("update_time")
    stored = getattr(existing, "update_time", None)
    return incoming is not None and stored is not None and incoming <= stored


__all__ = ["EntityT", "SessionRepo", "ShopScopedRepo", "utc_now_naive"]
