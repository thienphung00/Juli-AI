"""Lever flows: the cover-image photo, Seller Center promotions, and Đo lường
(fast track P10-B, AC-10.2, contract ``fasttrack/contracts/p10-quyet-dinh.md`` §4-§6).

- ``flows`` -- which levers need a flow, the ``awaiting`` vocabulary, the flow row.
- ``photo_checks`` -- the four photo checks (two exact, two heuristic).
- ``photos`` -- the stored before/after photos, their served URLs, multipart.
- ``promotion`` -- rules check, proposal and Seller Center instructions (VI).
- ``planner`` -- the two playbooks and their deterministic planners.
- ``driver`` -- the worker's wiring and ``LeverFlowRunner`` (the waits).
- ``measurement`` -- ``GET /v1/demo/runs/{id}/measurement`` and calibration.
"""

from juli_backend.services.lever_flows.driver import (
    FlowWiring,
    LeverFlowRunner,
    wiring_for_run,
)
from juli_backend.services.lever_flows.flows import (
    AWAITING_PHOTO,
    AWAITING_SELLER_ACTION,
    MAX_VERIFY_ROUNDS,
    NARRATION_AWAITING_PHOTO,
    NARRATION_AWAITING_SELLER,
    NARRATION_NOT_FOUND,
    PROMOTION_LEVERS,
    RECHECK_DELAY_S,
    AwaitSeller,
    awaiting_of,
    flow_kind_for_lever,
    flows_for_runs,
    get_flow,
    is_promotion_lever,
    register_flow,
    touch,
    wait_timeout_hours,
)
from juli_backend.services.lever_flows.measurement import (
    LABELS_VI,
    NotMeasurable,
    final_label,
    measure_run,
)
from juli_backend.services.lever_flows.photo_checks import (
    MAX_PHOTO_BYTES,
    PhotoReport,
    check_photo,
    too_large_report,
)
from juli_backend.services.lever_flows.photos import (
    PHOTO_AFTER,
    PHOTO_BEFORE,
    MultipartError,
    fetch_image,
    get_photo,
    parse_multipart_file,
    photo_by_token,
    photo_url,
    save_photo,
)
from juli_backend.services.lever_flows.planner import (
    PHOTO_PLAYBOOK,
    PROMOTION_PLAYBOOK,
    PhotoPlanner,
    PromotionPlanner,
)
from juli_backend.services.lever_flows.promotion import (
    Instructions,
    PromotionProposal,
    PromotionRules,
    PromotionRulesMissing,
    instructions,
)


def termination_policy_for_wait(awaiting: str | None):
    """The flow playbook's ``TerminationPolicy`` for a run waiting on ``awaiting``
    (the reaper's per-run policy for lever-flow runs), else ``None``."""
    if awaiting == AWAITING_PHOTO:
        return PHOTO_PLAYBOOK.termination_policy
    if awaiting == AWAITING_SELLER_ACTION:
        return PROMOTION_PLAYBOOK.termination_policy
    return None


__all__ = [
    "AWAITING_PHOTO",
    "AWAITING_SELLER_ACTION",
    "LABELS_VI",
    "MAX_PHOTO_BYTES",
    "MAX_VERIFY_ROUNDS",
    "NARRATION_AWAITING_PHOTO",
    "NARRATION_AWAITING_SELLER",
    "NARRATION_NOT_FOUND",
    "PHOTO_AFTER",
    "PHOTO_BEFORE",
    "PHOTO_PLAYBOOK",
    "PROMOTION_LEVERS",
    "PROMOTION_PLAYBOOK",
    "RECHECK_DELAY_S",
    "AwaitSeller",
    "FlowWiring",
    "Instructions",
    "LeverFlowRunner",
    "MultipartError",
    "NotMeasurable",
    "PhotoPlanner",
    "PhotoReport",
    "PromotionPlanner",
    "PromotionProposal",
    "PromotionRules",
    "PromotionRulesMissing",
    "awaiting_of",
    "check_photo",
    "fetch_image",
    "final_label",
    "flow_kind_for_lever",
    "flows_for_runs",
    "get_flow",
    "get_photo",
    "instructions",
    "is_promotion_lever",
    "measure_run",
    "parse_multipart_file",
    "photo_by_token",
    "photo_url",
    "register_flow",
    "save_photo",
    "termination_policy_for_wait",
    "too_large_report",
    "touch",
    "wait_timeout_hours",
    "wiring_for_run",
]
