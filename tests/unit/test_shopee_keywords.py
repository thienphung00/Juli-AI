"""ADR-119, migration 111: the Shopee keyword board ("Từ khóa").

On the unit substrate (source text + SQLite):

- the chain: revision id fits ``alembic_version`` (32), sits on 110, the deferred tail moved
  onto it, the additive gate accepts it and its upgrade only adds; vocabularies match the
  models; every model column is created; the lanes are classified (seeds tenant-direct,
  metrics ops-only, no ``shop_id``);
- the decomposer: combinations (never single words) by pattern, with the items they came
  from; diacritics only for matching; size tokens; brand given or inferred; ≥ 2 titles;
  deterministic;
- the collection format and the raw-capture converter: empty is ``blocked`` unless marked
  ``no_match``, never zero; Vietnamese numbers; quoted numbers refused;
- the store: re-upload replaces, a refused retry never erases an ``ok`` row;
- the board: coverage (đã tra / không khớp / bị chặn / chưa tra), weekly history, related
  keywords, title-proposal candidates;
- the Ops routes: generate → trim → upload → board, each write audited; a viewer cannot
  write; a TikTok shop is refused.

The Postgres proof (RLS, grants) is ``tests/integration/test_shopee_keywords_db.py``.
Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models import market as market_models
from juli_backend.models import shop_keywords as seed_models
from juli_backend.models.market import MarketKeywordMetric
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services import shop_keywords
from juli_backend.services.shop_keywords import collection
from juli_backend.services.shop_keywords.decompose import PATTERNS, Title, decompose
from tests.support.builders import make_tenant

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/111_shopee_keywords.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"
NOW = datetime(2026, 11, 3, 3, 0)
DAY1, DAY2 = date(2026, 10, 27), date(2026, 11, 3)

TITLES = [
    Title("1", "Miếng rửa chén xơ mướp Lumi tự nhiên [Chính hãng] Freeship"),
    Title("2", "Lumi Miếng rửa chén xơ mướp loại lớn 2 miếng"),
    Title("3", "Nước rửa chén Lumi tinh dầu sả 500ml"),
    Title("4", "Nước rửa chén sinh học hương sả 500ml giá rẻ"),
    Title("5", "Bàn chải đánh răng tre Lumi 4 cái"),
]


def _module():
    spec = importlib.util.spec_from_file_location("mig111", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =========================================================================== migration 111


def test_migration_111_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "111_shopee_keywords" and len(mig.revision) <= 32
    assert mig.down_revision == "110_ops_shop_platform"
    # ADR-120's 112 (Shopee profit and history) went on 111 and took the deferred tail.
    later = (MIGRATIONS / "versions/112_shopee_profit_and_history.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "128_connector_state"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_111_and_its_upgrade_only_adds():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True
    body = MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]
    # The one drop is the method CHECK, recreated wider on the next line (D81.1).
    widen = 'op.drop_constraint(RESULTS_METHOD_CHECK, RESULTS_TABLE, type_="check")'
    assert body.count(widen) == 1
    assert "op.create_check_constraint(RESULTS_METHOD_CHECK" in body
    body = body.replace(widen, "")
    for verb in ("op.drop_", "op.alter_column", "UPDATE public", "DELETE FROM", "DROP "):
        assert verb not in body, verb


def test_migration_vocabularies_match_the_models_and_the_decomposer():
    mig = _module()
    assert mig.PATTERNS == seed_models.PATTERNS == PATTERNS
    assert mig.PLATFORMS == seed_models.PLATFORMS
    assert mig.STATUSES == market_models.KEYWORD_STATUSES
    assert mig.SOURCES == market_models.KEYWORD_SOURCES


@pytest.mark.parametrize(
    "model", [MarketKeywordMetric, ShopKeywordSeed], ids=lambda m: m.__tablename__
)
def test_every_model_column_is_created_by_the_migration(model):
    source = MIGRATION.read_text("utf-8")
    # ``role`` / ``item_scope`` came later, with migration 112 (ADR-120).
    later = {"role", "item_scope"}
    for column in model.__table__.columns.keys():
        if column in later:
            continue
        assert f'sa.Column("{column}"' in source, f"{model.__tablename__}.{column}"


def test_seeds_are_client_lane_and_metrics_are_public_ops_only():
    assert TABLE_CLASSIFICATION_MAP[("public", "shop_keyword_seeds")] == "tenant_direct"
    assert TABLE_CLASSIFICATION_MAP[("public", "market_keyword_metrics")] == "ops_only"
    assert "shop_id" in ShopKeywordSeed.__table__.columns
    assert "shop_id" not in MarketKeywordMetric.__table__.columns
    mig = _module()
    upgrade = MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]
    assert "_secure_ops(METRICS_TABLE" in upgrade and "_secure_tenant(SEEDS_TABLE" in upgrade
    assert mig.UPSERT_VERBS == "SELECT, INSERT, UPDATE"


# =========================================================================== decomposer


def _by_keyword(candidates):
    return {c.keyword: c for c in candidates}


def test_titles_decompose_into_combinations_with_their_items():
    found = _by_keyword(decompose(TITLES, brand="Lumi"))
    expected = {
        "miếng rửa chén xơ mướp": ("type_function_material", ("1", "2")),
        "miếng rửa chén": ("type_function", ("1", "2")),
        "nước rửa chén": ("type_function", ("3", "4")),
        "nước rửa chén sả": ("type_function_material", ("3", "4")),
        "rửa chén xơ mướp": ("function_material", ("1", "2")),
        "rửa chén 500ml": ("function_size", ("3", "4")),
        "nước rửa chén 500ml": ("type_size", ("3", "4")),
        "lumi rửa chén": ("brand_function", ("1", "2", "3")),
        "rửa chén": ("common_phrase", ("1", "2", "3", "4")),
    }
    for keyword, (pattern, items) in expected.items():
        assert (found[keyword].pattern, found[keyword].item_ids) == (pattern, items), keyword
    # Never a single word; marketing noise and counts never become a keyword.
    assert all(" " in k for k in found)
    assert not any("chính hãng" in k or "freeship" in k or "giá rẻ" in k for k in found)
    assert "2 miếng" not in " | ".join(found)


def test_a_brand_combination_from_one_title_is_kept_other_single_titles_are_not():
    found = _by_keyword(decompose(TITLES, brand="Lumi"))
    assert found["lumi bàn chải đánh răng"].item_ids == ("5",)
    assert "bàn chải đánh răng" not in found  # one title only, no brand
    without_brand = _by_keyword(decompose(TITLES))
    assert not any(k.startswith("lumi") for k in without_brand)


def test_the_brand_is_inferred_from_shared_leading_words_but_never_a_product_word():
    titles = [
        Title("a", "Mộc An nến thơm sả chanh"),
        Title("b", "Mộc An nến thơm oải hương"),
        Title("c", "Mộc An túi thơm treo xe"),
    ]
    found = _by_keyword(decompose(titles))
    assert found["mộc an túi thơm"].pattern == "brand_type"
    assert found["mộc an thơm"].pattern == "brand_function"
    product_led = [Title("a", "Miếng rửa chén A"), Title("b", "Miếng rửa chén B")]
    assert not any(c.pattern.startswith("brand_") for c in decompose(product_led))


def test_diacritics_only_for_matching_and_sizes_are_one_token():
    titles = [
        Title("1", "Dầu gội bồ kết 1,5l"),
        Title("2", "Dau goi bo ket 1,5 L"),
        Title("3", "Dầu gội đầu bồ kết 1,5l"),
    ]
    found = _by_keyword(decompose(titles))
    # The two spellings are one combination, shown with diacritics.
    assert found["dầu gội bồ kết"].item_ids == ("1", "2")
    assert found["gội 1,5l"].pattern == "function_size"
    # "đầu" (head) is not the type "dầu" (oil): it is the object of "gội".
    assert not any(k.startswith("đầu ") for k in found)
    assert all("goi" not in k for k in found)


def test_the_decomposer_is_deterministic_and_ignores_empty_titles():
    shuffled = [*reversed(TITLES), Title("9", "   ")]
    assert decompose(TITLES, brand="Lumi") == decompose(TITLES, brand="Lumi")
    assert _by_keyword(decompose(shuffled, brand="Lumi")) == _by_keyword(
        decompose(TITLES, brand="Lumi")
    )
    assert decompose([]) == []


# =========================================================================== collection format

RAW_OK = {
    "kw": "Miếng rửa chén",
    "sum": "1.250",
    "n": "3",
    "rows": [
        "miếng rửa chén | 1.000 |  | 436 | 3.113 | 67 | 86 | 15",
        "miếng rửa bát | 200 |  | 0 | 0 | 43 | 26 | 2",
        "giẻ rửa chén | 50 |  | 1,5 | 2 | 31 | 29 | 0",
    ],
}


def test_a_raw_capture_becomes_an_ok_record_with_plain_numbers():
    record = collection.from_raw(RAW_OK, collected_on=DAY2)
    assert (record.seed, record.status, record.total_volume) == ("miếng rửa chén", "ok", 1250)
    first = record.rows[0]
    assert (first.volume, first.cpc_min, first.cpc_max, first.difficulty) == (1000, 436, 3113, 67)
    assert record.rows[2].cpc_min == 1.5
    line = collection.dump_jsonl([record])
    assert '"volume": 1000' in line and '"cpc_max": 3113' in line


@pytest.mark.parametrize(
    "rows",
    [[], ["Không có từ khóa khớp bộ lọc"], ["x | 1 | | Không có từ khóa khớp bộ lọc | | | |"]],
)
def test_an_empty_or_refused_result_is_blocked_never_zero(rows):
    record = collection.from_raw({"kw": "cọ tre", "sum": "0", "rows": rows}, collected_on=DAY2)
    assert record.status == "blocked"
    assert record.rows == [] and record.total_volume is None
    marked = collection.from_raw(
        {"kw": "Cọ  Tre", "rows": rows}, collected_on=DAY2, no_match=frozenset({"cọ tre"})
    )
    assert marked.status == "no_match"


def test_the_format_refuses_quoted_numbers_rows_on_blocked_and_empty_ok():
    good = {
        "source": "shopeeanalytics",
        "collected_on": "2026-11-03",
        "seed": "miếng rửa chén",
        "status": "ok",
        "total_volume": 100,
        "rows": [{"keyword": "miếng rửa chén", "volume": 100}],
    }
    assert collection.parse_records([good])[0].rows[0].volume == 100
    bad = [
        {**good, "rows": [{"keyword": "x", "volume": "1.250"}]},
        {**good, "status": "blocked"},
        {**good, "rows": []},
        {**good, "source": "elsewhere"},
        {**good, "extra_field": 1},
    ]
    for n, record in enumerate(bad):
        with pytest.raises(collection.CollectionError) as refused:
            collection.parse_records([record])
        assert refused.value.errors[0].startswith("line 1:"), n
    with pytest.raises(collection.CollectionError) as not_json:
        collection.parse_jsonl('{"source": "shopeeanalytics"\n')
    assert "not JSON" in not_json.value.errors[0]


def test_metric_rows_put_the_seed_first_and_record_an_unlisted_seed_without_numbers():
    record = collection.from_raw(RAW_OK, collected_on=DAY2)
    rows = collection.metric_rows(record)
    assert rows[0].keyword == rows[0].seed == "miếng rửa chén"
    assert rows[0].extra == {"total_volume": 1250, "listed": True}
    unlisted = collection.from_raw({**RAW_OK, "kw": "rửa chén"}, collected_on=DAY2)
    first = collection.metric_rows(unlisted)[0]
    assert (first.keyword, first.volume, first.extra["listed"]) == ("rửa chén", None, False)
    blocked = collection.from_raw({"kw": "x y", "rows": []}, collected_on=DAY2)
    assert [(r.keyword, r.status, r.volume) for r in collection.metric_rows(blocked)] == [
        ("x y", "blocked", None)
    ]


def test_the_cli_converts_a_capture_with_the_folder_date(tmp_path):
    from scripts.shopeeanalytics_keywords import main

    folder = tmp_path / "2026-11-03"
    folder.mkdir()
    raw = folder / "raw.jsonl"
    raw.write_text(
        '{"kw": "Miếng rửa chén", "sum": "1.250", '
        '"rows": ["miếng rửa chén | 1.000 |  | 1 | 2 | 3 | 4 | 5"]}\n'
        '{"kw": "cọ tre", "sum": "", "rows": []}\n',
        "utf-8",
    )
    out = tmp_path / "out.jsonl"
    assert main([str(raw), "-o", str(out)]) == 0
    records = collection.parse_jsonl(out.read_text("utf-8"))
    assert [(r.collected_on, r.status) for r in records] == [(DAY2, "ok"), (DAY2, "blocked")]
    assert main(["--check", str(out)]) == 0


# =========================================================================== store + board


def _record(seed, status="ok", rows=(), day=DAY2, total=None):
    return collection.CollectionRecord.model_validate(
        {
            "source": "shopeeanalytics",
            "collected_on": day,
            "seed": seed,
            "status": status,
            "total_volume": total,
            "rows": [{"keyword": k, "volume": v, "cpc_min": 100, "cpc_max": 900} for k, v in rows],
        }
    )


async def test_a_reupload_replaces_and_a_refused_retry_never_erases_ok(session):
    first = await shop_keywords.store_records(
        session,
        [_record("nước rửa chén", rows=[("nước rửa chén", 300), ("nước rửa bát", 80)])],
        now=NOW,
    )
    assert (first.rows_written, first.by_status) == (2, {"ok": 1})
    again = await shop_keywords.store_records(
        session, [_record("nước rửa chén", rows=[("nước rửa chén", 320)])], now=NOW
    )
    refused = await shop_keywords.store_records(
        session, [_record("nước rửa chén", "blocked")], now=NOW
    )
    assert again.rows_written == 1 and refused.rows_kept == 1
    rows = (
        await session.scalars(
            select(MarketKeywordMetric).where(MarketKeywordMetric.keyword == "nước rửa chén")
        )
    ).all()
    assert [(r.status, r.volume) for r in rows] == [("ok", 320)]


def _seed(shop_id, keyword, items, pattern="type_function", enabled=True):
    return ShopKeywordSeed(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        keyword=keyword,
        pattern=pattern,
        item_ids=list(items),
        enabled=enabled,
        created_at=NOW,
        updated_at=NOW,
    )


def _metric(keyword, seed, day, status="ok", volume=None):
    return MarketKeywordMetric(
        id=uuid.uuid4(),
        platform="shopee",
        source="shopeeanalytics",
        keyword=keyword,
        seed=seed,
        collected_on=day,
        status=status,
        volume=volume,
        extra={},
    )


def test_the_board_reports_coverage_history_related_and_title_candidates():
    shop = uuid.uuid4()
    seeds = [
        _seed(shop, "nước rửa chén", ["3", "4"]),
        _seed(shop, "miếng rửa chén", ["1", "2"]),
        _seed(shop, "rửa chén xơ mướp", ["1"]),
        _seed(shop, "giẻ lau bếp", ["5"]),
        _seed(shop, "lumi rửa chén", ["3"], pattern="brand_function", enabled=False),
    ]
    titles = [Title(i, f"Synthetic {i}") for i in ("1", "2", "3", "4", "5", "6")]
    metrics = [
        _metric("nước rửa chén", "nước rửa chén", DAY1, volume=250),
        _metric("nước rửa chén", "nước rửa chén", DAY2, volume=300),
        _metric("nước rửa bát", "nước rửa chén", DAY2, volume=90),
        # Listed only as another seed's related keyword: looked up, with a volume.
        _metric("miếng rửa chén", "nước rửa chén", DAY2, volume=40),
        _metric("rửa chén xơ mướp", "rửa chén xơ mướp", DAY2, "no_match"),
        _metric("giẻ lau bếp", "giẻ lau bếp", DAY2, "blocked"),
    ]
    board = shop_keywords.build_board(seeds, titles, metrics, min_volume=100)
    by = {k["keyword"]: k for k in board["keywords"]}
    assert by["nước rửa chén"]["coverage"] == "da_tra"
    assert by["nước rửa chén"]["history"] == [
        {"collected_on": "2026-10-27", "volume": 250},
        {"collected_on": "2026-11-03", "volume": 300},
    ]
    assert [r["keyword"] for r in by["nước rửa chén"]["related"]] == [
        "nước rửa bát",
        "miếng rửa chén",
    ]
    assert (by["miếng rửa chén"]["coverage"], by["miếng rửa chén"]["latest"]["volume"]) == (
        "da_tra",
        40,
    )
    assert by["rửa chén xơ mướp"]["coverage"] == "khong_khop"
    assert by["giẻ lau bếp"]["coverage"] == "bi_chan" and by["giẻ lau bếp"]["latest"] is None
    # The disabled seed is listed last and counted nowhere.
    assert board["keywords"][-1]["keyword"] == "lumi rửa chén"
    assert board["coverage"] == {"da_tra": 2, "khong_khop": 1, "bi_chan": 1, "chua_tra": 0}
    assert board["to_look_up"] == ["giẻ lau bếp"]
    status = {p["item_id"]: p["status"] for p in board["products"]}
    assert status == {
        "1": "de_xuat_tieu_de",  # looked up everywhere, best 40 < 100
        "2": "de_xuat_tieu_de",
        "3": "co_tu_khoa",
        "4": "co_tu_khoa",
        "5": "chua_du_du_lieu",  # its only seed was refused: not yet known
        "6": "de_xuat_tieu_de",  # no combination at all
    }
    assert board["collection_dates"] == ["2026-10-27", "2026-11-03"]


def test_before_any_seed_no_product_is_a_title_candidate():
    board = shop_keywords.build_board([], [Title("1", "Synthetic")], [], min_volume=100)
    assert board["products"][0]["status"] == "chua_du_du_lieu"
    assert board["keywords"] == [] and board["to_look_up"] == []


# =========================================================================== Ops routes


async def _shopee_shop(session, platform="shopee"):
    user, shop = await make_tenant(session)
    shop.platform = platform
    for title in TITLES:
        session.add(
            PlatformItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                platform="shopee",
                item_id=title.item_id,
                name=title.title,
                source="file",
                source_rank=2,
                source_version="test",
                captured_at=NOW,
                updated_at=NOW,
            )
        )
    await session.flush()
    return user, shop


async def _ops_client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def test_an_operator_generates_trims_uploads_and_reads_the_board(session, monkeypatch):
    from tests.support.api import client_for

    _, shop = await _shopee_shop(session)
    app = await _ops_client(session, monkeypatch, "operator")
    base = f"/v1/ops/shops/{shop.id}/shopee/keywords"
    upload = collection.from_raw(
        {
            "kw": "nước rửa chén",
            "sum": "300",
            "rows": ["nước rửa chén | 300 |  | 1 | 2 | 3 | 4 | 5"],
        },
        collected_on=DAY2,
    ).model_dump(mode="json")
    async with client_for(app) as client:
        made = await client.post(f"{base}/seeds/generate", json={"brand": "Lumi"})
        assert made.status_code == 200, made.text
        again = await client.post(f"{base}/seeds/generate", json={"brand": "Lumi"})
        before = (await client.get(base)).json()
        target = next(k for k in before["keywords"] if k["keyword"] == "lumi rửa chén")
        trimmed = await client.put(f"{base}/seeds/{target['id']}", json={"enabled": False})
        stored = await client.post("/v1/ops/market/keyword-metrics", json={"records": [upload]})
        refused = await client.post(
            "/v1/ops/market/keyword-metrics", json={"records": [{**upload, "rows": []}]}
        )
        after = (await client.get(base, params={"min_volume": 200})).json()
        regenerated = await client.post(f"{base}/seeds/generate", json={"brand": "Lumi"})
    app.dependency_overrides.clear()

    assert made.json()["created"] > 0 and again.json() == {**made.json(), "created": 0}
    assert trimmed.json()["seed"]["enabled"] is False
    assert stored.status_code == 200 and stored.json()["by_status"] == {"ok": 1}
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "invalid_keyword_collection"
    by = {k["keyword"]: k for k in after["keywords"]}
    assert by["nước rửa chén"]["latest"]["volume"] == 300
    assert by["nước rửa chén"]["products"][0]["name"] == TITLES[2].title
    assert by["lumi rửa chén"]["enabled"] is False
    # Re-generating never re-enables a trimmed combination.
    assert regenerated.json()["created"] == 0
    kept = await session.scalar(
        select(ShopKeywordSeed).where(ShopKeywordSeed.id == uuid.UUID(target["id"]))
    )
    assert kept is not None and kept.enabled is False
    actions = (await session.scalars(select(OpsAuditLog.action))).all()
    assert {"keyword_seeds_generate", "keyword_seed_toggle", "keyword_metrics_upload"} <= set(
        actions
    )


async def test_a_viewer_cannot_write_and_a_tiktok_shop_is_refused(session, monkeypatch):
    from tests.support.api import client_for

    _, shop = await _shopee_shop(session)
    _, tiktok = await _shopee_shop(session, platform="tiktok")
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        generate = await client.post(f"/v1/ops/shops/{shop.id}/shopee/keywords/seeds/generate")
        upload = await client.post("/v1/ops/market/keyword-metrics", json={"records": [{}]})
        board = await client.get(f"/v1/ops/shops/{shop.id}/shopee/keywords")
        other = await client.get(f"/v1/ops/shops/{tiktok.id}/shopee/keywords")
    app.dependency_overrides.clear()
    assert (generate.status_code, upload.status_code) == (403, 403)
    assert board.status_code == 200 and board.json()["keywords"] == []
    assert other.status_code == 409
