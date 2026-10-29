"""P76-5: Đo lường shows TikTok's check of the written draft beside Ngày 0 and now.

The listing write stored TikTok's ``diagnose_optimize`` reading of the confirmed draft on
its ledger outcome (``draft_score``). The sandbox reviewer's runs list carries it as a third
reading ("Sau sửa (TikTok kiểm tra)"), and a title / description code TikTok's live
diagnosis still lists that the check cleared is labelled as TikTok's not-yet-updated
diagnosis (edge case D31), not as no improvement.
"""

from __future__ import annotations

from typing import Any

from juli_backend.models.models import WorkflowRun
from juli_backend.services.agent.tools.diagnosis_labels import STALE_DIAGNOSIS_NOTE_VI
from juli_backend.services.agent.tools.draft_scoring import DraftScore
from juli_backend.services.agent_runs import listing_quality
from juli_backend.services.agent_runs.listing_quality import (
    DiagnosisReading,
    checked_reading,
    mark_stale,
)
from tests.unit import test_p71_listing_quality as p71
from tests.unit.test_p67_reviewer_confirmed_writes import _run_with_write

reviewer_env = p71.reviewer_env
world = p71.world
tiktok = p71.tiktok

DAY0 = p71._state({"codes": p71.DAY0_CODES, "count": 4})
SCORED_AT = "2026-10-29T03:00:00Z"
CLEARED = {
    "status": "scored",
    "codes_after": ["MAIN_IMG_NUMBER_LESS_THAN_FIVE"],
    "scored_at": SCORED_AT,
}


async def _edit(session, ids, reviewer_id, *, draft_score: dict[str, Any] | None) -> str:
    outcome: dict[str, Any] = {"title": "Tiêu đề mới", "description": "Mô tả mới"}
    if draft_score is not None:
        outcome["draft_score"] = draft_score
    run_id = await _run_with_write(
        session,
        ids,
        reviewer_id,
        workflow="optimize_product_2",
        tool="update_product_listing",
        outcome=outcome,
        n=1,
    )
    run = await session.get(WorkflowRun, run_id)
    run.state = DAY0
    await session.commit()
    return str(run_id)


async def test_three_readings_and_tiktoks_stale_diagnosis_is_labelled(session, world, tiktok):
    ids, reviewer_id = world
    # TikTok's live diagnosis still lists what its own check of the draft cleared (D31).
    tiktok.codes = ["TITLE_LESS_THAN_40_CHARACTERS", "MAIN_IMG_NUMBER_LESS_THAN_FIVE"]
    run_id = await _edit(session, ids, reviewer_id, draft_score=CLEARED)

    quality = (await p71._quality(session, ids, reviewer_id))[run_id]

    assert quality["before"]["count"] == 4
    assert quality["checked"] == {
        "count": 1,
        "issues": ["Ít hơn 5 ảnh chính"],
        "read_at": SCORED_AT,
    }
    assert quality["after"]["count"] == 2
    assert quality["after"]["issues"] == [
        f"Tiêu đề quá ngắn ({STALE_DIAGNOSIS_NOTE_VI})",
        "Ít hơn 5 ảnh chính",
    ]
    assert "codes" not in quality["after"]


async def test_a_not_read_check_shows_no_third_reading(session, world, tiktok):
    ids, reviewer_id = world
    tiktok.codes = ["TITLE_LESS_THAN_40_CHARACTERS"]
    run_id = await _edit(
        session, ids, reviewer_id, draft_score={"status": "not_read", "codes_after": []}
    )

    quality = (await p71._quality(session, ids, reviewer_id))[run_id]

    assert quality["checked"] is None
    assert quality["after"]["issues"] == ["Tiêu đề quá ngắn"]


async def test_a_write_from_before_p76_reads_as_before(session, world, tiktok):
    ids, reviewer_id = world
    run_id = await _edit(session, ids, reviewer_id, draft_score=None)

    quality = (await p71._quality(session, ids, reviewer_id))[run_id]

    assert quality["checked"] is None
    assert quality["after"]["issues"] == ["Ít hơn 5 ảnh chính"]


def test_only_title_and_description_codes_are_called_stale():
    now = DiagnosisReading(
        count=2,
        issues=("Mô tả chưa xuống dòng", "Ảnh chính bị trùng"),
        read_at="t",
        codes=("DESC_NO_NEW_LINE", "MAIN_IMG_DUPLICATE"),
    )
    checked = checked_reading(DraftScore(status="scored", codes_after=[], scored_at="s"))

    after, stale = mark_stale(now, checked)

    assert stale == (f"Mô tả chưa xuống dòng ({STALE_DIAGNOSIS_NOTE_VI})",)
    assert after is not None
    assert after.issues == (stale[0], "Ảnh chính bị trùng")
    assert after.count == 2


def test_no_check_or_no_live_reading_changes_nothing():
    now = DiagnosisReading(
        count=1, issues=("Tiêu đề quá ngắn",), codes=("TITLE_LESS_THAN_40_CHARACTERS",)
    )
    assert mark_stale(now, None) == (now, ())
    assert mark_stale(None, checked_reading(DraftScore(status="scored"))) == (None, ())
    assert checked_reading(DraftScore(status="not_read")) is None
    assert checked_reading(None) is None


def test_the_reread_keeps_its_codes():
    class Products:
        def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
            return {
                "products": [
                    {
                        "id": product_ids[0],
                        "diagnoses": [
                            {
                                "field": "TITLE",
                                "diagnosis_results": [{"code": "TITLE_LESS_THAN_40_CHARACTERS"}],
                            }
                        ],
                    }
                ]
            }

    class Resources:
        products = Products()

    reading = listing_quality._read_now(Resources(), "1")
    assert reading.codes == ("TITLE_LESS_THAN_40_CHARACTERS",)
