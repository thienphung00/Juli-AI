"""ONE structured-output model call per script version (D24.1, D24.7, D24.16).

``OpenAIContentDrafter`` sends the prompt templates (``prompts``) to
``gpt-5.4-nano`` through the existing OpenAI Responses adapter with a JSON
schema (``schemas``), parses the answer and runs the guardrails. The result is
either a script that passed every check, or the reason it is not shown. The
call's token usage is returned so the run's own cost rollup counts it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from juli_backend.services.agent.llm.blocks import FinalResponse, TextBlock, Usage
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.content_cards import prompts
from juli_backend.services.content_cards.constants import VIDEO, ContentKind
from juli_backend.services.content_cards.guardrails import (
    ContentRules,
    DraftFacts,
    Verdict,
    check_live,
    check_video,
)
from juli_backend.services.content_cards.schemas import (
    LivePlan,
    SchemaViolation,
    VideoScript,
    parse_draft,
    schema_for,
)

logger = logging.getLogger(__name__)

#: A script is a few hundred tokens; JSON overhead and Vietnamese diacritics
#: roughly double it.
DRAFT_MAX_OUTPUT_TOKENS = 2_500
DRAFT_TIMEOUT_S = 60.0

ERROR_PROVIDER = "provider"
ERROR_SCHEMA = "schema"
ERROR_CHECKS = "checks"


@dataclass(frozen=True)
class DraftInputs:
    """What the run read, as the prompt states it."""

    facts: DraftFacts
    rules: ContentRules
    performance: Mapping[str, Any] = field(default_factory=dict)
    product: Mapping[str, Any] = field(default_factory=dict)
    seo_words: Sequence[str] = ()
    examples: Sequence[Mapping[str, Any]] = ()
    #: P15: the analysis of the seller's best / weakest uploaded video (derived only).
    analyses: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class DraftOutcome:
    version: int
    model: str
    usage: Usage
    script: dict[str, Any] | None = None
    verdict: Verdict | None = None
    error: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.script is not None and self.error is None


class ContentDrafter(Protocol):
    async def draft(
        self,
        *,
        kind: ContentKind,
        inputs: DraftInputs,
        version: int,
        previous: Mapping[str, Any] | None,
        config: LLMConfig,
    ) -> DraftOutcome: ...


def validate(kind: ContentKind, parsed: VideoScript | LivePlan, inputs: DraftInputs) -> Verdict:
    if kind == VIDEO:
        assert isinstance(parsed, VideoScript)
        return check_video(parsed, inputs.facts, inputs.rules)
    assert isinstance(parsed, LivePlan)
    return check_live(parsed, inputs.facts, inputs.rules)


def outcome_from_text(
    kind: ContentKind,
    text: str,
    inputs: DraftInputs,
    *,
    version: int,
    model: str,
    usage: Usage,
) -> DraftOutcome:
    """Parse + guardrails over the model's text (pure; the provider call is separate)."""
    try:
        parsed = parse_draft(kind, text)
    except SchemaViolation as exc:
        return DraftOutcome(version, model, usage, error=ERROR_SCHEMA, detail=str(exc)[:200])
    verdict = validate(kind, parsed, inputs)
    if not verdict.ok:
        detail = "; ".join(f"{c.key}: {c.detail}" for c in verdict.failures())
        return DraftOutcome(
            version, model, usage, verdict=verdict, error=ERROR_CHECKS, detail=detail[:300]
        )
    return DraftOutcome(
        version, model, usage, script=parsed.model_dump(mode="json"), verdict=verdict
    )


class OpenAIContentDrafter:
    """The production drafter over ``OpenAIResponsesAdapter`` (structured output)."""

    def __init__(self, adapter: Any | None = None) -> None:
        if adapter is None:
            from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter

            adapter = OpenAIResponsesAdapter()
        self._adapter = adapter

    async def draft(
        self,
        *,
        kind: ContentKind,
        inputs: DraftInputs,
        version: int,
        previous: Mapping[str, Any] | None,
        config: LLMConfig,
    ) -> DraftOutcome:
        from juli_backend.services.agent.llm.openai_adapter import (
            JsonSchemaFormat,
            LLMProviderError,
        )

        name, schema = schema_for(kind)
        call_config = replace(
            config,
            max_output_tokens=max(config.max_output_tokens, DRAFT_MAX_OUTPUT_TOKENS),
            request_timeout_seconds=max(config.request_timeout_seconds, DRAFT_TIMEOUT_S),
        )
        user = prompts.user_prompt(
            kind,
            inputs.facts,
            inputs.rules,
            performance=inputs.performance,
            product=inputs.product,
            seo_words=inputs.seo_words,
            examples=inputs.examples,
            previous=previous,
            analyses=inputs.analyses,
        )
        try:
            turn = await self._adapter.complete(
                messages=[{"role": "user", "content": user}],
                system=prompts.system_prompt(kind, inputs.rules),
                tools=[],
                config=call_config,
                response_format=JsonSchemaFormat(name=name, schema=schema),
            )
        except LLMProviderError as exc:
            logger.warning("content_draft_provider_error", extra={"detail": str(exc)[:200]})
            return DraftOutcome(
                version, config.model, Usage(0, 0), error=ERROR_PROVIDER, detail=str(exc)[:200]
            )
        text = "".join(
            block.content if isinstance(block, FinalResponse) else block.text
            for block in turn.blocks
            if isinstance(block, FinalResponse | TextBlock)
        )
        outcome = outcome_from_text(
            kind, text, inputs, version=version, model=config.model, usage=turn.usage
        )
        logger.info(
            "content_draft",
            extra={
                "kind": kind,
                "version": version,
                "model": config.model,
                "ok": outcome.ok,
                "error": outcome.error,
                "input_tokens": turn.usage.input_tokens,
                "output_tokens": turn.usage.output_tokens,
                "prompt_version": prompts.PROMPT_VERSION,
            },
        )
        return outcome


__all__ = [
    "DRAFT_MAX_OUTPUT_TOKENS",
    "ERROR_CHECKS",
    "ERROR_PROVIDER",
    "ERROR_SCHEMA",
    "ContentDrafter",
    "DraftInputs",
    "DraftOutcome",
    "OpenAIContentDrafter",
    "outcome_from_text",
    "validate",
]
