"""The generated bank follows the code: its dimensions are the code's constants, the text table
covers every value, and the paid sample covers every value, mode, card kind and intent count."""

from __future__ import annotations

from collections import Counter

from juli_backend.services.analytics_agent import levers, routing
from juli_backend.services.analytics_agent.create_card import CARD_TYPES
from juli_backend.services.analytics_agent.types import TEMPLATES
from tests.unit.analytics_agent.bank import combos, paid_sample, text_variants
from tests.unit.analytics_agent.bank import dimensions as D


def test_dimensions_follow_the_code() -> None:
    assert set(D.metric_ids()) == {*routing._registry_metric_keys(), "none"}
    assert {p.preset for p in D.PERIODS if p.preset} == set(routing.WINDOWS)
    assert D.CARD_TYPES == CARD_TYPES and D.DRAFT_KINDS == tuple(levers.card_kinds(None))
    assert D.TEMPLATE_KEYS == tuple(t.key for t in TEMPLATES)
    entity_kinds = {k for _, k in routing.ENTITY_WORDS}
    assert {"voucher", "affiliate"} <= {s.kind for s in D.SCOPES} and "program" in entity_kinds
    assert set(D.OUTPUTS) >= {"value", "why"} and set(D.LOOKUP_OF.values()) == set(routing.LOOKUPS)
    assert max(D.INTENT_COUNTS) > routing.MAX_INTENTS


def test_the_covering_array_covers_every_pair_and_the_period_metric_scope_triples() -> None:
    rows = combos.covering_rows()
    triples = {(p, m, s) for p, s, m, _ in rows}
    assert len(triples) == len(D.PERIODS) * len(D.metric_ids()) * len(D.SCOPES)
    dims = [[p.id for p in D.PERIODS], [s.id for s in D.SCOPES], list(D.metric_ids()),
            list(D.OUTPUTS)]  # fmt: skip
    for i in range(4):
        for j in range(i + 1, 4):
            got = {(r[i], r[j]) for r in rows}
            assert len(got) == len(dims[i]) * len(dims[j]), (i, j)


def test_every_dimension_value_has_every_text_variant() -> None:
    table = text_variants.load_table()
    want = {
        "period": [p.id for p in D.PERIODS], "scope": [s.id for s in D.SCOPES],
        "metric": list(D.metric_ids()), "output": list(D.OUTPUTS),
        "card_type": list(D.CARD_TYPES), "goal": list(D.GOALS),
    }  # fmt: skip
    for dim, values in want.items():
        assert set(table[dim]) == set(values), dim
        for v in values:
            assert set(table[dim][v]) == set(text_variants.KINDS), (dim, v)
    assert table == text_variants.build_table(), "regenerate: python -m ...bank.text_variants"


def test_the_paid_sample_is_stratified() -> None:
    sample = paid_sample.load()
    assert sample == paid_sample.build(), "regenerate: python -m ...bank.paid_sample"
    cases = [combos.data_case(*c["combo_id"].split(".")[1:]) for c in sample
             if c["combo_id"].startswith("data.")]  # fmt: skip
    for dim, values in (("period", [p.id for p in D.PERIODS]), ("scope", [s.id for s in D.SCOPES]),
                        ("metric", D.metric_ids()), ("output", D.OUTPUTS)):  # fmt: skip
        assert {c["dims"][dim] for c in cases} == set(values), dim
    fams = Counter(c["area"] for c in sample)
    assert {"data", "create", "advise", "analysis", "explain", "unsupported", "ambiguous",
            "intents", "mismatch"} <= set(fams)  # fmt: skip
    assert {c["combo_id"].split(".")[1] for c in sample if c["area"] == "create"} == set(
        D.CARD_TYPES
    )
    assert {c["combo_id"].split(".")[1] for c in sample if c["area"] == "advise"} == set(D.GOALS)
    assert {c["combo_id"].split(".")[-1] for c in sample if c["area"] == "intents"} == {
        str(n) for n in D.INTENT_COUNTS
    }
    assert {c["text_kind"] for c in sample} == set(text_variants.KINDS)
