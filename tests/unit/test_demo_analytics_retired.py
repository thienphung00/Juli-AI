"""GET /v1/demo/analytics is retired (fast track P61-D, owner D72.5, 2026-10-21).

It answers 410 Gone with a short body, touches no database or cache, and no worker
or route reads DEMO_REFERENCE_SHOP_ID any more.
"""

from __future__ import annotations

import re
from pathlib import Path

from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "src" / "juli_backend"


async def test_the_route_answers_410_gone_without_any_session(monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    monkeypatch.delenv("DEMO_REFERENCE_SHOP_ID", raising=False)
    app = create_app()

    async def _no_session():  # pragma: no cover - must not be reached
        raise AssertionError("the retired route opened a database session")
        yield

    app.dependency_overrides[get_session] = _no_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plain = await client.get("/v1/demo/analytics")
        ranged = await client.get("/v1/demo/analytics?range=7d")

    for response in (plain, ranged):
        assert response.status_code == 410
        assert "retired" in response.json()["detail"]


def test_no_backend_code_reads_the_reference_shop_variable():
    literal = re.compile(r"[\"']DEMO_REFERENCE_SHOP_ID[\"']")
    hits = [
        str(path.relative_to(BACKEND))
        for path in BACKEND.rglob("*.py")
        if literal.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == [], f"still read: {hits}"


def test_the_retired_beats_and_tasks_are_gone():
    import importlib.util

    for module in ("analytics_backfill_topup", "mock_analytics_reconcile", "shop_kpi_reconcile"):
        assert importlib.util.find_spec(f"juli_backend.workers.tasks.{module}") is None
