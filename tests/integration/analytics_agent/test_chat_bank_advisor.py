"""The bank's opt-in PAID set (owner decision #109): `advisor_cases.json`, about twenty questions
that only the real parser, router and advisor can answer (the advise path, the create path, the
real parse of messages that failed in the owner's tests). Same checks as the bank, on the
seeded shop in Postgres, with the production ports.

NOT run by default: it needs the `live` marker selection AND `JULI_CHAT_BANK_PAID=1`, plus real
LLM / router credentials. Estimate the cost first and ask before running (owner rule):

    PYTHONPATH=backend/src:. python scripts/chat_bank_advisor_cost.py
    JULI_CHAT_BANK_PAID=1 fasttrack/bin/pg-test.sh \
        tests/integration/analytics_agent/test_chat_bank_advisor.py -m live
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.analytics_agent import AskRequest, run, shopee_labels
from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from juli_backend.services.analytics_agent.data_service import ServiceData
from juli_backend.services.juli_agent_api.ports import open_ports
from tests.support.consent import grant_llm_consent, grant_service_consent
from tests.support.postgres import requires_postgres
from tests.unit.analytics_agent.bank import combo_eval, paid_sample, runner
from tests.unit.analytics_agent.bank.test_chat_bank import _param
from tests.unit.analytics_agent.bank.world import seed_into
from tests.unit.analytics_agent.fakes import ListSink

PAID_ENV = "JULI_CHAT_BANK_PAID"
pytestmark = [
    requires_postgres,
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get(PAID_ENV) != "1",
        reason=f"paid set: opt in with {PAID_ENV}=1 after the cost estimate",
    ),
]

CASES = runner.load_cases(runner.ADVISOR_FILE)
SAMPLE = paid_sample.load()  # the stratified sample of the generated combinations


@pytest_asyncio.fixture
async def world():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()
    write = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    async with write() as seed:
        sid = await seed_into(seed)
        await grant_service_consent(seed, sid)
        await grant_llm_consent(seed, sid)
        await seed.commit()

    @asynccontextmanager
    async def factory():
        s: AsyncSession = write()
        try:
            yield s
        finally:
            await s.close()

    try:
        yield sid, factory, write
    finally:
        await outer.rollback()
        await conn.close()
        await engine.dispose()


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
async def test_paid_case(case: dict[str, Any], world: Any) -> None:
    sid, factory, write = world
    llm, jev = await open_ports(write, sid)
    sink = ListSink()
    res = await run(
        AskRequest(
            shop_id=sid, platform="shopee", text=case["question"], as_of=runner.DEFAULT_AS_OF
        ),
        llm=llm,
        jev=jev,
        sink=sink,
        labels=shopee_labels(),
        data=ServiceData(factory, sid),
        card_engine=ServiceCardEngine(factory, sid),
    )
    out = runner.Outcome(sink.events, list(res.stop_reasons), [])
    problems = await runner.check(out, case, factory, sid)
    assert not problems, f"{case['id']} ({case['question']!r}) cost ${res.cost_usd:.4f}:\n  - " + (
        "\n  - ".join(problems)
    )


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in SAMPLE])
async def test_paid_sample(case: dict[str, Any], world: Any) -> None:
    """The real parse of a generated combination in a seller's wording; the free bank's oracle
    and gap rules judge it (a known gap xfails as in the free bank)."""
    sid, factory, write = world
    llm, jev = await open_ports(write, sid)
    sink = ListSink()
    res = await run(
        AskRequest(
            shop_id=sid, platform="shopee", text=case["question"], as_of=runner.DEFAULT_AS_OF
        ),
        llm=llm,
        jev=jev,
        sink=sink,
        labels=shopee_labels(),
        data=ServiceData(factory, sid),
        card_engine=ServiceCardEngine(factory, sid),
    )
    out = runner.Outcome(sink.events, list(res.stop_reasons), [])
    combo = {**combo_eval.case_of(case["combo_id"]), "expect": case["expect"]}
    problems = await runner.check(out, combo, factory, sid)
    v = combo_eval.judge(combo, out, problems)
    if v.status == "mismatch":
        if v.bucket != "correct_refusal":  # the mismatch rule (combos.MISMATCH_RULE)
            pytest.xfail(f"mismatch outcome: {v.bucket}")
        return
    assert v.status != "fail", f"{case['id']} ({case['question']!r}) ${res.cost_usd:.4f}:\n  - " + (
        "\n  - ".join(v.unexplained)
    )
    if v.status == "gap":
        pytest.xfail("gap: " + ", ".join(v.rules))
