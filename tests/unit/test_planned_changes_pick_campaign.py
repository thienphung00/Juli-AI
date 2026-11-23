"""E77: an imported ads row picks, among the campaigns matching its name token (else holding its
items), the one that has an ads report on the row's evaluation day. Synthetic keys and days."""

from __future__ import annotations

from datetime import date

from juli_backend.services.planned_changes import external_rows as er

TODAY = date(2026, 11, 20)
GROUP = er.Campaign("g", "Nhóm chung", ("p1", "p2", "p3"), 900.0)


def _row(ref: str, on: date, plan: str = "ROAS mục tiêu 8", items=("p1",)) -> er.SheetRow:
    return er.SheetRow(
        row=1, ref=ref, category="Quảng cáo", items=items, shop_wide=False, plan=plan,
        data="", on=on, status=er.STATUS_DONE, status_text="", days=7,
    )  # fmt: skip


def _pick(row, campaigns, reports):
    return er.pick_campaign(row, campaigns, reports, er.as_of_day(row, TODAY))


def test_a_campaign_without_a_report_on_the_day_gives_way_to_the_group_key():
    solo = er.Campaign("s1", "Riêng p1", ("p1",), 100.0)
    row = _row("A", date(2026, 10, 10))
    day = er.as_of_day(row, TODAY)
    got = _pick(row, [solo, GROUP], {day: frozenset({"g"})})
    assert got is not None and got.key == "g"


def test_the_key_whose_products_cover_the_item_is_preferred_when_both_have_a_report():
    solo = er.Campaign("s1", "Riêng p1", ("p1",), 100.0)
    row = _row("A", date(2026, 11, 10))
    day = er.as_of_day(row, TODAY)
    both = {day: frozenset({"g", "s1"})}
    got = _pick(row, [solo, GROUP], both)
    assert got is not None and got.key == "g"  # both cover; the busiest wins


def test_a_named_campaign_with_a_report_wins_over_the_group_key():
    named = er.Campaign("s1", "CDN/01 p1", ("p1",), 10.0)
    row = _row("A", date(2026, 11, 10), plan="CDN/01 ROAS mục tiêu 8")
    day = er.as_of_day(row, TODAY)
    got = _pick(row, [named, GROUP], {day: frozenset({"g", "s1"})})
    assert got is not None and got.key == "s1"


def test_three_rows_before_the_per_product_report_all_land_on_the_group_key_as_cards():
    solo = er.Campaign("s1", "Riêng p1", ("p1",), 100.0)
    rows = [_row(f"R{n}", date(2026, 10, 10 + n)) for n in range(3)]
    reports = {er.as_of_day(r, TODAY): frozenset({"g"}) for r in rows}
    facts = er.Facts(today=TODAY, campaigns=[solo, GROUP], reports=reports)
    plans = er.plan_rows(rows, facts)
    assert [p.skip for p in plans] == [None, None, None]
    assert [c.spec["campaign_key"] for p in plans for c in p.cards] == ["g", "g", "g"]
    assert [len(p.cards) for p in plans] == [1, 1, 1]


def test_without_report_knowledge_the_old_rule_holds():
    named = er.Campaign("s1", "CDN/01 p1", ("p1",), 10.0)
    row = _row("A", date(2026, 11, 10), plan="CDN/01 ROAS 8")
    assert er.pick_campaign(row, [GROUP, named]) is named
    plain = _row("B", date(2026, 11, 10))
    assert er.pick_campaign(plain, [named, GROUP]) is GROUP


def test_no_campaign_has_a_report_keeps_a_candidate_so_the_evaluation_refuses_as_before():
    row = _row("A", date(2026, 11, 10))
    got = _pick(row, [GROUP], {er.as_of_day(row, TODAY): frozenset()})
    assert got is GROUP
