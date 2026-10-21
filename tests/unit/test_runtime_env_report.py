"""Boot env / flag report (fast track P61-D, D71.4).

Missing TikTok / Redis env used to surface only as an INFO "skipped" line from
whichever ingestion task met it first. These pin: the report names every gap,
logs one WARNING per gap at API and worker boot, is served to Ops, and never
carries a value.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from juli_backend.core.config import log_runtime_env_report, runtime_env_report
from juli_backend.core.config.runtime_env import CHECKS

_LOGGER = "juli_backend.core.config.runtime_env"
ROOT = Path(__file__).resolve().parents[2]

#: Sentinel values that must never appear in a log line or a response body.
SECRETS = {
    "TIKTOK_APP_KEY": "app-key-SENTINEL-1",
    "TIKTOK_APP_SECRET": "app-secret-SENTINEL-2",
    "TIKTOK_REDIRECT_URI": "https://example.test/cb-SENTINEL-3",
    "REDIS_URL": "redis://:pw-SENTINEL-4@localhost:6379/0",
    "AGENT_WORKFLOWS_ENABLED": "true",
    "PRODUCTION_WRITE_ENABLED": "true",
}


def _records(caplog, message: str):
    return [r for r in caplog.records if r.name == _LOGGER and r.getMessage() == message]


def test_the_report_covers_every_variable_the_brief_names():
    assert [c.name for c in CHECKS] == [
        "TIKTOK_APP_KEY",
        "TIKTOK_APP_SECRET",
        "TIKTOK_REDIRECT_URI",
        "REDIS_URL",
        "AGENT_WORKFLOWS_ENABLED",
        "PRODUCTION_WRITE_ENABLED",
    ]
    kinds = {c.name: c.kind for c in CHECKS}
    assert kinds["PRODUCTION_WRITE_ENABLED"] == "info"
    assert kinds["AGENT_WORKFLOWS_ENABLED"] == "flag"


def test_a_fully_configured_deployment_is_healthy(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)

    report = log_runtime_env_report("api", environ=SECRETS)

    assert report.healthy
    assert report.missing == [] and report.flags_off == [] and report.info_off == []
    assert _records(caplog, "runtime_env_missing") == []
    (summary,) = _records(caplog, "runtime_env_report")
    assert summary.levelno == logging.INFO


def test_an_empty_environment_names_every_gap_one_warning_each(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)

    report = log_runtime_env_report("worker", environ={})

    assert report.missing == [
        "TIKTOK_APP_KEY",
        "TIKTOK_APP_SECRET",
        "TIKTOK_REDIRECT_URI",
        "REDIS_URL",
    ]
    assert report.flags_off == ["AGENT_WORKFLOWS_ENABLED"]
    assert report.info_off == ["PRODUCTION_WRITE_ENABLED"]
    assert not report.healthy

    warnings = _records(caplog, "runtime_env_missing")
    assert [w.env_var for w in warnings] == report.missing + report.flags_off
    assert all(w.levelno == logging.WARNING for w in warnings)
    assert all(w.boot_process == "worker" and w.effect for w in warnings)
    # PRODUCTION_WRITE_ENABLED off is the expected state: info, not a warning.
    (info,) = _records(caplog, "runtime_env_flag_off")
    assert info.env_var == "PRODUCTION_WRITE_ENABLED" and info.levelno == logging.INFO
    (summary,) = _records(caplog, "runtime_env_report")
    assert summary.levelno == logging.WARNING
    assert summary.missing == report.missing


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_value_is_missing(blank):
    report = runtime_env_report("api", environ={**SECRETS, "REDIS_URL": blank})
    assert report.missing == ["REDIS_URL"]


@pytest.mark.parametrize(
    ("value", "on"), [("true", True), ("1", True), ("on", True), ("false", False), ("", False)]
)
def test_agent_workflows_flag_uses_the_guards_truthy_set(value, on):
    report = runtime_env_report("api", environ={**SECRETS, "AGENT_WORKFLOWS_ENABLED": value})
    assert ("AGENT_WORKFLOWS_ENABLED" not in report.flags_off) is on


def test_no_value_ever_reaches_a_log_line_or_the_json(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    partial = {k: v for k, v in SECRETS.items() if k not in {"REDIS_URL", "TIKTOK_APP_KEY"}}

    report = log_runtime_env_report("api", environ=partial)

    emitted = json.dumps(report.to_json()) + "".join(
        json.dumps(vars(r), default=str) for r in caplog.records
    )
    for value in SECRETS.values():
        if value in {"true"}:
            continue
        assert value not in emitted


def test_both_processes_log_the_report_at_boot():
    """API lifespan and the Celery app (worker AND beat import it) call it."""
    api_main = (ROOT / "backend/src/juli_backend/api/main.py").read_text(encoding="utf-8")
    celery_app = (ROOT / "backend/src/juli_backend/workers/celery_app.py").read_text(
        encoding="utf-8"
    )
    assert 'log_runtime_env_report("api")' in api_main
    assert 'log_runtime_env_report("worker")' in celery_app


def test_the_worker_boot_call_does_not_raise_on_an_empty_env(monkeypatch, caplog):
    """`extra` keys must not collide with LogRecord attributes (``process``, ``name``)."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    for check in CHECKS:
        monkeypatch.delenv(check.name, raising=False)

    report = log_runtime_env_report("worker")

    assert len(_records(caplog, "runtime_env_missing")) == len(report.missing) + len(
        report.flags_off
    )


# -- the ingestion skip is a named warning now -------------------------------------


def test_an_unconfigured_ingestion_skip_is_a_named_warning(monkeypatch, caplog):
    from juli_backend.workers.tasks import shop_ingestion

    caplog.set_level(logging.INFO, logger=shop_ingestion.logger.name)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("REDIS_URL")
    monkeypatch.setenv("TIKTOK_APP_SECRET", " ")

    env = shop_ingestion._skip_if_unconfigured("poll_shop", shop_id="shop-1")

    assert env is None
    (record,) = [
        r for r in caplog.records if r.getMessage() == "shop_ingestion_skipped_unconfigured"
    ]
    assert record.levelno == logging.WARNING
    assert record.task == "poll_shop" and record.shop_id == "shop-1"
    assert record.missing == ["TIKTOK_APP_SECRET", "REDIS_URL"]
    assert all(
        value not in json.dumps(vars(record), default=str)
        for value in SECRETS.values()
        if value != "true"
    )


def test_a_configured_ingestion_task_does_not_warn(monkeypatch, caplog):
    from juli_backend.workers.tasks import shop_ingestion

    caplog.set_level(logging.INFO, logger=shop_ingestion.logger.name)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)

    env = shop_ingestion._skip_if_unconfigured("shop_poll_fanout")

    assert env is not None and env["redis_url"] == SECRETS["REDIS_URL"]
    assert not [
        r for r in caplog.records if r.getMessage() == "shop_ingestion_skipped_unconfigured"
    ]


# -- Ops-visible status ------------------------------------------------------------


async def test_ops_sees_the_runtime_env_report_without_values(session, monkeypatch):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app, client_for
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TIKTOK_APP_KEY")
    monkeypatch.setenv("AGENT_WORKFLOWS_ENABLED", "false")

    email = "viewer-env@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(email=email, role="viewer", active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    async with client_for(app) as client:
        response = await client.get("/v1/ops/runtime-env")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["process"] == "api"
    assert body["healthy"] is False
    assert body["missing"] == ["TIKTOK_APP_KEY"]
    assert body["flags_off"] == ["AGENT_WORKFLOWS_ENABLED"]
    assert {c["name"] for c in body["checks"]} == {c.name for c in CHECKS}
    for value in SECRETS.values():
        if value not in {"true"}:
            assert value not in response.text


async def test_a_seller_cannot_read_the_runtime_env(session, monkeypatch):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from tests.support.api import build_app, client_for
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    seller = await make_user(session, email="seller-env@gmail.com")
    app = build_app(session)

    async def current():
        return seller

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    async with client_for(app) as client:
        response = await client.get("/v1/ops/runtime-env")

    assert response.status_code == 403
