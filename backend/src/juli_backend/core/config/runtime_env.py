"""Boot report of required env and flags (fast track P61-D, D71.4).

A missing ``TIKTOK_APP_KEY`` or ``REDIS_URL`` used to show up only as an
``info``-level "skipped" line from whichever task met it first -- ingestion
looked healthy and did nothing. This module names, at API and worker boot, every
variable a connected shop needs end to end that is missing, and every flag that
is off, as one structured WARNING each (``runtime_env_missing``), plus one
summary line (``runtime_env_report``). The same report is served to Juli Ops
(``GET /v1/ops/runtime-env``).

NEVER A VALUE. The report carries names, a present / on boolean, and what the
gap breaks -- not one character of any value, secret or not.

Not a boot assertion: nothing here fails the process. The assertions that must
fail boot stay where they are (``require_env``, ``assert_agent_runtime_config``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

Kind = Literal["required", "flag", "info"]

#: The truthy spellings ``workers/agent_broker_guard.agent_workflows_enabled`` accepts.
_AGENT_TRUTHY = frozenset({"1", "true", "yes", "on"})
#: The spellings ``core/config/runtime.is_production_write_enabled`` accepts.
_WRITE_TRUTHY = frozenset({"true", "1", "yes"})


@dataclass(frozen=True)
class EnvCheck:
    """One variable: what it is and what breaks without it."""

    name: str
    kind: Kind
    effect: str
    truthy: frozenset[str] | None = None


#: The variables / flags a connected shop needs end to end. Order is the report order.
CHECKS: tuple[EnvCheck, ...] = (
    EnvCheck("TIKTOK_APP_KEY", "required", "TikTok OAuth and every ingestion task are skipped"),
    EnvCheck("TIKTOK_APP_SECRET", "required", "TikTok OAuth and every ingestion task are skipped"),
    EnvCheck(
        "TIKTOK_REDIRECT_URI", "required", "TikTok OAuth and every ingestion task are skipped"
    ),
    EnvCheck("REDIS_URL", "required", "ingestion, rate limits and refresh cooldowns are off"),
    EnvCheck(
        "TIKTOK_PRODUCTION_MERCHANT_ID",
        "required",
        "production-read paths that need the configured merchant fail closed",
    ),
    EnvCheck(
        "TIKTOK_SANDBOX_MERCHANT_ID",
        "required",
        "polling and every read client fail closed (cannot exclude the sandbox merchant)",
    ),
    EnvCheck(
        "AGENT_WORKFLOWS_ENABLED",
        "flag",
        "approving a card creates no agent run",
        truthy=_AGENT_TRUTHY,
    ),
    EnvCheck(
        "PRODUCTION_WRITE_ENABLED",
        "info",
        "agent writes go to the sandbox merchant only (expected until the owner turns it on)",
        truthy=_WRITE_TRUTHY,
    ),
)


@dataclass(frozen=True)
class EnvCheckResult:
    name: str
    kind: Kind
    #: required: set and non-blank. flag / info: on.
    ok: bool
    effect: str

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "kind": self.kind, "ok": self.ok, "effect": self.effect}


@dataclass(frozen=True)
class RuntimeEnvReport:
    process: str
    results: tuple[EnvCheckResult, ...]

    @property
    def missing(self) -> list[str]:
        return [r.name for r in self.results if r.kind == "required" and not r.ok]

    @property
    def flags_off(self) -> list[str]:
        return [r.name for r in self.results if r.kind == "flag" and not r.ok]

    @property
    def info_off(self) -> list[str]:
        return [r.name for r in self.results if r.kind == "info" and not r.ok]

    @property
    def healthy(self) -> bool:
        return not self.missing and not self.flags_off

    def to_json(self) -> dict[str, object]:
        return {
            "process": self.process,
            "healthy": self.healthy,
            "missing": self.missing,
            "flags_off": self.flags_off,
            "info_off": self.info_off,
            "checks": [r.to_json() for r in self.results],
        }


def _evaluate(check: EnvCheck, environ: Mapping[str, str]) -> EnvCheckResult:
    raw = (environ.get(check.name) or "").strip()
    if check.truthy is None:
        ok = bool(raw)
    else:
        ok = raw.lower() in check.truthy
    return EnvCheckResult(name=check.name, kind=check.kind, ok=ok, effect=check.effect)


def runtime_env_report(
    process: str, *, environ: Mapping[str, str] | None = None
) -> RuntimeEnvReport:
    """Evaluate :data:`CHECKS` against ``environ`` (default ``os.environ``). Pure."""
    env = os.environ if environ is None else environ
    return RuntimeEnvReport(
        process=process, results=tuple(_evaluate(check, env) for check in CHECKS)
    )


def log_runtime_env_report(
    process: str, *, environ: Mapping[str, str] | None = None
) -> RuntimeEnvReport:
    """Log the report: a WARNING per missing variable / off flag, INFO otherwise. Never raises."""
    report = runtime_env_report(process, environ=environ)
    for result in report.results:
        if result.ok:
            continue
        # `process` / `name` are LogRecord attributes and may not be passed in
        # `extra` (KeyError at emit time), hence `boot_process` / `env_var`.
        extra = {
            "boot_process": process,
            "env_var": result.name,
            "kind": result.kind,
            "effect": result.effect,
        }
        if result.kind == "info":
            logger.info("runtime_env_flag_off", extra=extra)
        else:
            logger.warning("runtime_env_missing", extra=extra)
    log = logger.info if report.healthy else logger.warning
    log(
        "runtime_env_report",
        extra={
            "boot_process": process,
            "healthy": report.healthy,
            "missing": report.missing,
            "flags_off": report.flags_off,
            "info_off": report.info_off,
        },
    )
    return report


__all__ = [
    "CHECKS",
    "EnvCheck",
    "EnvCheckResult",
    "RuntimeEnvReport",
    "log_runtime_env_report",
    "runtime_env_report",
]
