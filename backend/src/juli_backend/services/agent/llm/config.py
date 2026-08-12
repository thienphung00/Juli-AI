"""Fail-closed LLM configuration (ADR-071 decision 4).

Resolution order: **playbook override -> environment -> defaults**. The
provider API key arrives via the established `require_env` startup-assertion
pattern (`juli_backend.core.config`, ADR-061 vocabulary) and is
never defaulted to an empty string — resolving configuration with the key
absent from the environment fails closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from juli_backend.core.config import require_env

DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0

_MODEL_ENV_VAR = "LLM_MODEL"
_MAX_OUTPUT_TOKENS_ENV_VAR = "LLM_MAX_OUTPUT_TOKENS"
_TEMPERATURE_ENV_VAR = "LLM_TEMPERATURE"
_REQUEST_TIMEOUT_ENV_VAR = "LLM_REQUEST_TIMEOUT_SECONDS"
_API_KEY_ENV_VAR = "OPENAI_API_KEY"


@dataclass(frozen=True)
class LLMConfig:
    """Resolved configuration for a single `LLMService.complete` call."""

    model: str = DEFAULT_MODEL
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS


@dataclass(frozen=True)
class LLMConfigOverride:
    """Per-workflow playbook override.

    Every field defaults to `None`, meaning "no override" — resolution falls
    through to the environment, then the default, for that field only.
    """

    model: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    request_timeout_seconds: float | None = None


def resolve_llm_config(override: LLMConfigOverride | None = None) -> LLMConfig:
    """Resolve `LLMConfig` as playbook override -> environment -> defaults.

    Fails closed: raises `RuntimeError` (via `require_env`) when
    `OPENAI_API_KEY` is absent or blank in the environment, before any field
    is resolved. The key itself is intentionally not stored on the returned
    `LLMConfig` — it is not a secrets carrier, and providers (built in a
    later slice) read the key directly at call time via the same
    `require_env` pattern.
    """
    require_env(_API_KEY_ENV_VAR)

    resolved_override = override or LLMConfigOverride()

    return LLMConfig(
        model=_resolve_str(resolved_override.model, _MODEL_ENV_VAR, DEFAULT_MODEL),
        max_output_tokens=_resolve_int(
            resolved_override.max_output_tokens,
            _MAX_OUTPUT_TOKENS_ENV_VAR,
            DEFAULT_MAX_OUTPUT_TOKENS,
        ),
        temperature=_resolve_float(
            resolved_override.temperature, _TEMPERATURE_ENV_VAR, DEFAULT_TEMPERATURE
        ),
        request_timeout_seconds=_resolve_float(
            resolved_override.request_timeout_seconds,
            _REQUEST_TIMEOUT_ENV_VAR,
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
    )


def _resolve_str(override_value: str | None, env_var: str, default: str) -> str:
    if override_value is not None:
        return override_value
    raw = os.environ.get(env_var, "").strip()
    return raw or default


def _resolve_int(override_value: int | None, env_var: str, default: int) -> int:
    if override_value is not None:
        return override_value
    raw = os.environ.get(env_var, "").strip()
    return int(raw) if raw else default


def _resolve_float(override_value: float | None, env_var: str, default: float) -> float:
    if override_value is not None:
        return override_value
    raw = os.environ.get(env_var, "").strip()
    return float(raw) if raw else default
