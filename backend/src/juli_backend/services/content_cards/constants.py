"""Names and Vietnamese copy of the P14-E content cards (contract ``p14-content-cards.md`` §0).

Two kinds, each its own ``workflow_key`` so a product can carry a Video and a
LIVE card at once (the run lock is per workflow and subject) and so the emission
budget can count them as content cards (D24.17's day-1 content slot).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ContentKind = Literal["video", "live"]

VIDEO: ContentKind = "video"
LIVE: ContentKind = "live"

CONTENT_VIDEO_WORKFLOW_KEY = "content_video"
CONTENT_LIVE_WORKFLOW_KEY = "content_live"
#: The workflow keys of every content card / run. Emission counts a card as a
#: content card by this set (or by the payload's ``card_executor``).
CONTENT_WORKFLOW_KEYS: frozenset[str] = frozenset(
    {CONTENT_VIDEO_WORKFLOW_KEY, CONTENT_LIVE_WORKFLOW_KEY}
)

#: The card's executor (contract §1): Juli drafts, the seller films / goes live.
EXECUTOR_JULI_DRAFTS = "juli_drafts"
CHIP_VI = "Juli soạn · bạn làm"

#: Lever codes: the cooldown key (``decision_reasons.lever_code``), the
#: calibration key (``lever_calibrations.lever``) and the measurement final's lever.
LEVER_VIDEO_SCRIPT = "video_script"
LEVER_LIVE_SCRIPT = "live_script"
CONTENT_LEVERS: frozenset[str] = frozenset({LEVER_VIDEO_SCRIPT, LEVER_LIVE_SCRIPT})

#: Days a card stays valid (D24.17), and how long the same action on the same
#: product stays away after it expired / was rejected / declined.
VALIDITY_DAYS = 7
COOLDOWN_DAYS = 7
#: Once surfaced, a card stays at least this long unless it is no longer valid.
MIN_SURFACED_DAYS = 3
#: D24.17 sub-limit: at most this many new content cards per ISO week.
WEEKLY_CONTENT_CARDS = 5

PAYLOAD_VERSION = "p14-content-v1"

#: The run's two seller waits (``workflow_runs.external_wait_reason``): the
#: script choice (3 days), then the video / the LIVE (7 days). Read by the runs
#: list, the decline route and the reaper through ``lever_flows.flows``.
AWAITING_CONTENT_CHOICE = "content_choice"
AWAITING_CONTENT_PUBLISH = "content_publish"
CHOICE_WAIT_HOURS = 72
PUBLISH_WAIT_HOURS = 7 * 24

#: The run's own read-only tools (``tools``), named here so the playbooks can
#: list them without importing the tool module.
CONTENT_PERFORMANCE_TOOL = "get_content_performance"
FIND_NEW_CONTENT_TOOL = "find_new_content"


@dataclass(frozen=True)
class KindSpec:
    """Everything that differs between the Video and the LIVE card."""

    kind: ContentKind
    workflow_key: str
    lever_code: str
    workflow_label: str
    action_label: str
    kpi_key: str
    kpi_label: str
    reason_short: str
    stream: str
    metric: str
    gmv_method: str


VIDEO_SPEC = KindSpec(
    kind=VIDEO,
    workflow_key=CONTENT_VIDEO_WORKFLOW_KEY,
    lever_code=LEVER_VIDEO_SCRIPT,
    workflow_label="Tối ưu nội dung · Video",
    action_label="Kịch bản video mới",
    kpi_key="video_ctr",
    kpi_label="CTR - Video của người bán",
    reason_short="Video có lượt xem nhưng ít bấm vào sản phẩm",
    stream="seller_video",
    metric="ctr",
    gmv_method=(
        "lượt hiển thị × (CTR mục tiêu − CTR hiện tại) × CTOR × AOV của video trong shop, "
        "trung bình 30 ngày, ước tính theo quy tắc"
    ),
)

LIVE_SPEC = KindSpec(
    kind=LIVE,
    workflow_key=CONTENT_LIVE_WORKFLOW_KEY,
    lever_code=LEVER_LIVE_SCRIPT,
    workflow_label="Tối ưu nội dung · LIVE",
    action_label="Kịch bản host + thứ tự giỏ",
    kpi_key="live_ctor",
    kpi_label="CTOR - LIVE của người bán",
    reason_short="Người xem bấm vào nhưng ít chốt đơn",
    stream="seller_live",
    metric="ctor",
    gmv_method=(
        "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV của LIVE trong shop, "
        "trung bình 30 ngày, ước tính theo quy tắc"
    ),
)

SPECS: dict[ContentKind, KindSpec] = {VIDEO: VIDEO_SPEC, LIVE: LIVE_SPEC}
SPEC_BY_WORKFLOW: dict[str, KindSpec] = {s.workflow_key: s for s in SPECS.values()}
SPEC_BY_LEVER: dict[str, KindSpec] = {s.lever_code: s for s in SPECS.values()}


def is_content_workflow(workflow_key: str | None) -> bool:
    return workflow_key in CONTENT_WORKFLOW_KEYS


__all__ = [
    "CHIP_VI",
    "CONTENT_LEVERS",
    "CONTENT_LIVE_WORKFLOW_KEY",
    "CONTENT_VIDEO_WORKFLOW_KEY",
    "CONTENT_WORKFLOW_KEYS",
    "COOLDOWN_DAYS",
    "EXECUTOR_JULI_DRAFTS",
    "LEVER_LIVE_SCRIPT",
    "LEVER_VIDEO_SCRIPT",
    "LIVE",
    "LIVE_SPEC",
    "MIN_SURFACED_DAYS",
    "PAYLOAD_VERSION",
    "SPECS",
    "SPEC_BY_LEVER",
    "SPEC_BY_WORKFLOW",
    "VALIDITY_DAYS",
    "VIDEO",
    "VIDEO_SPEC",
    "WEEKLY_CONTENT_CARDS",
    "ContentKind",
    "KindSpec",
    "is_content_workflow",
]
