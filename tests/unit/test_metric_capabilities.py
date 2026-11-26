"""The capability table (owner #115): every registry key and every card kind has a row, the rows
agree with the code they are read from, and Chat's one line comes from the same table."""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.services.analytics_agent import applies, levers
from juli_backend.services.analytics_agent.labels import shopee_labels
from juli_backend.services.metrics import capabilities as cap
from juli_backend.services.metrics.registry import METRICS
from juli_backend.services.shopee_builder.engine_families.families import _SIMPLE
from juli_backend.services.shopee_recommendations.kinds import KINDS, WIRING

#: a KindSpec target that is not a registry key: the ads report's own GMV
TARGET_KEY = {"ads_gmv": "channel_gmv_ads"}


def test_every_registry_key_is_measurable_somewhere() -> None:
    missing = [k for k in METRICS if not cap.scopes_for(k)]
    assert not missing, f"registry keys without a scope row: {missing}"


def test_every_scope_row_holds_registry_keys_only() -> None:
    for sid, s in cap.SCOPES.items():
        assert s.measurable <= set(METRICS), (sid, s.measurable - set(METRICS))
        assert s.parent is None or s.parent in cap.SCOPES


def test_every_card_kind_has_a_row_of_registry_keys() -> None:
    assert set(cap.MOVES) == set(KINDS), "a card kind without a capability row (or a stale row)"
    for k, ms in cap.MOVES.items():
        assert set(ms) <= set(METRICS), (k, set(ms) - set(METRICS))


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_kind_moves_its_own_target_metric(kind: str) -> None:
    spec = KINDS[kind]
    lo, hi = spec.prior
    if spec.target_metric == "none" or (lo + hi) / 2 <= 0:
        return  # no volume effect predicted, or a removal / limit (the effect is a loss)
    assert cap.moves(kind, TARGET_KEY.get(spec.target_metric, spec.target_metric)), kind


@pytest.mark.parametrize("kind", sorted(_SIMPLE))
def test_a_kind_moves_its_engine_drivers(kind: str) -> None:
    _, _, lead, co = _SIMPLE[kind]
    drivers = {lead[0]} | ({co[0]} if co else set())
    if kind == "listing_hide":  # removal: its views driver is -100 %
        assert not cap.MOVES[kind]
        return
    assert drivers <= cap.moves_all(kind), (kind, drivers)


def test_section_8_is_the_tables_own() -> None:
    assert WIRING is cap.SECTION8
    assert set(WIRING) <= set(cap.CRITICAL_METRIC)
    for crit, kinds in WIRING.items():
        assert all(cap.moves(k, cap.CRITICAL_METRIC[crit]) for k in kinds), crit
    assert cap.NOT_MEASURED <= set(KINDS)


def test_a_wired_kind_that_does_not_move_the_metric_fails_at_import() -> None:
    with pytest.raises(ValueError, match="do not move"):
        cap._section8({"aov": ("title",)})


def test_the_lines_read_as_the_owner_wrote_them() -> None:
    assert cap.kind_line("title", "Tên sản phẩm", "aov") == (
        "Tên sản phẩm tác động lượt xem và CTR, không tác động AOV."
    )
    assert cap.scope_line("organic", "roas").startswith("Organic không có ROAS. ROAS chỉ có cho ")
    assert "Quảng cáo" in cap.scope_line("organic", "roas")
    assert cap.short_scopes("roas") == ("shop", "product", "ads")  # the ads lines fold into ads


def _intent(**kw: Any) -> dict[str, Any]:
    return {"question_type": "status", "metric_key": "none", "card_kind": "none", **kw}


@pytest.mark.parametrize(
    ("intent", "line"),
    [
        (
            _intent(metric_key="roas", source_phrase="Organic"),
            "Organic không có ROAS. ROAS chỉ có cho Shop, Sản phẩm, Quảng cáo.",
        ),
        (
            _intent(metric_key="days_left", entity_phrase="ad campaign"),
            "Chiến dịch quảng cáo không có Còn bán được (ngày). Còn bán được (ngày) chỉ có cho "
            "Sản phẩm.",
        ),
        (
            _intent(
                metric_key="roas",
                source_phrase="Dịch vụ hiển thị Shop+",
                product_phrase="găng tay",
            ),
            "Dịch vụ hiển thị Shop+ không tính theo từng sản phẩm.",
        ),
        (
            _intent(metric_key="aov", card_kind="title"),
            "Tên sản phẩm tác động lượt xem và CTR, không tác động AOV.",
        ),
    ],
)
def test_chat_refuses_a_pairing_that_does_not_apply(intent: dict[str, Any], line: str) -> None:
    r = applies.refusal(intent, shopee_labels())
    assert r is not None and r.line == line
    assert r.buttons, "the pairings that apply are buttons"
    assert "chưa có số liệu" not in r.line
    ev = applies.events(r)
    assert ev[0] == {"type": "label", "stop_reason": "not_applicable", "text_vi": line,
                     "detail_vi": None}  # fmt: skip
    assert ev[1]["type"] == "more"


def test_the_buttons_of_a_metric_are_the_scopes_that_have_it() -> None:
    r = applies.refusal(_intent(metric_key="roas", source_phrase="Organic"), shopee_labels())
    assert r is not None
    assert [b["label_vi"] for b in r.buttons] == ["Shop", "Sản phẩm", "Quảng cáo"]


def test_the_buttons_of_a_card_goal_are_the_kinds_that_move_it() -> None:
    r = applies.refusal(_intent(metric_key="aov", card_kind="title"), shopee_labels())
    assert r is not None
    labels = shopee_labels()
    want = cap.kinds_moving("aov", levers.card_kinds(None))[: applies.MAX_BUTTONS]
    assert want and all(cap.moves(k, "aov") for k in want)
    assert [b["label_vi"] for b in r.buttons] == [labels.kind(k) for k in want]


@pytest.mark.parametrize(
    "intent",
    [
        _intent(metric_key="gmv", source_phrase="Organic"),
        _intent(metric_key="profit", source_phrase="Organic"),  # channel_profit_organic
        _intent(metric_key="roas", source_phrase="Quảng cáo"),
        _intent(metric_key="orders", entity_phrase="voucher"),
        _intent(metric_key="views", card_kind="title"),
        _intent(metric_key="gmv", card_kind="cover_image"),  # CTR carries GMV
        _intent(metric_key="days_left", product_phrase="găng tay"),
        _intent(metric_key="days_left", ranking="top"),  # a ranking reads per product
        _intent(metric_key="none", source_phrase="Organic"),
    ],
)
def test_a_pairing_that_applies_is_answered(intent: dict[str, Any]) -> None:
    assert applies.refusal(intent, shopee_labels()) is None
