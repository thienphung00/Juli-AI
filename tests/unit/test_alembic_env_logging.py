"""Regression test for #1019.

`env.py` calls `logging.config.fileConfig(config.config_file_name)` when the Alembic
migration chain runs in-process. `fileConfig` defaults to `disable_existing_loggers=True`,
which sets `logger.disabled = True` on every already-created logger not named in
`alembic.ini`. Once that runs, every `juli_backend.*` logger is permanently dead for the
rest of the process, so `caplog.records` is empty in every test that runs afterwards.

This does not reproduce locally (no `DATABASE_URL`, so the migration chain — and
therefore `env.py` — never runs), and it must not depend on suite ordering to catch it in
CI either. So this test constructs the exact failure mechanism directly: configure
logging the way the app does, then make the same `fileConfig` call `env.py` makes against
the real `alembic.ini`, and assert a pre-existing application logger survives it.
"""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import pytest

from juli_backend.core.observability import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def restore_logging_state():
    """This test mutates global logging state (root handlers, logger.disabled).

    Restore it afterwards so later tests in the same process are unaffected.
    """
    root = logging.getLogger()
    attached: list[logging.Handler] = []
    yield attached
    for handler in attached:
        root.removeHandler(handler)
    configure_logging(force=True)


def test_fileconfig_with_disable_existing_loggers_false_keeps_app_loggers_alive(
    restore_logging_state,
):
    """The regression: env.py's fileConfig() call must not disable app loggers.

    Mirrors the exact call env.py now makes (`disable_existing_loggers=False`) and
    proves a pre-existing juli_backend.* logger is still enabled and still emits after
    it runs.
    """
    assert ALEMBIC_INI.is_file(), f"expected alembic.ini at {ALEMBIC_INI}"

    # 1. Configure logging the way the application does at startup.
    configure_logging(force=True)

    # 2. A representative application logger, created before fileConfig() runs — this
    # is the logger that dies in the bug (it is not named in alembic.ini).
    app_logger = logging.getLogger("juli_backend.api.demo")
    assert app_logger.disabled is False

    # 3. The same call env.py makes against the real alembic.ini.
    logging.config.fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)

    # 4. The logger must still be enabled and must still actually emit.
    assert app_logger.disabled is False

    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _CaptureHandler(level=logging.INFO)
    root = logging.getLogger()
    root.addHandler(handler)
    restore_logging_state.append(handler)
    root.setLevel(logging.INFO)

    app_logger.setLevel(logging.INFO)
    app_logger.info("alembic_logging_regression_probe")

    assert any(r.message == "alembic_logging_regression_probe" for r in captured)
