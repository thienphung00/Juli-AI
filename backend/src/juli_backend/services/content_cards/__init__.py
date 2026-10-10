"""P14-E "Juli soạn · bạn làm" content cards (D24.4, D24.17–D24.19).

Contract: ``fasttrack/contracts/p14-content-cards.md``.

- ``constants`` -- the two kinds (Video / LIVE), workflow keys, lever codes, copy.
- ``candidates`` -- rules over the stored metric rankings (no model).
- ``emission`` -- the nightly cards (cooldown, validity, weekly sub-limit).
- ``card_view`` -- the ``recommendation.card`` block of a content card.
- ``tools`` -- the run's read-only TikTok tools (``content`` tool domain).
- ``schemas`` / ``guardrails`` / ``prompts`` / ``drafter`` -- the ONE
  structured-output model call per script version, and its checks.
- ``planner`` / ``driver`` / ``run_state`` / ``actions`` -- the run.
- ``poll`` / ``measurement`` -- auto-detect and Đo lường.

This package's ``__init__`` imports only ``constants`` so the playbook and
tool-domain registries can import its submodules without a cycle.
"""

from juli_backend.services.content_cards.constants import (
    CONTENT_LEVERS,
    CONTENT_LIVE_WORKFLOW_KEY,
    CONTENT_VIDEO_WORKFLOW_KEY,
    CONTENT_WORKFLOW_KEYS,
    EXECUTOR_JULI_DRAFTS,
    is_content_workflow,
)

__all__ = [
    "CONTENT_LEVERS",
    "CONTENT_LIVE_WORKFLOW_KEY",
    "CONTENT_VIDEO_WORKFLOW_KEY",
    "CONTENT_WORKFLOW_KEYS",
    "EXECUTOR_JULI_DRAFTS",
    "is_content_workflow",
]
