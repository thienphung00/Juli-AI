"""Composition: the analytics engine (T1) and the LLM gate ports (T2), wired for one run.

Everything that names T1's or T2's Python API lives in this file, behind :class:`Engine` and
:class:`PortsFactory`, so the routes and the runner are tested with fakes and the integration
re-points one file.

- T1 ``juli_backend.services.analytics_agent``: ``TEMPLATES``, ``AskRequest``, ``run``, and a
  per-platform ``LabelTable`` (contract §T1). Imported lazily: the route module must import
  while T1 is not on the branch.
- T2 ``juli_backend.services.llm_gate``: the Anthropic API (``LLMPort``) and the TypeSafe Jev API
  (``JevPort``) behind the gate. Each run gets its own pair, bound to the shop.
- Analysis sessions are read-only at the database: ``default_transaction_read_only`` is set on
  the connection before the shop scope (:func:`read_only_session_factory`).
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.database.tenant_context import with_shop_scope


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    label_vi: str


@dataclass(frozen=True)
class Ports:
    llm: Any
    jev: Any


class Engine(Protocol):
    def templates(self) -> list[TemplateInfo]: ...

    async def run(
        self,
        request: Mapping[str, Any],
        *,
        read_session_factory: Callable[[], Any],
        llm: Any,
        jev: Any,
        sink: Any,
    ) -> Any: ...


class PortsFactory(Protocol):
    async def __call__(
        self, *, shop_id: uuid.UUID, platform: str, write_factory: async_sessionmaker[AsyncSession]
    ) -> Ports: ...


class EngineUnavailable(RuntimeError):
    """T1 / T2 is not importable here (the branch before integration)."""


# -- read-only analysis sessions ---------------------------------------------------------------


def _begin_read_only(session: Any, transaction: Any, connection: Any) -> None:
    """``after_begin``: make THIS transaction read-only (Postgres; SQLite has no such mode).

    Per transaction, never ``default_transaction_read_only``: production reaches Postgres
    through Supavisor, and a session-level setting could stay on a pooled server connection.
    """
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")


def read_only_session_factory(
    factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID
) -> Callable[[], Any]:
    """Sessions the engine reads with: read-only at the database, in the shop's scope.

    Every transaction the session begins -- the first and any after a commit -- runs
    ``SET TRANSACTION READ ONLY`` as its first statement (:func:`_begin_read_only`), so each
    write fails with ``25006 read_only_sql_transaction`` and nothing outlives the transaction.
    """

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            event.listen(session.sync_session, "after_begin", _begin_read_only)
            async with with_shop_scope(session, shop_id):
                yield session

    return _session


# -- T1 ----------------------------------------------------------------------------------------


def _analytics_agent() -> Any:
    try:
        # by name: T1 lands in the batch beside this track (mypy must pass before and after)
        analytics_agent = importlib.import_module("juli_backend.services.analytics_agent")
    except ImportError as exc:  # pragma: no cover - only before T1 lands
        raise EngineUnavailable("analytics_agent is not installed") from exc
    return analytics_agent


def _labels_for(module: Any, platform: str) -> Any:
    """The engine's ``LabelTable`` for this platform (T1 ships both)."""
    for name in ("label_table", "labels_for"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn(platform)
    tables = getattr(module, "LABELS", None)
    if isinstance(tables, Mapping):
        return tables[platform]
    raise EngineUnavailable("analytics_agent has no label table")


class AnalyticsAgentEngine:
    """The real engine: ``analytics_agent.run``."""

    def templates(self) -> list[TemplateInfo]:
        return [TemplateInfo(t.key, t.label_vi) for t in _analytics_agent().TEMPLATES]

    async def run(
        self,
        request: Mapping[str, Any],
        *,
        read_session_factory: Callable[[], Any],
        llm: Any,
        jev: Any,
        sink: Any,
    ) -> Any:
        module = _analytics_agent()
        req = module.AskRequest(**dict(request))
        return await module.run(
            req,
            read_session_factory=read_session_factory,
            llm=llm,
            jev=jev,
            sink=sink,
            labels=_labels_for(module, str(request["platform"])),
        )


# -- T2 ----------------------------------------------------------------------------------------


async def gate_ports(
    *, shop_id: uuid.UUID, platform: str, write_factory: async_sessionmaker[AsyncSession]
) -> Ports:
    """The LLMPort (Anthropic) and JevPort (TypeSafe) behind T2's gate, for one run.

    The gate writes its ``llm_call_log`` rows, so it logs on WRITABLE sessions of its own
    (``ports.CommittingCallLog``), never on the read-only analysis session.
    """
    from juli_backend.services.juli_agent_api.ports import open_ports

    try:
        llm, jev = await open_ports(write_factory, shop_id)
    except ImportError as exc:  # pragma: no cover - only before T2 lands
        raise EngineUnavailable("llm_gate has no Anthropic / TypeSafe doors yet (T2)") from exc
    return Ports(llm=llm, jev=jev)


# -- overridable process defaults (tests set fakes) ----------------------------------------------

_engine: Engine | None = None
_ports: PortsFactory | None = None


def get_engine() -> Engine:
    return _engine if _engine is not None else AnalyticsAgentEngine()


def set_engine(engine: Engine | None) -> None:
    global _engine
    _engine = engine


def get_ports_factory() -> PortsFactory:
    return _ports if _ports is not None else gate_ports


def set_ports_factory(factory: PortsFactory | None) -> None:
    global _ports
    _ports = factory


__all__ = [
    "AnalyticsAgentEngine",
    "Engine",
    "EngineUnavailable",
    "Ports",
    "PortsFactory",
    "TemplateInfo",
    "gate_ports",
    "get_engine",
    "get_ports_factory",
    "read_only_session_factory",
    "set_engine",
    "set_ports_factory",
]
