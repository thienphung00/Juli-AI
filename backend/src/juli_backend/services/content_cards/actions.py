"""The seller's steps of a content run (contract §2.2): Dùng / Soạn lại / "Tôi đã đăng".

Each one checks the run waits for exactly that step, updates the run's content
state and returns; the route commits and enqueues the resume (the existing
``resume_lever_flow`` task). Không thực hiện is the existing decline route.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.content_cards import run_state
from juli_backend.services.content_cards.constants import VIDEO, ContentKind
from juli_backend.services.content_cards.guardrails import (
    CHECK_LABELS,
    ContentRules,
    DraftFacts,
    check_edited_text,
)
from juli_backend.services.lever_flows.flows import awaiting_of

MAX_BLOCK_CHARS = 1_200


class ContentActionRefused(Exception):
    """The run is not at the step the seller pressed (→ 409), or the edit breaks a rule (→ 422)."""

    def __init__(self, code: str, message_vi: str, *, field: str | None = None, status: int = 409):
        super().__init__(message_vi)
        self.code = code
        self.message_vi = message_vi
        self.field = field
        self.status = status


_NOT_CONTENT_VI = "Lượt chạy này không phải kịch bản video hay LIVE."
_NOT_CHOICE_VI = "Lượt chạy này không chờ bạn chọn kịch bản."
_NOT_PUBLISH_VI = "Lượt chạy này không chờ bạn đăng video hay LIVE."
_NO_VERSION_VI = "Không tìm thấy bản kịch bản này."
_REDRAFT_USED_VI = "Juli đã soạn đủ 2 bản cho thẻ này."


def _state(run: WorkflowRunRow) -> dict[str, Any]:
    state = run_state.state_of(run)
    if state is None:
        raise ContentActionRefused("not_content", _NOT_CONTENT_VI)
    return state


def _rules(state: Mapping[str, Any]) -> ContentRules:
    raw = state.get("rules") or {}
    cap = raw.get("discount_cap_pct")
    return ContentRules(
        tone=raw.get("tone"),
        banned_terms=tuple(raw.get("banned_terms") or ()),
        protected_terms=tuple(raw.get("protected_terms") or ()),
        discount_cap_pct=float(cap) if isinstance(cap, int | float) else None,
    )


def _facts(state: Mapping[str, Any]) -> DraftFacts:
    raw = state.get("facts") or {}
    inventory = raw.get("inventory")
    return DraftFacts(
        product_label=str(raw.get("product_label") or state.get("label") or ""),
        product_title=str(raw.get("product_title") or state.get("title") or ""),
        prices_vnd=tuple(int(p) for p in raw.get("prices_vnd") or () if isinstance(p, int | float)),
        inventory=int(inventory) if isinstance(inventory, int) else None,
        basket_skus=tuple(str(s) for s in raw.get("basket_skus") or ()),
    )


def use_script(
    run: WorkflowRunRow, *, version: int, edited_blocks: Mapping[str, str] | None
) -> None:
    """Dùng kịch bản này (optionally with the seller's own edits, checked like a draft)."""
    state = _state(run)
    if awaiting_of(run) != run_state.AWAITING_CHOICE:
        raise ContentActionRefused("not_awaiting_choice", _NOT_CHOICE_VI)
    shown = run_state.draft(state, version)
    if shown is None or not shown.get("script"):
        raise ContentActionRefused("unknown_version", _NO_VERSION_VI, status=422)
    kind: ContentKind = "video" if state.get("kind") == VIDEO else "live"
    blocks = {
        b["key"]: b["text"]
        for b in run_state.script_blocks(kind, shown["script"], str(state.get("label") or ""))
    }
    edits: dict[str, str] = {}
    for key, text in (edited_blocks or {}).items():
        if key not in blocks or not isinstance(text, str):
            continue
        text = text.strip()
        if not text or text == blocks[key].strip():
            continue
        if len(text) > MAX_BLOCK_CHARS:
            raise ContentActionRefused(
                "rule_violation", "Đoạn bạn sửa quá dài.", field=key, status=422
            )
        verdict = check_edited_text(text, _facts(state), _rules(state))
        if not verdict.ok:
            failed = verdict.failures()[0]
            raise ContentActionRefused(
                "rule_violation",
                f"Đoạn bạn sửa chưa đạt: {CHECK_LABELS[failed.key]}"
                + (f" ({failed.detail})" if failed.detail else "")
                + ".",
                field=key,
                status=422,
            )
        edits[key] = text
    now = datetime.now(UTC).isoformat()
    state["chosen_version"] = version
    state["chosen_at"] = now
    state["edited_blocks"] = edits
    state["stage"] = run_state.STAGE_PUBLISH
    state.setdefault("step_at", {})["choose"] = now
    run_state.save_state(run, state)


def redraft(run: WorkflowRunRow) -> int:
    """Soạn lại: one more model call (bản 2). Returns the version asked for."""
    state = _state(run)
    if awaiting_of(run) != run_state.AWAITING_CHOICE:
        raise ContentActionRefused("not_awaiting_choice", _NOT_CHOICE_VI)
    versions = len(state.get("drafts") or [])
    if versions >= run_state.MAX_VERSIONS:
        raise ContentActionRefused("redraft_used", _REDRAFT_USED_VI)
    state["requested_version"] = versions + 1
    state["stage"] = run_state.STAGE_DRAFTING
    run_state.save_state(run, state)
    return versions + 1


def mark_published(run: WorkflowRunRow) -> None:
    """ "Tôi đã đăng video" / "Tôi đã LIVE xong"."""
    state = _state(run)
    if awaiting_of(run) != run_state.AWAITING_PUBLISH:
        raise ContentActionRefused("not_awaiting_publish", _NOT_PUBLISH_VI)
    state["published_at"] = datetime.now(UTC).isoformat()
    state["published_by"] = "seller"
    state["stage"] = run_state.STAGE_PUBLISHED
    state["detect_rounds"] = int(state.get("detect_rounds") or 0) + 1
    run_state.save_state(run, state)


__all__ = ["ContentActionRefused", "mark_published", "redraft", "use_script"]
