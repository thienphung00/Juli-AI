"""AC-10.2 (fast track P10-B), contract §4: the cover-image flow.

- the four photo checks (two exact, two heuristic) pass and fail as documented;
- a cover-image run, driven by the real ``WorkflowRunner`` with the photo
  playbook and planner, reads, then waits (``awaiting = "photo"``, narration
  "Đang chờ ảnh từ bạn", the current cover kept as "before"), resumes once the
  photo is stored, stages it, pauses for the ordinary consent, and on approval
  writes it as the cover (the rest of the gallery kept) with before/after
  recorded for Hoàn tác; a decline writes nothing;
- the photo request expires after 3 days (reaper: ``timed_out``), not before;
- the routes: 202/422/409/404 for the photo, ``awaiting`` on the run detail and
  list, the stored photos served by token.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from juli_backend.models.lever_flows import RunLeverFlow, RunLeverPhoto
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.orm_base import Base
from juli_backend.services import lever_flows
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.lever_flows import photo_checks, photos
from juli_backend.services.lever_flows.driver import FlowWiring, LeverFlowRunner
from juli_backend.workers.tasks import reaper
from tests.support.lever_flows import (
    CDN_URL,
    PRODUCT_ID,
    FakeProducts,
    api_client,
    multipart,
    png,
    resources,
    seed_run,
    seed_shop,
)

# --- the checks --------------------------------------------------------------------


def _by_key(report: photo_checks.PhotoReport) -> dict[str, bool]:
    return {check.key: check.ok for check in report.checks}


def test_a_square_large_plain_filled_photo_passes_every_check():
    report = photo_checks.check_photo(png())
    assert report.ok
    assert _by_key(report) == {
        "ratio": True,
        "size": True,
        "background": True,
        "product_fill": True,
    }
    assert report.content_type == "image/png"
    assert (report.width, report.height) == (1000, 1000)
    heuristic = {c.key for c in report.checks if c.heuristic}
    assert heuristic == {"background", "product_fill"}, "the two heuristics are marked"


def test_a_jpeg_passes_too():
    assert photo_checks.check_photo(png(fmt="JPEG")).ok


@pytest.mark.parametrize(
    ("image", "failing"),
    [
        (lambda: png(600, 600, product_box=(40, 40, 560, 560)), {"size"}),
        (lambda: png(1000, 800, product_box=(60, 60, 940, 740)), {"ratio"}),
        (lambda: png(product_box=(400, 400, 600, 600)), {"product_fill"}),
        (lambda: png(400, 400, noisy=True, product_box=None), {"size", "background"}),
    ],
)
def test_each_failing_check_is_reported_by_key(image, failing):
    report = photo_checks.check_photo(image())
    assert not report.ok
    assert {key for key, ok in _by_key(report).items() if not ok} >= failing
    assert all(check.label for check in report.checks), "every check carries its VI label"


def test_a_noisy_background_fails_the_background_check():
    report = photo_checks.check_photo(png(900, 900, noisy=True, product_box=(100, 100, 800, 800)))
    assert _by_key(report)["background"] is False


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        (b"", "Tệp trống"),
        (b"not an image at all", "Không đọc được ảnh"),
        (b"x" * (photo_checks.MAX_PHOTO_BYTES + 1), "Tệp lớn hơn 5 MB"),
    ],
)
def test_an_unusable_file_fails_the_file_check_only(data, detail):
    report = photo_checks.check_photo(data)
    assert [(c.key, c.ok, c.detail) for c in report.checks] == [("file", False, detail)]


def test_a_gif_is_not_accepted():
    report = photo_checks.check_photo(png(fmt="GIF"))
    assert [(c.key, c.ok) for c in report.checks] == [("file", False)]


def test_multipart_parsing_finds_the_file_part():
    content_type, body = multipart(b"PNGDATA")
    assert photos.parse_multipart_file(content_type, body) == b"PNGDATA"
    with pytest.raises(photos.MultipartError):
        photos.parse_multipart_file("application/json", b"{}")
    content_type, body = multipart(b"x", field="other")
    with pytest.raises(photos.MultipartError):
        photos.parse_multipart_file(content_type, body)


def test_only_tiktok_cdn_https_urls_are_fetched():
    assert photos.allowed_image_url(CDN_URL)
    assert not photos.allowed_image_url(CDN_URL.replace("https", "http"))
    assert not photos.allowed_image_url("https://evil.example.com/a.png")
    assert not photos.allowed_image_url("https://ibyteimg.com.evil.example/a.png")


def test_the_staged_uri_recorder_keeps_the_uri_on_the_sellers_photo():
    engine = create_engine(
        "sqlite://",
        execution_options={
            "schema_translate_map": {"ops": None, "bronze": None, "gold": None, "silver": None}
        },
    )
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    shop_id, run_id = uuid.uuid4(), uuid.uuid4()
    session.add(
        RunLeverPhoto(
            shop_id=shop_id,
            workflow_run_id=run_id,
            role="after",
            content_type="image/png",
            data=b"x",
            width=1,
            height=1,
            checks=[],
            public_token="t",
        )
    )
    session.commit()
    photos.SqlStagedUriRecorder(session, shop_id=shop_id, workflow_run_id=run_id)("tos-staged")
    row = session.execute(select(RunLeverPhoto)).scalar_one()
    assert row.tiktok_uri == "tos-staged"


# --- the run, end to end through the real runner -----------------------------------------


class ListRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, *, tool_name, tool_call_id, tiktok_product_id, writes) -> None:
        self.calls.append({"tool_name": tool_name, "writes": list(writes)})


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class Leg:
    """What the worker's ``_construct_runner`` builds for one leg of a photo run."""

    def __init__(self, session, run, flow, after_bytes, products, sink, *, staged, recorder):
        self.guard = ConcurrencyGuard(basis_snapshot=run.state.get("basis_snapshots", {}))
        res = resources(products)
        self.recorder = recorder or ListRecorder()
        self.fetched: list[str] = []
        self.executor = ProductToolExecutor(
            registry=_registry(),
            read_resources=res,
            write_resources=res,
            product_id=PRODUCT_ID,
            concurrency_guard=self.guard,
            product_detail=run.state.get("product_detail"),
            write_value_recorder=self.recorder,
            pending_image_bytes=after_bytes,
            staged_image_uri=staged[-1] if staged else None,
            on_image_staged=staged.append,
        )
        self.planner = lever_flows.PhotoPlanner(photo_ready=after_bytes is not None)
        runner = WorkflowRunner(
            llm_service=self.planner,
            tool_executor=self.executor,
            event_sink=sink,
            conversation_store=JsonbConversationStore(session),
            registry=_registry(),
            playbook=lever_flows.PHOTO_PLAYBOOK,
            concurrency_guard=self.guard,
        )

        def _detail():
            return self.guard.get_product_detail() or run.state.get("product_detail")

        def _fetch(url: str) -> bytes:
            self.fetched.append(url)
            return png(600, 600, product_box=(250, 250, 350, 350))

        self.flow_runner = LeverFlowRunner(
            runner,
            session=session,
            wiring=FlowWiring(flow=flow, playbook=lever_flows.PHOTO_PLAYBOOK, planner=self.planner),
            product_detail=_detail,
            fetch_image=_fetch,
        )

    @classmethod
    async def build(cls, session, run_id, products, sink, *, staged, recorder=None):
        run = await session.get(WorkflowRunRow, run_id)
        await session.refresh(run)
        flow = (
            await session.execute(
                select(RunLeverFlow).where(RunLeverFlow.workflow_run_id == run_id)
            )
        ).scalar_one()
        after = await photos.get_photo(session, run.shop_id, run_id, "after")
        after_bytes = after.data if after is not None else None
        return cls(
            session, run, flow, after_bytes, products, sink, staged=staged, recorder=recorder
        )


async def _start_photo_run(session):
    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product, lever="cover_image", flow_kind="photo")
    await session.commit()
    return shop, run


@pytest.mark.asyncio
async def test_a_cover_image_run_waits_for_the_photo_then_consents_then_writes_it(session):
    shop, run = await _start_photo_run(session)
    products, sink, staged = FakeProducts(), InMemoryEventSink(), []

    # Leg 1 (approve): read, look at the current photo, wait for the seller.
    leg1 = await Leg.build(session, run.id, products, sink, staged=staged)
    paused = await leg1.flow_runner.run(run.id, product_ref=PRODUCT_ID)
    await session.commit()

    assert paused.status == WorkflowRunStatus.WAITING_EXTERNAL
    row = await session.get(WorkflowRunRow, run.id)
    await session.refresh(row)
    assert row.status == "waiting_external"
    assert row.external_wait_reason == "photo"
    assert lever_flows.awaiting_of(row) == "photo"
    narrations = [
        e.payload.phase_narration for e in sink.events if e.event_type == "workflow.status"
    ]
    assert narrations[-1] == "Đang chờ ảnh từ bạn"
    assert [e.payload.tool_name for e in sink.events if e.event_type == "tool.completed"] == [
        "get_product_diagnoses",
        "get_product_information",
        "inspect_product_image",
    ]
    assert products.uploads == [] and products.edits == [], "nothing leaves before the photo"
    before = await photos.get_photo(session, shop.id, run.id, "before")
    assert before is not None and leg1.fetched == [CDN_URL], "the current cover is kept as before"
    assert (before.width, before.height) == (600, 600)

    # The seller's photo arrives (the route's job; see the route tests).
    await photos.save_photo(
        session,
        shop_id=shop.id,
        run_id=run.id,
        role="after",
        data=png(),
        report=photo_checks.check_photo(png()),
    )
    await session.commit()

    # Leg 2 (resume_lever_flow): stage the photo, pause for the ordinary consent.
    leg2 = await Leg.build(session, run.id, products, sink, staged=staged)
    waiting = await leg2.flow_runner.resume_after_external_wait(run.id)
    await session.commit()
    assert waiting.status == WorkflowRunStatus.WAITING_APPROVAL
    assert len(products.uploads) == 1 and staged == ["tos-new-cover"]
    assert products.edits == [], "the listing does not change before consent"
    approval = [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert approval[-1].payload.tool_name == "update_product_listing"
    assert lever_flows.awaiting_of(await session.get(WorkflowRunRow, run.id)) is None

    # Leg 3 (consent approved): the cover is replaced, the gallery kept.
    recorder = ListRecorder()
    leg3 = await Leg.build(session, run.id, products, sink, staged=staged, recorder=recorder)
    done = await leg3.flow_runner.resume(run.id, approved=True)
    await session.commit()

    assert done.status == WorkflowRunStatus.COMPLETED
    assert "Đã thay ảnh bìa" in (done.final_response or "")
    [edit] = products.edits
    assert edit["main_images"] == [{"uri": "tos-new-cover"}, {"uri": "tos-old-2"}]
    [call] = recorder.calls
    assert {w.field: (w.before, w.after) for w in call["writes"]} == {
        "main_images": (["tos-old-1", "tos-old-2"], ["tos-new-cover", "tos-old-2"])
    }, "before/after recorded, so Hoàn tác restores the old cover"
    types = {e.event_type for e in sink.events}
    assert types <= {
        "workflow.started",
        "workflow.status",
        "assistant.text",
        "tool.started",
        "tool.completed",
        "workflow.approval_required",
        "workflow.completed",
        "workflow.failed",
    }, "no new SSE event type"


@pytest.mark.asyncio
async def test_declining_the_new_cover_writes_nothing(session):
    shop, run = await _start_photo_run(session)
    products, sink, staged = FakeProducts(), InMemoryEventSink(), []
    await (await Leg.build(session, run.id, products, sink, staged=staged)).flow_runner.run(
        run.id, product_ref=PRODUCT_ID
    )
    await photos.save_photo(
        session,
        shop_id=shop.id,
        run_id=run.id,
        role="after",
        data=png(),
        report=photo_checks.check_photo(png()),
    )
    await session.commit()
    leg2 = await Leg.build(session, run.id, products, sink, staged=staged)
    await leg2.flow_runner.resume_after_external_wait(run.id)
    await session.commit()

    leg3 = await Leg.build(session, run.id, products, sink, staged=staged)
    done = await leg3.flow_runner.resume(run.id, approved=False)

    assert products.edits == []
    assert done.stop_reason == StopReason.CONFIRMATION_DECLINED
    assert "không thay ảnh" in (done.final_response or "")


@pytest.mark.asyncio
async def test_a_second_resume_of_a_run_no_longer_waiting_is_a_no_op(session):
    shop, run = await _start_photo_run(session)
    products, sink = FakeProducts(), InMemoryEventSink()
    leg = await Leg.build(session, run.id, products, sink, staged=[])
    assert await leg.flow_runner.resume_after_external_wait(run.id) is None
    assert products.uploads == [] and sink.events == ()


@pytest.mark.asyncio
async def test_wiring_hands_the_worker_the_photo_and_its_staged_uri(session):
    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product, lever="cover_image", flow_kind="photo")
    other_shop, other_product = await seed_shop(session, "b")
    plain = await seed_run(session, other_shop, other_product, lever="title")
    data = png()
    photo = await photos.save_photo(
        session,
        shop_id=shop.id,
        run_id=run.id,
        role="after",
        data=data,
        report=photo_checks.check_photo(data),
    )
    photo.tiktok_uri = "tos-staged"
    await session.flush()

    wiring = await lever_flows.wiring_for_run(
        session,
        None,
        run,
        product,
        product_detail=lambda: None,  # type: ignore[arg-type]
    )
    assert wiring is not None
    assert wiring.playbook is lever_flows.PHOTO_PLAYBOOK
    assert wiring.planner.photo_ready is True
    assert (wiring.pending_image_bytes, wiring.staged_image_uri) == (data, "tos-staged")
    assert (
        await lever_flows.wiring_for_run(
            session, None, plain, other_product, product_detail=lambda: None
        )  # type: ignore[arg-type]
        is None
    ), "an ordinary run is untouched"


# --- expiry ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_photo_request_expires_after_three_days_not_before(session):
    shop, run = await _start_photo_run(session)
    products, sink = FakeProducts(), InMemoryEventSink()
    await (await Leg.build(session, run.id, products, sink, staged=[])).flow_runner.run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    row = await session.get(WorkflowRunRow, run.id)
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    row.waiting_external_since = now - timedelta(hours=71)
    await session.flush()
    early = await reaper.reap_workflow_runs(session, now=now, has_live_task=lambda _r: False)
    assert run.id not in early.expired_external_waits_reaped
    assert (await session.get(WorkflowRunRow, run.id)).status == "waiting_external"

    row.waiting_external_since = now - timedelta(hours=73)
    await session.flush()
    late = await reaper.reap_workflow_runs(session, now=now, has_live_task=lambda _r: False)
    assert run.id in late.expired_external_waits_reaped
    expired = await session.get(WorkflowRunRow, run.id)
    await session.refresh(expired)
    assert (expired.status, expired.stop_reason) == ("timed_out", "external_wait_expired")
    assert products.edits == [] and products.uploads == []


# --- the routes ------------------------------------------------------------------------------


@pytest.fixture
def enqueued(monkeypatch):
    from juli_backend.api.routes import demo_run_flows

    calls: list[uuid.UUID] = []

    def _enqueue(run_id):
        calls.append(run_id)
        return "task-1"

    monkeypatch.setattr(demo_run_flows, "_enqueue_resume_lever_flow", _enqueue)
    return calls


async def _waiting_photo_run(session, label="a"):
    shop, product = await seed_shop(session, label)
    run = await seed_run(
        session,
        shop,
        product,
        lever="cover_image",
        flow_kind="photo",
        status="waiting_external",
        external_wait_reason="photo",
        waiting_since=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
    )
    await session.commit()
    return shop, run


@pytest.mark.asyncio
async def test_post_photo_202s_with_the_checks_stores_it_and_resumes_the_run(
    engine, session, enqueued
):
    shop, run = await _waiting_photo_run(session)
    content_type, body = multipart(png())
    async with api_client(engine, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/photo", content=body, headers={"content-type": content_type}
        )
        detail = await client.get(f"/v1/demo/runs/{run.id}")
        listed = await client.get("/v1/demo/runs")

    assert resp.status_code == 202, resp.text
    checks = resp.json()["checks"]
    assert [c["key"] for c in checks] == ["ratio", "size", "background", "product_fill"]
    assert all(c["ok"] for c in checks) and all(c["label"] for c in checks)
    assert enqueued == [run.id]

    data = detail.json()["data"]
    assert data["awaiting"] == "photo"
    assert data["awaiting_expires_at"].startswith("2026-10-12T03:00")
    assert data["lever"] == {"code": "cover_image", "kind": "photo"}
    assert data["photo"]["after_url"].startswith(f"/v1/demo/photos/{shop.id}/")
    assert data["photo"]["before_url"] is None
    assert [item["awaiting"] for item in listed.json()["data"]] == ["photo"]

    async with api_client(engine, shop) as client:
        served = await client.get(data["photo"]["after_url"])
        wrong = await client.get(f"/v1/demo/photos/{shop.id}/not-the-token")
        other = await client.get(
            data["photo"]["after_url"].replace(str(shop.id), str(uuid.uuid4()))
        )
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.content == png()
    assert wrong.status_code == 404 and other.status_code == 404


@pytest.mark.asyncio
async def test_post_photo_422s_with_the_same_list_when_a_check_fails(engine, session, enqueued):
    shop, run = await _waiting_photo_run(session)
    content_type, body = multipart(png(product_box=(450, 450, 550, 550)))
    async with api_client(engine, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/photo", content=body, headers={"content-type": content_type}
        )
        not_multipart = await client.post(f"/v1/demo/runs/{run.id}/photo", json={"file": "x"})
    assert resp.status_code == 422
    failing = {c["key"] for c in resp.json()["checks"] if not c["ok"]}
    assert failing == {"product_fill"}
    assert not_multipart.status_code == 422
    assert enqueued == []
    assert await photos.get_photo(session, shop.id, run.id, "after") is None


@pytest.mark.asyncio
async def test_post_photo_409s_when_not_waiting_and_404s_for_another_shop(
    engine, session, enqueued
):
    shop_a, run_a = await _waiting_photo_run(session, "a")
    shop_b, product_b = await seed_shop(session, "b")
    run_b = await seed_run(session, shop_b, product_b, lever="title", status="running")
    await session.commit()
    content_type, body = multipart(png())
    headers = {"content-type": content_type}
    async with api_client(engine, shop_b) as client:
        not_waiting = await client.post(
            f"/v1/demo/runs/{run_b.id}/photo", content=body, headers=headers
        )
        foreign = await client.post(
            f"/v1/demo/runs/{run_a.id}/photo", content=body, headers=headers
        )
        foreign_detail = await client.get(f"/v1/demo/runs/{run_a.id}")
    assert not_waiting.status_code == 409
    assert not_waiting.json()["detail"]["code"] == "not_awaiting_photo"
    assert foreign.status_code == 404 and foreign_detail.status_code == 404
    assert enqueued == []
