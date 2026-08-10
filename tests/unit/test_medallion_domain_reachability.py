"""Contract test: every registered bronze domain is reachable end to end.

Guards against the twofold #880 failure mode: a medallion domain gets added
to ``BRONZE_SUPPORTED_RESOURCE_ATTRS`` (targeted_fetch_executor.py), fully
unit-tested in isolation, reviewed, merged, and deployed — and changes
nothing in production, because a downstream link in the chain never got
wired up to consume it:

  1. First gap: ``BronzeAppendTracker`` gained ``ctor_row_ids`` /
     ``live_hours_row_ids`` and a ``SilverAnalyticsPromoter`` was written,
     but ``SharedComputeOrchestrator._default_silver_stage`` dispatches on
     ``order_row_ids`` / ``return_row_ids`` **by name**, hardcoded. Nothing
     read the new fields. Bronze would fill; silver stayed empty.
  2. Second gap (after fixing the first): ``BRONZE_SUPPORTED_RESOURCE_ATTRS``
     was extended and planner entries added, but
     ``mock_analytics_reconcile.py::_make_hourly_gap_fetch_plan`` hardcoded
     its resource list to ``orders`` + ``analytics_shop``. Nothing ever
     requested the new domains.

Both times the full unit suite passed (2400+ tests): every *piece* was
individually correct and individually tested. Nothing tested the *chain*.

**This test is data-driven off the live registry.** It iterates
``BRONZE_SUPPORTED_RESOURCE_ATTRS`` itself, never a literal
``["orders", "returns", "ctor", "live_hours"]`` list. Add a fifth domain to
that frozenset tomorrow and wire nothing downstream, and this test fails on
its own with zero edits here.

Link-by-link method — documented per repo convention so a green result is
never mistaken for more proof than it actually is:

  - **Link 1** (sync fn registered) — BEHAVIORAL: real dict membership +
    callable check against the live ``_SYNC_BY_RESOURCE_ATTR``.
  - **Link 2** (bronze append route exists) — STRUCTURAL: source-text
    inspection of ``targeted_fetch_bronze_handoff.py`` for a
    ``tracker.<field>.append(`` call. A genuine behavioral drive here would
    require per-domain fixture payloads and literal channel strings
    (``"tiktok.orders.raw"`` etc.) that cannot be derived from the registry
    alone, so this link is intentionally structural.
  - **Link 3** (tracker field exists) — BEHAVIORAL: real
    ``dataclasses.fields(BronzeAppendTracker)`` introspection against the
    live class.
  - **Link 4** (silver stage consumes the tracker field) — BEHAVIORAL: drives
    the real ``SharedComputeOrchestrator._default_silver_stage`` with a
    tracker carrying one live row id for the domain under test (every other
    field empty) against a recording fake session, and asserts
    ``session.execute`` was actually called. If the domain's
    ``if bronze_tracker.<field>:`` branch doesn't exist, ``execute()`` is
    never invoked for that call and the assertion fails — this is exactly
    how #880's first gap would have been caught.
  - **Link 5** (a fetch-plan builder requests it) — BEHAVIORAL: calls the
    real ``_make_hourly_gap_fetch_plan`` (mock_analytics_reconcile.py) and
    the real ``plan_targeted_fetch`` for every catalog id in the material
    webhook matrix, then checks the ``resource_attr`` of the actual
    ``FetchResource`` objects those plan builders produce — not just the
    planner's static resource table. This is exactly how #880's second gap
    would have been caught.
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from typing import Any

import pytest

from juli_backend.services.cdp_speed import targeted_fetch_bronze_handoff as bronze_handoff_module
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeOrchestrator
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import BronzeAppendTracker
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    _SYNC_BY_RESOURCE_ATTR,
    BRONZE_SUPPORTED_RESOURCE_ATTRS,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    _MATERIAL_FETCH_MATRIX,
    plan_targeted_fetch,
)
from juli_backend.workers.tasks.mock_analytics_reconcile import _make_hourly_gap_fetch_plan


def _tracker_field_for_resource_attr(resource_attr: str) -> str:
    """Resolve the BronzeAppendTracker field for a resource_attr by naming convention.

    Tries the exact ``<attr>_row_ids`` name first (matches ctor/live_hours),
    then the singularized form (matches orders -> order_row_ids, returns ->
    return_row_ids). Raises with a clear message — never a silent skip —
    when neither exists, because "no field found" is itself part of the gap
    this test exists to catch.
    """
    candidates = [f"{resource_attr}_row_ids"]
    if resource_attr.endswith("s"):
        candidates.append(f"{resource_attr[:-1]}_row_ids")

    tracker_fields = {f.name for f in dataclasses.fields(BronzeAppendTracker)}
    for candidate in candidates:
        if candidate in tracker_fields:
            return candidate

    raise AssertionError(
        f"BronzeAppendTracker has no row-ids field for resource_attr "
        f"{resource_attr!r}. Tried {candidates}. Existing fields: "
        f"{sorted(tracker_fields)}. Add a matching <domain>_row_ids field to "
        f"BronzeAppendTracker (targeted_fetch_bronze_handoff.py)."
    )


class _FakeResult:
    """Empty result stub: every promotion helper does zero real work either
    way, so the only signal that matters is whether execute() was attempted."""

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return []

    def __iter__(self) -> Any:
        return iter(())


class _RecordingSession:
    """Fake AsyncSession that records execute()/flush() calls without a DB."""

    def __init__(self) -> None:
        self.execute_calls: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.execute_calls.append(statement)
        return _FakeResult()

    async def flush(self) -> None:
        return None


@pytest.mark.parametrize("resource_attr", sorted(BRONZE_SUPPORTED_RESOURCE_ATTRS))
class TestMedallionDomainReachability:
    """One parametrized case per registered bronze domain — registry-driven.

    ``BRONZE_SUPPORTED_RESOURCE_ATTRS`` is read live at collection time via
    ``sorted(...)`` above; no domain name is spelled out anywhere in this
    file.
    """

    def test_link1_sync_function_registered(self, resource_attr: str) -> None:
        """BEHAVIORAL: a callable sync function exists for this resource_attr."""
        sync_fn = _SYNC_BY_RESOURCE_ATTR.get(resource_attr)
        assert sync_fn is not None, (
            f"No sync function registered in _SYNC_BY_RESOURCE_ATTR for "
            f"{resource_attr!r}. BRONZE_SUPPORTED_RESOURCE_ATTRS declares it "
            f"bronze-supported but nothing fetches it."
        )
        assert callable(sync_fn)

    def test_link2_bronze_append_route_exists(self, resource_attr: str) -> None:
        """STRUCTURAL: the bronze handoff appends rows for this domain's tracker field.

        See module docstring — source-text inspection, not a live handoff
        call, because driving the real handoff needs per-domain payloads and
        channel strings that aren't derivable from the registry alone.
        """
        field = _tracker_field_for_resource_attr(resource_attr)
        source = inspect.getsource(bronze_handoff_module)
        needle = f"tracker.{field}.append("
        assert needle in source, (
            f"targeted_fetch_bronze_handoff.py has no `{needle}` call. "
            f"{resource_attr!r} is registered as bronze-supported but has no "
            f"bronze append route wired to its tracker field."
        )

    def test_link3_tracker_field_exists(self, resource_attr: str) -> None:
        """BEHAVIORAL: BronzeAppendTracker carries a row-ids field for this domain."""
        field = _tracker_field_for_resource_attr(resource_attr)
        tracker = BronzeAppendTracker()
        assert hasattr(tracker, field)
        assert getattr(tracker, field) == []

    async def test_link4_silver_stage_consumes_tracker_field(self, resource_attr: str) -> None:
        """BEHAVIORAL: _default_silver_stage attempts promotion for this domain.

        Reproduces #880 gap #1: BronzeAppendTracker/SilverAnalyticsPromoter
        existed with nothing reading the new fields. Reverting the
        ``if bronze_tracker.<field>:`` branch for a domain (with every other
        tracker field empty) drops session.execute() to zero calls here, and
        this assertion fails.
        """
        field = _tracker_field_for_resource_attr(resource_attr)
        tracker = BronzeAppendTracker()
        setattr(tracker, field, [uuid.uuid4()])

        session = _RecordingSession()
        shop_id = uuid.uuid4()

        await SharedComputeOrchestrator._default_silver_stage(session, shop_id, tracker)

        assert session.execute_calls, (
            f"SharedComputeOrchestrator._default_silver_stage never called "
            f"session.execute() when BronzeAppendTracker.{field} carried a "
            f"row id and every other tracker field was empty. The silver "
            f"stage does not consume {resource_attr!r} — bronze would fill "
            f"and silver would stay empty (#880 gap #1)."
        )

    def test_link5_a_fetch_plan_builder_requests_it(self, resource_attr: str) -> None:
        """BEHAVIORAL: at least one production fetch-plan builder requests this domain.

        Reproduces #880 gap #2: BRONZE_SUPPORTED_RESOURCE_ATTRS and the
        planner catalog were extended but mock_analytics_reconcile.py's
        hourly gap plan hardcoded its resource list and never asked for the
        new domains. Checked against the *real* plan builders (hourly gap
        plan + material webhook matrix), not just the planner's static
        resource table — a domain reachable only from a plan builder nothing
        calls in production is still a dead registration.
        """
        hourly_attrs = {
            resource.resource_attr
            for resource in _make_hourly_gap_fetch_plan("reachability-test-shop").resources
        }

        material_attrs: set[str] = set()
        for catalog_id in _MATERIAL_FETCH_MATRIX:
            plan = plan_targeted_fetch(shop_id="reachability-test-shop", catalog_id=catalog_id)
            material_attrs.update(resource.resource_attr for resource in plan.resources)

        reachable = hourly_attrs | material_attrs
        assert resource_attr in reachable, (
            f"{resource_attr!r} is bronze-supported but no production "
            f"fetch-plan builder requests it. hourly gap plan resource_attrs="
            f"{sorted(hourly_attrs)}, material webhook matrix "
            f"resource_attrs={sorted(material_attrs)}. A domain reachable "
            f"only from a plan builder nothing calls in production is still "
            f"a dead registration (#880 gap #2)."
        )
