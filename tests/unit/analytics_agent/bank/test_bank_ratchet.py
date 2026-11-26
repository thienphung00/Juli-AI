"""The bank only grows (owner decision #109): no recorded case removed, none changed or added
without updating `ratchet.json`, the counts never drop, and every case is well formed (a typo'd
key would silently switch a check off, so unknown keys fail)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.analytics_agent.bank import ratchet, runner

UPDATE = "PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.ratchet --update"
CASE_KEYS = {
    "id", "area", "question", "intents", "jev", "jev_card", "jev_product", "jev_down", "as_of",
    "platform", "template", "then", "parse_fails", "ungated", "writer", "restated", "pg", "paid",
    "status", "reason", "note", "expect",
}  # fmt: skip
EXPECT_KEYS = {
    "stop", "routes", "n_intent_blocks", "events", "no_events", "more_items", "more_vietnamese",
    "needs_choice_item", "answers", "n_answers", "forbid", "require", "no_numbers", "followup",
    "max_jev_calls",
}  # fmt: skip
ANSWER_KEYS = {
    "kind", "title_vi", "title_has", "window", "fresh", "rows_have", "first_row", "value_has",
    "screen", "from", "to", "missing_as", "before_screen",
}  # fmt: skip
SCREENS = (
    "overview.", "overview_prev.", "overview_profit.", "metric_view.", "channel_split.",
    "voucher.", "kol.", "offer.", "product.",
)  # fmt: skip


@pytest.mark.parametrize(
    "part,path", [("bank", runner.CASES_FILE), ("advisor", runner.ADVISOR_FILE)]
)
def test_no_case_removed_changed_or_unrecorded(part: str, path: Any) -> None:
    rec = ratchet.record()[part]
    now = ratchet.snapshot(path)
    gone = sorted(set(rec["cases"]) - set(now["cases"]))
    assert not gone, f"{part}: cases removed: {gone} (the bank only grows)"
    changed = sorted(i for i, h in rec["cases"].items() if now["cases"].get(i) != h)
    new = sorted(set(now["cases"]) - set(rec["cases"]))
    assert not changed and not new, (
        f"{part}: changed {changed}, unrecorded {new}. A loosened expectation needs the owner's "
        f"OK; then record it: {UPDATE}"
    )
    assert now["count"] >= rec["count"] and now["passing"] >= rec["passing"]


def _check_expect(cid: str, exp: dict[str, Any]) -> list[str]:
    bad = [f"{cid}: unknown expect key {k!r}" for k in set(exp) - EXPECT_KEYS]
    if not set(exp) - {"followup"}:
        bad.append(f"{cid}: expects nothing")
    for a in exp.get("answers") or []:
        bad += [f"{cid}: unknown answer key {k!r}" for k in set(a) - ANSWER_KEYS]
        for k in ("screen", "before_screen"):
            if k in a:
                if not a[k].startswith(SCREENS):
                    bad.append(f"{cid}: unknown screen {a[k]!r}")
                if not ({"from", "to"} <= set(a)):
                    bad.append(f"{cid}: a screen figure needs its window (from / to)")
    if "followup" in exp:
        bad += _check_expect(cid + ".followup", exp["followup"])
    return bad


@pytest.mark.parametrize("path", [runner.CASES_FILE, runner.ADVISOR_FILE])
def test_cases_are_well_formed(path: Any) -> None:
    cases = runner.load_cases(path)
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate ids"
    bad: list[str] = []
    for c in cases:
        cid = c["id"]
        bad += [f"{cid}: unknown key {k!r}" for k in set(c) - CASE_KEYS]
        status = c.get("status", "pass")
        if status not in runner.STATUSES:
            bad.append(f"{cid}: status {status!r} (no skip: pass | xfail | pending)")
        if status != "pass" and not str(c.get("reason") or "").strip():
            bad.append(f"{cid}: {status} needs the gap named in 'reason'")
        if status == "pass" and c.get("reason"):
            bad.append(f"{cid}: a passing case carries a reason")
        if not (c.get("paid") or c.get("template") or c.get("parse_fails") or c.get("intents")):
            bad.append(f"{cid}: no parser output")
        bad += _check_expect(cid, c["expect"])
    assert not bad, "\n".join(bad)


def test_bank_covers_the_owner_areas() -> None:
    areas = {c["area"] for c in runner.load_cases()}
    want = {
        "periods", "orders", "aov", "units", "traffic", "funnel", "profit", "vouchers",
        "programmes", "affiliate", "ads", "products", "stock", "cards", "plan", "freshness",
        "multi", "ambiguous", "refuse", "thread", "templates", "create", "why",
    }  # fmt: skip
    assert want <= areas, f"missing areas: {sorted(want - areas)}"
