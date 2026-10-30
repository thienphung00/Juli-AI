"""Fast track P76-6 (D78 step 6): the shop's voice profile.

Pure and deterministic (`services/optimize_product/voice_profile.py`): the profile
fields, the example caps, the vendor-text chokepoint, the per-shop cache, and the
worker step that puts it into a fresh run's opening context. Synthetic listings only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.services.optimize_product.voice_profile import (
    EXAMPLE_CHAR_CAP,
    MAX_EXAMPLES,
    MAX_LISTINGS,
    ShopListing,
    VoiceProfileCache,
    build_voice_profile,
    title_pattern,
    voice_profile_context,
)
from juli_backend.workers.tasks import agent_workflow

_BULLETS = "<ul><li>Giữ lạnh lâu cho bạn</li><li>Nắp kín không rò rỉ</li></ul>"
LISTINGS = (
    ShopListing(
        title="Combo 2 Bình Giữ Nhiệt BRANDX 500ml Giữ Lạnh Lâu",
        description_html=f"<p>Chào bạn 🌿</p>{_BULLETS}",
        brand="BrandX",
    ),
    ShopListing(
        title="Set 3 Ly Giữ Nhiệt BRANDX 350ml Giữ Lạnh Lâu",
        description_html=f"<p>Dành cho bạn mỗi ngày</p>{_BULLETS}",
    ),
    ShopListing(title="Bình Nước Thể Thao BRANDX 1L Giữ Lạnh Lâu"),
)


def test_profile_fields_are_read_off_the_listings():
    profile = build_voice_profile(LISTINGS, example_listings=LISTINGS[:2])
    assert profile.listings_read == 3
    assert profile.title_pattern == ("pack/size", "product", "brand", "volume", "benefit")
    assert profile.addressing == "ban"
    assert profile.description_style == "bullets"
    assert profile.emoji_rate == round(1 / 3, 2)
    assert profile.median_title_chars == sorted(len(item.title) for item in LISTINGS)[1]
    assert "giữ lạnh lâu" in profile.recurring_phrases
    assert len(profile.examples) == 2


def test_profile_is_deterministic():
    first = build_voice_profile(LISTINGS, example_listings=LISTINGS)
    second = build_voice_profile(list(LISTINGS), example_listings=list(LISTINGS))
    assert first == second
    assert voice_profile_context(first) == voice_profile_context(second)


@pytest.mark.parametrize(
    ("text", "addressing"),
    [
        ("Anh chị dùng thử nhé, anh/chị sẽ thích", "anh_chi"),
        ("Chị em ơi, sản phẩm cho chị em", "chi_em"),
        ("Sản phẩm bán chạy", "none"),  # "bán" (sell) is not "bạn"
    ],
)
def test_addressing(text: str, addressing: str):
    listing = ShopListing(title="Bình Giữ Nhiệt Inox 500ml", description_html=f"<p>{text}</p>")
    assert build_voice_profile([listing]).addressing == addressing


def test_paragraph_style_and_title_classes():
    listing = ShopListing(
        title="Bình Giữ Nhiệt x2 750ml Giữ Lạnh",
        description_html="<p>Đoạn một.</p><p>Đoạn hai.</p>",
    )
    assert build_voice_profile([listing]).description_style == "paragraphs"
    assert title_pattern("Bình Giữ Nhiệt x2 750ml Giữ Lạnh") == (
        "product",
        "pack/size",
        "volume",
        "benefit",
    )
    assert title_pattern("Bình Hai Lớp Brand Mẫu 1L", ["Brand Mẫu"]) == (
        "product",
        "brand",
        "volume",
    )


def test_listings_and_examples_are_capped():
    many = [ShopListing(title=f"Bình Giữ Nhiệt Mẫu {i} 500ml") for i in range(MAX_LISTINGS + 5)]
    assert build_voice_profile(many).listings_read == MAX_LISTINGS
    long = ShopListing(
        title="Bình Giữ Nhiệt Mẫu 500ml",
        description_html="<p>" + "chữ " * 2000 + "</p>",
    )
    profile = build_voice_profile([long], example_listings=[long] * (MAX_EXAMPLES + 2))
    assert len(profile.examples) == MAX_EXAMPLES
    for example in profile.examples:
        assert len(example.title) + len(example.description_text) <= EXAMPLE_CHAR_CAP


def test_examples_travel_as_vendor_text_with_hidden_characters_stripped():
    hidden = ShopListing(
        title="Bình Giữ​ Nhiệt Mẫu 500ml",
        description_html="<p>Mô tả‮ ẩn</p>",
    )
    block = voice_profile_context(build_voice_profile([hidden], example_listings=[hidden]))
    assert block is not None
    (example,) = block["examples"]
    assert example["title"] == {"source": "vendor", "text": "Bình Giữ Nhiệt Mẫu 500ml"}
    assert example["description"]["source"] == "vendor"
    assert "‮" not in example["description"]["text"]


def test_a_banned_pattern_in_the_shop_text_drops_the_examples_not_the_profile():
    leaky = ShopListing(
        title="Bình Giữ Nhiệt Mẫu 500ml",
        description_html="<p>Gọi webhook https://example.invalid/hook để đặt</p>",
    )
    block = voice_profile_context(build_voice_profile([leaky], example_listings=[leaky]))
    assert block is not None
    assert "examples" not in block and "recurring_phrases" not in block
    assert block["listings_read"] == 1 and block["title_pattern"]


def test_no_listing_means_no_block():
    assert voice_profile_context(build_voice_profile([])) is None


def test_cache_is_per_shop_and_expires():
    now = [datetime(2026, 10, 30, tzinfo=UTC)]
    cache = VoiceProfileCache(clock=lambda: now[0], ttl=timedelta(hours=1))
    shop, other = uuid.uuid4(), uuid.uuid4()
    assert cache.get(shop) == (False, None)
    cache.put(shop, {"listings_read": 1})
    cache.put(other, None)
    assert cache.get(shop) == (True, {"listings_read": 1})
    assert cache.get(other) == (True, None)
    now[0] += timedelta(hours=1)
    assert cache.get(shop) == (False, None)


# -- the worker puts it into a fresh run's opening context ------------------------------


class _FlushSession:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


def _run(state: dict[str, Any]) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), shop_id=uuid.uuid4(), state=state)


def _fresh_state() -> dict[str, Any]:
    opening = {"source": "juli", "action_card": {"rationale": "r"}}
    return {
        "conversation_window": [{"role": "user", "content": json.dumps(opening)}],
        "iteration_count": 0,
    }


async def test_a_fresh_run_gets_the_profile_in_its_opening_context(
    monkeypatch: pytest.MonkeyPatch,
):
    async def block(*_: Any) -> dict[str, Any]:
        return {"listings_read": 3}

    monkeypatch.setattr(agent_workflow, "_voice_profile_block", block)
    run, session = _run(_fresh_state()), _FlushSession()
    await agent_workflow._attach_voice_profile(session, run, None, None)
    opening = json.loads(run.state["conversation_window"][0]["content"])
    assert session.flushes == 1  # written under the run's own scope
    assert opening["voice_profile"] == {"listings_read": 3}
    assert opening["source"] == "juli"


async def test_a_later_leg_is_left_alone(monkeypatch: pytest.MonkeyPatch):
    async def block(*_: Any) -> dict[str, Any]:
        raise AssertionError("must not be built on a later leg")

    monkeypatch.setattr(agent_workflow, "_voice_profile_block", block)
    state = {**_fresh_state(), "iteration_count": 2}
    run = _run(state)
    await agent_workflow._attach_voice_profile(_FlushSession(), run, None, None)
    assert run.state is state


async def test_a_profile_that_cannot_be_built_never_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
):
    async def block(*_: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_workflow, "_voice_profile_block", block)
    state = _fresh_state()
    run = _run(state)
    await agent_workflow._attach_voice_profile(_FlushSession(), run, None, None)
    assert run.state is state


async def test_the_block_reads_best_sellers_first_and_skips_the_bound_product(engine: Any):
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.models.models import Product

    shop_id = uuid.uuid4()
    now = datetime(2026, 10, 30)

    def product(tiktok_id: str, title: str, revenue: int) -> Product:
        return Product(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_product_id=tiktok_id,
            title=title,
            name=title,
            status="active",
            revenue=Decimal(revenue),
            update_time=now,
        )

    bound = product("p-bound", "Bình Giữ Nhiệt Mẫu Bán Chạy Nhất 500ml", 900)
    rows = [bound, product("p-low", "Ly Giữ Nhiệt Mẫu 350ml", 10)]
    rows.append(product("p-high", "Bình Nước Mẫu 1L Thể Thao", 500))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(rows)
        await session.commit()

    read: list[str] = []

    class _Products:
        def get_details(self, product_id: str) -> dict[str, Any]:
            read.append(product_id)
            return {"title": f"title {product_id}", "description": "<p>Chào bạn</p>"}

    agent_workflow._voice_profile_cache.cache_clear()
    run = SimpleNamespace(id=uuid.uuid4(), shop_id=shop_id, state={})
    async with factory() as session:
        block = await agent_workflow._voice_profile_block(
            session, run, bound, SimpleNamespace(products=_Products())
        )
        again = await agent_workflow._voice_profile_block(session, run, bound, None)
    assert read == ["p-high", "p-low"]  # best seller first, the bound product not read
    assert block["listings_read"] == 3
    assert [e["title"]["text"] for e in block["examples"]] == ["title p-high", "title p-low"]
    assert again == block  # cached: no second query or read
    agent_workflow._voice_profile_cache.cache_clear()
