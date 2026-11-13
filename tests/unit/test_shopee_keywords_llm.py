"""P100-G: keywords built from titles -- the deterministic rules and the one model call.

Synthetic titles only; the model is a scripted fake, nothing reaches OpenAI.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.shop_keywords import llm_seeds
from juli_backend.services.shop_keywords.decompose import Title, decompose
from juli_backend.services.shopee_builder import llm
from tests.unit.test_shopee_keywords import _ops_client, _shopee_shop

SHAPES = [
    Title("1", "ORY Găng tay tự hủy sinh học 100 chiếc - Có VAT"),
    Title("2", "ORY Găng tay tự hủy sinh học 50 chiếc, giá rẻ"),
    Title("3", "STAHAUS Túi đựng thực phẩm phân hủy sinh học (500ml)"),
    Title("4", "STAHAUS Túi đựng thực phẩm phân hủy sinh học x2 lần"),
    Title("5", "1 găng tay nitrile size L"),
    Title("6", "2 găng tay nitrile size M"),
]


class FakeLLM:
    model = "fake-model"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def complete_json(self, *, system, user, schema_name, schema):
        self.calls.append({"user": user, "schema": schema_name})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _keywords(titles=SHAPES, **kw):
    return {c.keyword: c for c in decompose(titles, **kw)}


def test_numbers_collapse_and_fragments_never_become_keywords():
    found = _keywords()
    # "1 găng tay" and "2 găng tay" are one keyword carrying both items.
    assert found["găng tay nitrile"].item_ids == ("5", "6")
    assert found["găng tay"].item_ids == ("1", "2", "5", "6")
    joined = f" | {' | '.join(found)} | "
    for fragment in ("có vat", "tay tự hủy sinh", "đựng thực |", "hủy sinh học stahaus", "size"):
        assert fragment not in joined, fragment
    assert not any(ch.isdigit() for k in found for ch in k)


def test_phrases_never_cross_punctuation_or_cut_a_compound():
    for keyword in _keywords():
        assert not keyword.endswith("thực"), keyword
        assert "sinh học" in keyword or "sinh" not in keyword.split(), keyword
    titles = [Title("1", "Túi rác, tự hủy"), Title("2", "Túi rác, tự hủy")]
    assert not any("rác tự" in k for k in _keywords(titles))


def test_each_title_keeps_its_own_brand():
    found = _keywords()
    assert found["ory găng tay"].item_ids == ("1", "2")
    assert found["stahaus túi đựng thực phẩm"].item_ids == ("3", "4")
    assert not any(k.startswith("ory ") and "thực phẩm" in k for k in found)
    assert not any(k.startswith("stahaus ") and "găng" in k for k in found)


def test_a_sub_phrase_is_dropped_unless_it_stands_alone_or_is_a_head():
    titles = [
        Title("1", "Kem an toàn da nhạy cảm"),
        Title("2", "Sữa an toàn da nhạy cảm"),
        Title("3", "Dầu gội an toàn"),
        Title("4", "Dầu gội an toàn"),
    ]
    found = _keywords(titles)
    assert "an toàn da nhạy" in found
    # "an toàn" ends a chunk in titles 3 and 4, so it stays.
    assert "an toàn" in found
    only_modified = [Title("1", "Kem an toàn da"), Title("2", "Sữa an toàn da")]
    assert "an toàn" not in _keywords(only_modified)


# ------------------------------------------------------------------------- the model step


def _refine(client, titles=SHAPES):
    import asyncio

    return asyncio.run(llm_seeds.refine(client, titles, decompose(titles)))


def test_a_valid_answer_is_kept_and_a_near_word_is_returned_for_the_owner_to_tick():
    client = FakeLLM(
        {
            "heads": ["găng tay", "túi đựng thực phẩm"],
            "attributes": ["phân hủy sinh học"],
            "similar_groups": [{"item_id": "1", "source_word": "găng tay", "similar": ["bao tay"]}],
            "seeds": [
                {"keyword": "găng tay tự hủy sinh học", "item_ids": ["1", "2"]},
                {"keyword": "bao tay tự hủy sinh học", "item_ids": ["1"]},
                {"keyword": "ghế sofa da", "item_ids": ["3"]},  # words in no title: dropped
            ],
        }
    )
    out = _refine(client)
    kept = {c.keyword: c for c in out.seeds}
    assert kept["găng tay tự hủy sinh học"].item_ids == ("1", "2")
    assert [c.keyword for c in out.near] == ["bao tay tự hủy sinh học"]
    assert "ghế sofa da" not in kept and out.heads == ("găng tay", "túi đựng thực phẩm")
    # Titles the model's seeds never mention keep their deterministic candidates.
    assert {"3", "4", "5", "6"} <= {i for c in out.seeds for i in c.item_ids}
    assert client.calls[0]["schema"] == "shop_keyword_seeds"
    assert "ORY Găng tay" in client.calls[0]["user"]


def test_a_near_word_without_a_real_source_title_is_dropped():
    answer = {
        "heads": [],
        "attributes": [],
        "similar_groups": [{"item_id": "999", "source_word": "găng tay", "similar": ["bao tay"]}],
        "seeds": [{"keyword": "bao tay nitrile", "item_ids": ["5"]}],
    }
    out = _refine(FakeLLM(answer))
    assert out.near == () and "bao tay nitrile" not in {c.keyword for c in out.seeds}


def test_the_titles_hash_changes_only_with_the_titles_or_brand():
    base = llm_seeds.titles_hash(SHAPES)
    assert base == llm_seeds.titles_hash(list(reversed(SHAPES)))
    assert base != llm_seeds.titles_hash(SHAPES[:-1])
    assert base != llm_seeds.titles_hash(SHAPES, "ORY")


# ------------------------------------------------------------------------------ the route


def _answer(shop_titles):
    return {
        "heads": ["găng tay"],
        "attributes": [],
        "similar_groups": [{"item_id": "1", "source_word": "rửa", "similar": ["giặt"]}],
        "seeds": [
            {"keyword": "miếng rửa chén xơ mướp", "item_ids": ["1", "2"]},
            {"keyword": "giặt chén xơ mướp", "item_ids": ["1"]},
        ],
    }


async def test_the_route_uses_the_gated_client_stores_near_words_disabled_and_audits_the_hash(
    session, monkeypatch
):
    from tests.support.api import client_for

    _, shop = await _shopee_shop(session)
    fake = FakeLLM(_answer(None))
    seen = []

    async def gated(sess, shop_id):
        seen.append(shop_id)
        return fake

    monkeypatch.setattr(llm, "gated_client", gated)
    app = await _ops_client(session, monkeypatch, "operator")
    url = f"/v1/ops/shops/{shop.id}/shopee/keywords/seeds/generate"
    async with client_for(app) as client:
        first = await client.post(url, json={"brand": "Lumi"})
        second = await client.post(url, json={"brand": "Lumi"})
    app.dependency_overrides.clear()

    body = first.json()
    assert first.status_code == 200, first.text
    assert seen == [shop.id] and len(fake.calls) == 1
    assert body["llm_used"] is True and body["near_keywords"] == ["giặt chén xơ mướp"]
    near = await session.scalar(
        select(ShopKeywordSeed).where(ShopKeywordSeed.keyword == "giặt chén xơ mướp")
    )
    assert near is not None and near.enabled is False and near.pattern == "common_phrase"
    # Same titles after a model run: nothing is sent again.
    assert second.json()["skipped"] == "titles_unchanged" and len(fake.calls) == 1
    audit = (
        await session.scalars(
            select(OpsAuditLog).where(OpsAuditLog.action == "keyword_seeds_generate")
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].after["titles_hash"] == body["titles_hash"] and audit[0].after["llm_used"]
    assert all(t.title not in str(audit[0].after) for t in SHAPES)


async def test_an_unavailable_model_falls_back_to_the_deterministic_candidates(
    session, monkeypatch
):
    from tests.support.api import client_for

    _, shop = await _shopee_shop(session)

    async def off(sess, shop_id):
        raise llm.LLMUnavailable(llm.REASON_CONSENT, "llm_processing")

    monkeypatch.setattr(llm, "gated_client", off)
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        made = await client.post(
            f"/v1/ops/shops/{shop.id}/shopee/keywords/seeds/generate", json={"brand": "Lumi"}
        )
    app.dependency_overrides.clear()
    assert made.status_code == 200
    assert made.json()["llm_used"] is False and made.json()["llm_reason"] == llm.REASON_CONSENT
    assert made.json()["created"] > 0


@pytest.mark.parametrize("bad", [{}, {"seeds": "x"}, {"seeds": [1, None, {"keyword": 3}]}])
def test_a_malformed_answer_degrades_to_the_candidates(bad):
    out = _refine(FakeLLM(bad))
    assert out.near == () and {c.keyword for c in out.seeds} == {
        c.keyword for c in decompose(SHAPES)
    }
