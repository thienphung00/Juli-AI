"""A newly connected, non-reference shop runs the whole journey (fast track P61-E, D71.5).

One test, real Postgres, every database touch as `juli_app` (RLS enforced), nothing
reaches TikTok or OpenAI: a fake TikTok transport (`requests.Session.request`) serves
the recorded ADR-101 samples (`docs/integrations/tiktok_api/samples/`) plus
contract-shaped analytics, and `FakeLLMService` plays the model. Shop A is a
pre-existing production shop (own read credential) that is present the whole time;
the sandbox shop holds the one `sandbox_write` credential. Shop B is connected from
scratch and walks:

1. OAuth: `begin_tiktok_oauth` mints a signed state, `complete_tiktok_oauth_callback`
   exchanges the code (through the real `TikTokAuth` over the fake transport), the
   vendor-verified binding returns B's cipher, and the shop + credential rows land with
   the merchant id the connect flow returned (the OAuth `open_id`, P61-G) and the
   `seller_connect` capability. The callback enqueues the bootstrap (a recording
   dispatcher stands in for Celery).
2. `run_bootstrap_task` (the body of `bootstrap_shop`) runs the fast phase: orders,
   products, analytics for B only; the quick scan writes B's first card (`proposed`);
   `score_and_persist_cards` runs as the task wires it.
3. `approve_action_card` -> `accepted`; the agent workflow runs through the real
   `_run_agent_workflow_async` / `_resume_agent_workflow_async` shells with the REAL
   read and write composition: reads go out under B's own credential (`get_shop_identity`
   answers `verified` with B's name), the model streams (`assistant.text.delta` then
   `assistant.text`), the write takes the sandbox leg (`write_mode='simulated'`) and the
   run ends with an `executed` card event.
4. A product re-read after a seller edit: `external_changes` (`seller_change`) and a
   `seller_change` card event that links the run that wrote the field.
5. The impact reader skips the simulated execution (no `impact_readings` for B).
6. After every step, shop A's rows are exactly what they were, A's scope sees none of
   B's rows (and the reverse), and not one request carried A's token.

Not covered here (DEBT): a LIVE production write for B (the agent-run production leg is
fast track P61-F) and the live `shown` / `expired` writers across days.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.core.security import resolve_read_credential_for_shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    AUTHORIZED_SHOPS_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_DIAGNOSES_PATH,
    PRODUCT_SEARCH_PATH,
    PRODUCT_SEO_WORDS_PATH,
    PRODUCT_SUGGESTIONS_PATH,
    RETURN_SEARCH_PATH,
)
from juli_backend.services.agent.approval import approve_action_card
from juli_backend.services.agent.llm import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent_runs import list_runs
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion import make_etl_handoff, set_bootstrap_dispatcher
from juli_backend.services.onboarding import quick_scan
from juli_backend.services.product_history import job as product_history_job
from juli_backend.services.tiktok import oauth
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from juli_backend.workers.services.polling import FujiwaPollConfig
from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
from juli_backend.workers.tasks import agent_workflow
from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_bootstrap_task
from tests.integration.test_shop_ingestion_two_tenant import committing_juli_app_session
from tests.integration.tiktok_recorded_replay import load_sample
from tests.integration.two_tenant import RUNTIME_ROLE, seed_tenant
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    juli_app_sync_sessionmaker,
    requires_postgres,
)
from tests.support.shop_ingestion_fakes import FakeRateLimiter

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

# -- test data (nothing here is read by production code) ---------------------------------

APP_KEY = "p61e-app-key"
APP_SECRET = "p61e-app-secret"
ENCRYPTION_KEY = "p61e-token-encryption-key"

#: The vendor-side identity of each shop, as the fake TikTok answers for its token.
B_TOKEN, B_REFRESH = "p61e-b-access", "p61e-b-refresh"
B_OPEN_ID = "p61e-open-id-b"
B_CIPHER = "ROW_p61e_cipher_b"
B_SHOP_NAME = "Cửa hàng B (P61-E)"
SANDBOX_TOKEN = "p61e-sandbox-access"
SANDBOX_CIPHER = "ROW_p61e_cipher_sandbox"
SANDBOX_MERCHANT = "p61e-sandbox-merchant"
A_TOKENS = ("p61e-a-access", "p61e-a-access-expiring")
A_CIPHER = "ROW_p61e_cipher_a"
A_MERCHANT = "p61e-merchant-a"
AUTH_CODE = "p61e-auth-code-b"

#: Shop B's catalogue: the recorded Fujiwa sample product is B's weak listing.
PRODUCTS_SAMPLE = load_sample("products-search-response.json")["response"]["data"]["products"]
#: The recorded sample listing is a free gift ("[Quà Tặng]"), which is never optimised; B's weak
#: listing is the same recorded shape under another id and a regular title.
GIFT_PRODUCT_ID = PRODUCTS_SAMPLE[0]["id"]
WEAK_PRODUCT_ID = "7340000000000061001"
WEAK_PRODUCT_TITLE = "Chai xịt thơm miệng Fujisalt 14mL"
PEER_PRODUCT_IDS = tuple(f"73400000000000612{i:02d}" for i in range(5))
SELLER_EDIT_TITLE = "Tiêu đề do người bán tự sửa (P61-E)"

#: One fixed clock for the ingestion windows; the DB-side windows use now().
INGEST_NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
LATEST_ANALYTICS_DAY = date(2026, 10, 19)

# Long enough to stream: the relay holds back 64 characters and flushes at 48 (text_stream.py).
FIRST_NARRATION = (
    "Mình xác nhận đúng shop của bạn rồi đọc tiêu đề, mô tả và ảnh chính của sản phẩm, "
    "để mọi đề xuất bám vào những gì bạn đang có chứ không đoán. Xong mình sẽ soạn tiêu đề "
    "mới cho bạn duyệt."
)
FINAL_TEXT = (
    "Tiêu đề mới đã được chạy thử trên shop thử nghiệm của Juli, còn shop thật của bạn chưa "
    "thay đổi gì. Mình sẽ không tính kết quả của lần chạy thử này vào hiệu quả, và sẽ theo dõi "
    "lượt hiển thị cùng tỉ lệ bấm khi bạn áp dụng thật."
)
#: P76-4 (D78.1): a proposal keeps the 40-character minimum and the current title's
#: must-keep tokens (brand, "14mL").
NEW_TITLE = "Chai xịt thơm miệng Fujisalt 14mL giữ hơi thở thơm mát cả ngày (P61-E)"
STREAM_CHUNK_CHARS = 16


# -- the fake TikTok transport ------------------------------------------------------------


@dataclass
class Call:
    method: str
    host: str
    path: str
    token: str | None
    cipher: str | None
    params: dict[str, str]
    body: dict[str, Any]


def _envelope(data: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.text = ""
    response.json.return_value = {
        "code": 0,
        "message": "Success",
        "request_id": "p61e-replay",
        "data": data,
    }
    response.raise_for_status = MagicMock()
    return response


@dataclass
class ListingWorld:
    """What TikTok currently shows for one product (the seller can edit it)."""

    title: str
    update_time: int


@dataclass
class TikTokReplay:
    """`requests.Session.request` replaced by recorded samples + contract-shaped analytics.

    Every request is recorded with the access token and shop cipher it was signed with.
    A token the replay does not know (shop A's included) is a test failure, so a run that
    reached for another shop's credential cannot pass quietly.
    """

    #: token -> shop cipher the vendor ties it to (Get Authorized Shops answers by token).
    known_tokens: dict[str, str] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    listings: dict[str, ListingWorld] = field(default_factory=dict)
    sandbox_edits: list[dict[str, Any]] = field(default_factory=list)

    def request(self, *args: Any, **kwargs: Any) -> MagicMock:
        method, url = (
            (str(args[-2]), str(args[-1]))
            if len(args) >= 2
            else (
                str(kwargs["method"]),
                str(kwargs["url"]),
            )
        )
        parsed = urlparse(url)
        params = {k: str(v) for k, v in (kwargs.get("params") or {}).items()}
        params.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
        raw_body = kwargs.get("json")
        if raw_body is None and isinstance(kwargs.get("data"), str | bytes):
            raw_body = json.loads(kwargs["data"] or "{}")
        body = raw_body if isinstance(raw_body, dict) else {}
        headers = kwargs.get("headers") or {}
        token = headers.get("x-tts-access-token")
        call = Call(
            method=method,
            host=parsed.netloc,
            path=parsed.path,
            token=token,
            cipher=params.get("shop_cipher"),
            params=params,
            body=body,
        )
        self.calls.append(call)
        if parsed.netloc.startswith("auth."):
            return _envelope(self._token_exchange(params))
        assert token in self.known_tokens, (
            f"{method} {parsed.path} carried an unknown access token {token!r}: a request "
            "reached TikTok under a credential this journey does not own"
        )
        return _envelope(self._route(call))

    # -- OAuth ---------------------------------------------------------------------------

    def _token_exchange(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("auth_code") == AUTH_CODE
        return {
            "access_token": B_TOKEN,
            "refresh_token": B_REFRESH,
            "access_token_expire_in": int((datetime.now(UTC) + timedelta(days=7)).timestamp()),
            "refresh_token_expire_in": int((datetime.now(UTC) + timedelta(days=365)).timestamp()),
            "open_id": B_OPEN_ID,
            "seller_name": B_SHOP_NAME,
            "granted_scopes": ["seller.product.basic", "seller.order.info"],
        }

    # -- routing -------------------------------------------------------------------------

    def _route(self, call: Call) -> dict[str, Any]:
        path = call.path
        if path == AUTHORIZED_SHOPS_PATH:
            return self._authorized_shops(call)
        if path == ORDER_SEARCH_PATH:
            return self._recorded("orders-search-response.json", "orders", call)
        if path == RETURN_SEARCH_PATH:
            return self._recorded("returns-search-response.json", "return_orders", call)
        if path == INVENTORY_SEARCH_PATH:
            return self._recorded("inventory-search-response.json", None, call)
        if path == PRODUCT_SEARCH_PATH:
            return self._product_search()
        if path == PRODUCT_DIAGNOSES_PATH:
            return self._diagnoses(call)
        if path in (PRODUCT_SEO_WORDS_PATH, PRODUCT_SUGGESTIONS_PATH):
            return {}
        match = re.fullmatch(r"/product/\d+/products/([^/]+)", path)
        if match:
            return self._product(call, match.group(1))
        if path.startswith("/analytics/") or path.startswith("/promotion/"):
            return self._analytics(call)
        raise AssertionError(f"unexpected TikTok request: {call.method} {path}")

    def _authorized_shops(self, call: Call) -> dict[str, Any]:
        shop = copy.deepcopy(
            load_sample("authorized-shops-response.json")["response"]["data"]["shops"][0]
        )
        cipher = self.known_tokens[call.token or ""]
        shop["cipher"] = cipher
        shop["name"] = {
            B_CIPHER: B_SHOP_NAME,
            SANDBOX_CIPHER: "Sandbox shop (P61-E)",
            A_CIPHER: "Shop A (P61-E)",
        }[cipher]
        return {"shops": [shop]}

    def _recorded(self, name: str, items_key: str | None, call: Call) -> dict[str, Any]:
        data = copy.deepcopy(load_sample(name)["response"]["data"])
        data.pop("next_page_token", None)
        data.pop("page_token", None)
        # The recorded capture is served whole for any window: its rows are years old, so a
        # time filter would empty the first pull; the ETL upserts are idempotent anyway.
        del items_key, call
        return data

    # -- products ------------------------------------------------------------------------

    def _world(self, product_id: str) -> ListingWorld | None:
        return self.listings.get(product_id)

    def _product_search(self) -> dict[str, Any]:
        products = [copy.deepcopy(PRODUCTS_SAMPLE[0])]
        for product_id, title in (
            (WEAK_PRODUCT_ID, WEAK_PRODUCT_TITLE),
            *((pid, f"Sản phẩm đối chứng {n}") for n, pid in enumerate(PEER_PRODUCT_IDS, 1)),
        ):
            item = copy.deepcopy(PRODUCTS_SAMPLE[0])
            item["id"], item["title"] = product_id, title
            products.append(item)
        for item in products:
            world = self._world(item["id"])
            if world is not None:
                item["title"] = world.title
                item["update_time"] = world.update_time
        return {"products": products, "total_count": len(products)}

    def _product(self, call: Call, product_id: str) -> dict[str, Any]:
        if call.method == "PUT":
            assert call.token == SANDBOX_TOKEN, (
                "a listing write must go out under the sandbox credential only "
                f"(token {call.token!r})"
            )
            self.sandbox_edits.append({"product_id": product_id, "body": call.body})
            return {"product_id": product_id}
        detail = copy.deepcopy(load_sample("products-detail-response.json")["response"]["data"])
        detail["id"] = product_id
        if product_id == WEAK_PRODUCT_ID:
            detail["title"] = WEAK_PRODUCT_TITLE
        elif product_id in PEER_PRODUCT_IDS:
            detail["title"] = f"Sản phẩm đối chứng {PEER_PRODUCT_IDS.index(product_id) + 1}"
        world = self._world(product_id)
        if world is not None:
            detail["title"] = world.title
            detail["update_time"] = world.update_time
        return detail

    def _diagnoses(self, call: Call) -> dict[str, Any]:
        ids = [i for i in call.params.get("product_ids", "").split(",") if i]
        return {
            "products": [
                {
                    "id": product_id,
                    "diagnoses": [
                        {
                            "field": "MAIN_IMAGE",
                            "diagnosis_results": [{"code": "MAIN_IMG_NUMBER_LESS_THAN_FIVE"}],
                        }
                    ]
                    if product_id == WEAK_PRODUCT_ID
                    else [],
                }
                for product_id in ids
            ]
        }

    # -- analytics (contract-shaped; no ADR-101 capture exists for these envelopes) -----------

    def _days(self, call: Call) -> list[date]:
        first = date.fromisoformat(call.params["start_date_ge"])
        last = min(
            date.fromisoformat(call.params["end_date_lt"]) - timedelta(days=1), LATEST_ANALYTICS_DAY
        )
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]

    def _analytics(self, call: Call) -> dict[str, Any]:
        path = call.path
        days = self._days(call) if "start_date_ge" in call.params else []
        latest = {"latest_available_date": LATEST_ANALYTICS_DAY.isoformat()}
        if path == ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH:
            return {"products": self._product_rows(), "total_count": 1 + len(PEER_PRODUCT_IDS)}
        if path == ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH:
            return {"skus": [], "total_count": 0}
        if path == ANALYTICS_SHOP_PERFORMANCE_PATH:
            return {
                **latest,
                "performance": {
                    "intervals": [
                        {
                            "start_date": day.isoformat(),
                            "end_date": (day + timedelta(days=1)).isoformat(),
                            "sales": {
                                "gmv": {"overall": {"amount": "5000000.00", "currency": "VND"}},
                                "orders_count": 9,
                                "sku_orders_count": 9,
                                "items_sold": 12,
                            },
                            "traffic": {"avg_visitors": 400, "avg_conversation_rate": "0.05"},
                        }
                        for day in days
                    ]
                },
            }
        if path in (
            ANALYTICS_BESTSELLING_PRODUCTS_PATH,
            ANALYTICS_BESTSELLING_VIDEOS_PATH,
        ):
            return {"products": [], "videos": []}
        if path == ANALYTICS_LIVE_PERFORMANCE_LIST_PATH:
            return {"live_stream_sessions": [], "total_count": 0}
        detail = re.fullmatch(r"/analytics/\d+/shop_products/([^/]+)/performance", path)
        if detail:
            weak = detail.group(1) == WEAK_PRODUCT_ID

            def ctr_of(day: date) -> str:
                # B's weak listing: its CTR fell by more than half over the last two weeks
                # (the metric-first trigger's "fall beyond its band"); the peers are steady.
                return (
                    "0.02" if weak and day > LATEST_ANALYTICS_DAY - timedelta(days=14) else "0.05"
                )

            orders = 2
            return {
                **latest,
                "performance": {
                    "intervals": [
                        {
                            "start_date": day.isoformat(),
                            "end_date": (day + timedelta(days=1)).isoformat(),
                            "sales": {
                                "gmv": {"amount": str(orders * 200_000), "currency": "VND"},
                                "items_sold": orders,
                                "orders": orders,
                            },
                            "traffic": {
                                "breakdowns": [
                                    {
                                        "content_type": "VIDEO",
                                        "traffic": {"impressions": 2000, "ctr": ctr_of(day)},
                                    }
                                ]
                            },
                        }
                        for day in days
                    ]
                },
            }
        if re.fullmatch(r"/analytics/\d+/shop/performance/[\d-]+/performance_per_hour", path):
            return {"performance": {"intervals": []}}
        if path.startswith("/promotion/"):
            return {"activities": [], "total_count": 0}
        raise AssertionError(f"unexpected analytics request: {call.method} {path}")

    def _product_rows(self) -> list[dict[str, Any]]:
        def row(product_id: str, impressions: int, clicks: int, orders: int) -> dict[str, Any]:
            return {
                "id": product_id,
                "total_performance": {
                    "gmv": {"amount": str(orders * 200_000), "currency": "VND"},
                    "orders": orders,
                    "sku_orders": orders,
                    "items_sold": orders,
                    "ctr": "0.05",
                    "click_order_rate": "0.10",
                    "product_impressions": impressions,
                    "product_clicks": clicks,
                },
            }

        rows = [row(pid, 30_000, 1500, 75) for pid in PEER_PRODUCT_IDS]
        rows.append(row(WEAK_PRODUCT_ID, 30_000, 600, 30))
        return rows


# -- database helpers -----------------------------------------------------------------------


def _owner_scalar(owner_engine, sql: str, **params: Any) -> Any:
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _impact_readings(owner_engine, shop_id: uuid.UUID) -> int:
    """`impact_readings` has no shop column; it belongs to a shop through its execution."""
    return _owner_scalar(
        owner_engine,
        "SELECT count(*) FROM public.impact_readings r "
        "JOIN public.tool_executions e ON e.id = r.tool_execution_id WHERE e.shop_id = :shop",
        shop=str(shop_id),
    )


def _tenant_tables(owner_engine) -> list[str]:
    """Every schema-qualified table with a `shop_id` column that `juli_app` may read.

    Ops-only tables (`ops_audit_log`, ...) are refused to the runtime role outright, so there is
    nothing for a scope to leak through them.
    """
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ns.nspname || '.' || cls.relname FROM pg_class cls "
                "JOIN pg_namespace ns ON ns.oid = cls.relnamespace "
                "  AND ns.nspname IN ('public', 'silver', 'bronze', 'gold') "
                "JOIN pg_attribute att ON att.attrelid = cls.oid AND att.attname = 'shop_id' "
                "  AND NOT att.attisdropped "
                "WHERE cls.relkind IN ('r', 'p') "
                "AND has_table_privilege(CAST(:role AS name), cls.oid, 'SELECT') "
                "ORDER BY 1"
            ),
            {"role": RUNTIME_ROLE},
        )
        return [row[0] for row in rows]


# SQL below interpolates only table names read from the catalog (`_tenant_tables`), never input.
def _counts(owner_engine, tables: list[str], shop_id: uuid.UUID) -> Counter[str]:
    """Rows per tenant table for one shop, read as the owner (what is really stored)."""
    counts: Counter[str] = Counter()
    with owner_engine.connect() as conn:
        for table in tables:
            counts[table] = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE shop_id = :shop"),  # nosec B608
                {"shop": str(shop_id)},
            ).scalar_one()
    return counts


async def _visible_rows_of_other_shop(
    tables: list[str], *, scope: uuid.UUID, other: uuid.UUID
) -> dict[str, int]:
    """Under `scope`, as `juli_app`, how many rows of `other` does each table show?"""
    seen: dict[str, int] = {}
    async with committing_juli_app_session(scope) as session:
        for table in tables:
            count = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE shop_id = :other"),  # nosec B608
                    {"other": str(other)},
                )
            ).scalar_one()
            if count:
                seen[table] = count
            await session.rollback()
    return seen


# -- seeding (set-up as the owner; the journey itself runs as `juli_app`) ----------------------


@dataclass
class Journey:
    """Ids and handles the journey's steps share."""

    owner_engine: Any
    replay: TikTokReplay
    tables: list[str]
    shop_a: uuid.UUID
    sandbox_shop: uuid.UUID
    user_b: uuid.UUID
    shop_b: uuid.UUID | None = None
    #: What the OAuth callback queued for the bootstrap (the task's `connect_committed_at` ...).
    bootstrap_call: dict[str, Any] = field(default_factory=dict)
    card_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    a_before: Counter[str] = field(default_factory=Counter)
    sandbox_before: Counter[str] = field(default_factory=Counter)


def _seed_user(conn, label: str) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.users (id, phone, display_name, created_at, updated_at) "
            "VALUES (:id, :phone, :name, :now, :now)"
        ),
        {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "name": label, "now": now},
    )
    return user_id


def _seed_sandbox_shop(owner_engine) -> uuid.UUID:
    """The shop that holds the one `sandbox_write` credential (the sandbox merchant)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    shop_id = uuid.uuid4()
    with owner_engine.begin() as conn:
        user_id = _seed_user(conn, "sandbox owner")
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, created_at, "
                " updated_at) VALUES (:id, :user, 'Sandbox shop', :tt, :now, :now)"
            ),
            {"id": str(shop_id), "user": str(user_id), "tt": "p61e-sandbox-open-id", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials (id, shop_id, merchant_authorization_id, "
                " capability, shop_cipher, access_token, refresh_token, token_expires_at, status, "
                " refresh_count, created_at, updated_at) VALUES (:id, :shop, :merchant, "
                " 'sandbox_write', :cipher, :token, 'sandbox-refresh', :expires, 'active', 0, "
                " :now, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop": str(shop_id),
                "merchant": SANDBOX_MERCHANT,
                "cipher": SANDBOX_CIPHER,
                "token": SANDBOX_TOKEN,
                "expires": now + timedelta(days=30),
                "now": now,
            },
        )
    return shop_id


def _make_shop_a_a_production_shop(owner_engine, tenant) -> None:
    """Shop A: a connected production shop with its own known read credential."""
    with owner_engine.begin() as conn:
        for credential_id, token, capability in (
            (tenant.fresh_credential_id, A_TOKENS[0], "seller_connect"),
            (tenant.expiring_credential_id, A_TOKENS[1], None),
        ):
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials SET access_token = :token, "
                    " capability = :capability, shop_cipher = :cipher, "
                    " merchant_authorization_id = :merchant WHERE id = :id"
                ),
                {
                    "token": token,
                    "capability": capability,
                    "cipher": A_CIPHER if capability else None,
                    "merchant": A_MERCHANT if capability else None,
                    "id": str(credential_id),
                },
            )


class _RecordingDispatcher:
    """Stands in for Celery's `bootstrap_shop.apply_async` (the broker is out of scope)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, shop_id: str, *, connect_committed_at, enqueued_at) -> str:
        self.calls.append(
            {
                "shop_id": shop_id,
                "connect_committed_at": connect_committed_at,
                "enqueued_at": enqueued_at,
            }
        )
        return "p61e-bootstrap-task"


async def _no_sleep(_seconds: float) -> None:
    return None


@contextlib.asynccontextmanager
async def owner_async_session():
    """An async session as the table owner (RLS does not apply); commits really commit."""
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def _assert_isolated(journey: Journey, step: str) -> None:
    """Shop A is exactly as it was; neither shop's scope shows the other's rows."""
    owner = journey.owner_engine
    assert _counts(owner, journey.tables, journey.shop_a) == journey.a_before, (
        f"after {step}: shop A's rows changed"
    )
    # The sandbox shop is a tenant too: B's journey writes nothing onto it (its credential is
    # only ever READ to sign the sandbox write).
    assert _counts(owner, journey.tables, journey.sandbox_shop) == journey.sandbox_before, (
        f"after {step}: the sandbox shop's rows changed"
    )
    if journey.shop_b is None:
        return
    seen_by_a = await _visible_rows_of_other_shop(
        journey.tables, scope=journey.shop_a, other=journey.shop_b
    )
    assert seen_by_a == {}, f"after {step}: shop A's scope sees B's rows {seen_by_a}"
    seen_by_b = await _visible_rows_of_other_shop(
        journey.tables, scope=journey.shop_b, other=journey.shop_a
    )
    assert seen_by_b == {}, f"after {step}: shop B's scope sees A's rows {seen_by_b}"


@pytest.fixture
def connect_env(owner_engine, monkeypatch) -> tuple[uuid.UUID, TikTokReplay]:
    """The environment a connect needs: app credentials, a seller (B's owner), a fake TikTok."""
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://api.example.test/v1/auth/tiktok/callback")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with owner_engine.begin() as conn:
        user_b = _seed_user(conn, "p61e shop B owner")
    replay = TikTokReplay(known_tokens={B_TOKEN: B_CIPHER, SANDBOX_TOKEN: SANDBOX_CIPHER})
    return user_b, replay


@pytest.fixture
def journey(owner_engine, connect_env) -> Journey:
    user_b, replay = connect_env
    tenant_a = seed_tenant(owner_engine, label="p61e-shop-a")
    _make_shop_a_a_production_shop(owner_engine, tenant_a)
    return Journey(
        owner_engine=owner_engine,
        replay=replay,
        tables=_tenant_tables(owner_engine),
        shop_a=tenant_a.shop_id,
        sandbox_shop=_seed_sandbox_shop(owner_engine),
        user_b=user_b,
    )


# -- step 1: OAuth ---------------------------------------------------------------------------


async def _step_1_oauth(journey: Journey) -> None:
    owner = journey.owner_engine
    service = oauth.build_tiktok_oauth_service()
    started = oauth.begin_tiktok_oauth(journey.user_b, oauth_service=service)
    state = parse_qs(urlparse(started.authorize_url).query)["state"][0]
    assert service.verify_state(state) == journey.user_b  # signed for B's owner, nobody else

    dispatcher = _RecordingDispatcher()
    set_bootstrap_dispatcher(dispatcher)
    try:
        # P61-I: the callback runs as `juli_app` like every other step (it opens the owner's
        # user scope for the shop and the shop's scope for the credential).
        async with committing_juli_app_session() as session:
            result = await oauth.complete_tiktok_oauth_callback(
                session, code=AUTH_CODE, state=state, oauth_service=service
            )
    finally:
        set_bootstrap_dispatcher(None)
    assert result.status == "ok" and result.open_id_present

    shop_rows = _owner_rows(
        owner,
        "SELECT id, user_id, shop_name FROM public.shops WHERE tiktok_shop_id = :open_id",
        open_id=B_OPEN_ID,
    )
    assert len(shop_rows) == 1
    journey.shop_b = shop_rows[0][0]
    assert shop_rows[0][1] == journey.user_b and shop_rows[0][2] == B_SHOP_NAME

    credentials = _owner_rows(
        owner,
        "SELECT capability, merchant_authorization_id, shop_cipher FROM public.tiktok_credentials "
        "WHERE shop_id = :shop",
        shop=journey.shop_b,
    )
    # The merchant id is the OAuth open_id the connect flow returned; the cipher is the one the
    # vendor-verified binding resolved from B's own token. Nothing is configured.
    assert credentials == [("seller_connect", B_OPEN_ID, B_CIPHER)]
    async with committing_juli_app_session() as session:
        async with with_shop_scope(session, journey.shop_b):
            credential = await resolve_read_credential_for_shop(session, journey.shop_b)
    assert credential.access_token == B_TOKEN  # encrypted at rest, B's token on the way out

    # The callback queued B's bootstrap once, after its commit, and nothing else.
    assert [call["shop_id"] for call in dispatcher.calls] == [str(journey.shop_b)]
    journey.bootstrap_call = dispatcher.calls[0]
    await _assert_isolated(journey, "OAuth")


def _owner_rows(owner_engine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    bound = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in params.items()}
    with owner_engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql), bound).all()]


# -- step 2: bootstrap, quick scan, first cards ------------------------------------------------


async def _step_2_ingest(journey: Journey) -> None:
    owner = journey.owner_engine
    shop_b = journey.shop_b
    assert shop_b is not None
    queued: dict[str, list[Any]] = {"quick_scan": [], "history": [], "diagnosis": []}

    async def collaborators(session):
        async def dlq(channel, shop_key, payload):
            raise AssertionError(f"ETL routed a row to the DLQ: {channel}")

        return {
            "config": FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            "rate_limiter": FakeRateLimiter(),
            "handoff_fn": make_etl_handoff(EtlConsumer(session=session, dlq_handoff=dlq)),
        }

    def recorder(queue: str, task_id: str):
        def enqueue(shop_id: str, **_kwargs: Any) -> str:
            queued[queue].append(shop_id)
            return task_id

        return enqueue

    enqueuers = Enqueuers(
        history=recorder("history", "history-task"),
        diagnosis=recorder("diagnosis", "diagnosis-task"),
        quick_scan=recorder("quick_scan", "quick-scan-task"),
    )
    # The quick scan runs in another worker, in parallel with the fast phase, and finishes first
    # (2-3 minutes against the fast phase's full scoring): it writes B's first card.
    scan = await quick_scan.run_quick_scan(
        session_factory=committing_juli_app_session,
        shop_id=shop_b,
        app_key=APP_KEY,
        app_secret=APP_SECRET,
    )
    assert (scan.status, scan.cards, scan.surfaced) == ("done", 1, 1), scan
    await _assert_isolated(journey, "quick scan")

    bootstrap_call = journey.bootstrap_call
    result = await run_bootstrap_task(
        str(shop_b),
        session_factory=committing_juli_app_session,
        lock=InMemoryShopIngestLock(),
        collaborators=collaborators,
        enqueuers=enqueuers,
        connect_committed_at=bootstrap_call["connect_committed_at"],
        enqueued_at=bootstrap_call["enqueued_at"],
        run_kwargs={"sleep": _no_sleep, "now": INGEST_NOW},
    )
    assert not result.skipped and result.analytics is not None
    assert result.analytics.outcome.persisted > 0
    # The task queued the quick scan (parallel worker), the history phase and the diagnosis.
    assert queued["quick_scan"] == [str(shop_b)]
    assert queued["history"] == [str(shop_b)] and queued["diagnosis"] == [str(shop_b)]

    counts = _counts(owner, journey.tables, shop_b)
    assert counts["silver.orders"] >= 1 and counts["public.products"] >= 2, (
        {k: v for k, v in counts.items() if v},
        [(c.method, c.path) for c in journey.replay.calls],
    )
    assert counts["public.analytics_performance_intervals"] > 0
    state = _owner_rows(
        owner,
        "SELECT status, fast_done_at IS NOT NULL, connect_committed_at IS NOT NULL "
        "FROM public.shop_ingestion_state WHERE shop_id = :shop",
        shop=shop_b,
    )
    assert state == [("fast_done", True, True)]
    await _assert_isolated(journey, "bootstrap")


# -- step 3: approve, agent run (streamed), sandbox write ------------------------------------


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


RUN_LEG_SCRIPT = [
    _turn(
        TextBlock(text=FIRST_NARRATION),
        ToolCallBlock(call_id="c1", tool_name="get_shop_identity", arguments={}),
    ),
    _turn(ToolCallBlock(call_id="c2", tool_name="get_product_information", arguments={})),
    _turn(
        ToolCallBlock(
            call_id="c3", tool_name="update_product_listing", arguments={"title": NEW_TITLE}
        )
    ),
]
# The playbook also lists a price write, but once the approved listing write went through the
# model's closing FinalResponse ends the run with the work it did. P70 (run ceec586e, #2213):
# ADR-088's forced retry fires only while NO required step has been performed -- forcing a
# tool call after a confirmed write is what coerced a second CONFIRM proposal in that run. This
# leg used to script two FinalResponses (the first only armed the retry); one is now the truth.
RESUME_LEG_SCRIPT = [
    _turn(FinalResponse(content=FINAL_TEXT)),
]


@contextlib.contextmanager
def _worker_as_juli_app(monkeypatch, factory, sync_maker, script):
    """Bind the task shells to `juli_app` sessions and a streaming fake model.

    Everything else is the production path, including the READ and WRITE resource composition
    (`build_read_resources` per shop, `build_write_resources` -> the sandbox credential).
    """
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

    @contextlib.contextmanager
    def _ledger_session():
        session = sync_maker()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _ledger_session)
    llm = FakeLLMService(script=list(script), stream_chunk_chars=STREAM_CHUNK_CHARS)
    monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: llm)
    yield llm


async def _step_3_approve_and_run(journey: Journey, monkeypatch) -> None:
    owner = journey.owner_engine
    shop_b = journey.shop_b
    assert shop_b is not None
    # B's weak listing has two live cards: the cover image (a guided lever flow that waits for
    # the seller's photo) and the title (the agent edits the listing). The agent journey approves
    # the title card.
    cards = _owner_rows(
        owner,
        "SELECT c.id FROM public.action_cards c JOIN public.products p "
        "  ON c.subject_id = p.id::text || :lever "
        "WHERE c.shop_id = :shop AND c.workflow_key = 'optimize_product_2' "
        "AND c.status = 'active' AND p.tiktok_product_id = :product",
        shop=shop_b,
        product=WEAK_PRODUCT_ID,
        lever=":title",
    )
    assert len(cards) == 1
    card_id = cards[0][0]
    journey.card_id = card_id

    async with committing_juli_app_session(shop_b) as session:
        approval = await approve_action_card(
            session, shop_id=shop_b, action_card_id=card_id, approved_by_user_id=journey.user_b
        )
        await session.commit()
    run_id = approval.run_id
    journey.run_id = run_id
    accepted = _owner_rows(
        owner,
        "SELECT payload FROM public.card_events WHERE shop_id = :shop AND card_id = :card "
        "AND event_type = 'accepted'",
        shop=shop_b,
        card=card_id,
    )
    assert [row[0]["approved_by_user_id"] for row in accepted] == [str(journey.user_b)]
    await _assert_isolated(journey, "approval")

    async with juli_app_async_sessionmaker() as factory:
        with juli_app_sync_sessionmaker() as sync_maker:
            with _worker_as_juli_app(monkeypatch, factory, sync_maker, RUN_LEG_SCRIPT):
                await agent_workflow._run_agent_workflow_async(str(run_id))
            paused = _owner_rows(
                owner,
                "SELECT status, write_mode FROM public.workflow_runs WHERE id = :run",
                run=run_id,
            )
            # Leg 1 paused on the CONFIRM write; the run already knows where writes land.
            assert paused == [("waiting_approval", "simulated")]
            with _worker_as_juli_app(monkeypatch, factory, sync_maker, RESUME_LEG_SCRIPT):
                await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)

    final = _owner_rows(
        owner,
        "SELECT status, stop_reason, write_mode FROM public.workflow_runs WHERE id = :run",
        run=run_id,
    )
    assert final == [("completed", "final_response", "simulated")]

    # -- the model streamed: deltas first, then the authoritative text of the same turn --------
    events = _owner_rows(
        owner,
        "SELECT event_type, payload FROM public.workflow_run_events "
        "WHERE workflow_run_id = :run ORDER BY sequence_number",
        run=run_id,
    )
    kinds = [kind for kind, _payload in events]
    assert kinds[0] == "workflow.started" and kinds[-1] == "workflow.completed"
    texts_checked = 0
    pending_deltas: list[str] = []
    for kind, payload in events:
        if kind == "assistant.text.delta":
            pending_deltas.append(payload["text"])
        elif kind == "assistant.text":
            if pending_deltas:
                # What streamed is a prefix of the committed text, in order.
                assert payload["text"].startswith("".join(pending_deltas))
                texts_checked += 1
            pending_deltas = []
    assert texts_checked == 2, kinds  # narration + the final turn (P70: no forced retry turn)
    assert not pending_deltas
    assert [payload["text"] for kind, payload in events if kind == "assistant.text"][
        -1
    ] == FINAL_TEXT

    # -- reads used B's own credential: get_shop_identity answered with B's identity ------------
    window = _owner_rows(
        owner, "SELECT state FROM public.workflow_runs WHERE id = :run", run=run_id
    )[0][0]["conversation_window"]
    identity = next(
        entry["content"]
        for entry in window
        if entry.get("role") == "tool" and entry.get("tool_name") == "get_shop_identity"
    )
    assert identity["status"] == "verified" and identity["shop_matches"] is True
    assert identity["shop_name"]["text"] == B_SHOP_NAME
    assert "Shop A" not in json.dumps(identity, ensure_ascii=False)

    # -- the write took the sandbox leg and says so --------------------------------------------
    edits = journey.replay.sandbox_edits
    assert len(edits) == 1 and edits[0]["product_id"] == WEAK_PRODUCT_ID
    assert edits[0]["body"]["title"] == NEW_TITLE
    executions = _owner_rows(
        owner,
        "SELECT tool_name, status FROM public.tool_executions WHERE workflow_run_id = :run",
        run=run_id,
    )
    assert executions == [("update_product_listing", "succeeded")]
    written = _owner_rows(
        owner,
        "SELECT field, before_value, after_value FROM public.run_write_values "
        "WHERE workflow_run_id = :run",
        run=run_id,
    )
    assert written == [("title", WEAK_PRODUCT_TITLE, NEW_TITLE)]
    async with committing_juli_app_session(shop_b) as session:
        listed = [item for item in await list_runs(session, shop_b, limit=20) if item.id == run_id]
    assert [item.simulated for item in listed] == [True]  # the run surface says "chạy thử"

    # -- card_events: accepted, then executed (not not_executed) -------------------------------
    outcome = _owner_rows(
        owner,
        "SELECT event_type FROM public.card_events WHERE shop_id = :shop AND card_id = :card "
        "AND event_type IN ('proposed', 'accepted', 'executed', 'not_executed') "
        "ORDER BY occurred_at, event_type",
        shop=shop_b,
        card=card_id,
    )
    assert sorted(kind for (kind,) in outcome) == ["accepted", "executed", "proposed"]
    await _assert_isolated(journey, "agent run")


# -- step 4: a product re-read shows the seller's own edit ------------------------------------


async def _reconcile(journey: Journey) -> Any:
    """The daily product reconcile (`product_history.job`) with B's own read credential."""
    shop_b = journey.shop_b
    assert shop_b is not None
    plan = await product_history_job.plan_reads(
        committing_juli_app_session, shop_b, app_key=APP_KEY, app_secret=APP_SECRET
    )
    resources = product_history_job.build_resources(plan, app_key=APP_KEY)
    return await product_history_job.reconcile_products(
        committing_juli_app_session, shop_b, resources, backoff_sleep=lambda _s: None
    )


async def _step_4_seller_edit(journey: Journey) -> None:
    owner = journey.owner_engine
    shop_b = journey.shop_b
    assert shop_b is not None
    card_id = journey.card_id

    first = await _reconcile(journey)
    assert (
        first.baseline and first.snapshots == 1 + 1 + len(PEER_PRODUCT_IDS) and first.changes == 0
    )
    assert _counts(owner, journey.tables, shop_b)["public.external_changes"] == 0

    # The seller edits the title in Seller Center, after Juli's write: TikTok now shows a title
    # that is neither Juli's proposal nor the one before it. Juli's write is stamped with the
    # database clock, so the edit is stamped "now" as well (the attribution windows are relative
    # to it; a fixed past date would put the edit BEFORE the write).
    journey.replay.listings[WEAK_PRODUCT_ID] = ListingWorld(
        title=SELLER_EDIT_TITLE, update_time=int(datetime.now(UTC).timestamp())
    )
    second = await _reconcile(journey)
    assert second.read == 1 and second.snapshots == 1 and second.changes == 1

    changes = _owner_rows(
        owner,
        "SELECT kind, attribution, field_attribution, juli_write FROM public.external_changes "
        "WHERE shop_id = :shop AND tiktok_product_id = :product",
        shop=shop_b,
        product=WEAK_PRODUCT_ID,
    )
    assert len(changes) == 1
    kind, attribution, per_field, juli_write = changes[0]
    assert attribution == "seller_change" and per_field == {"title": "seller_change"}
    assert juli_write is False

    seller_events = _owner_rows(
        owner,
        "SELECT card_id, payload FROM public.card_events "
        "WHERE shop_id = :shop AND event_type = 'seller_change'",
        shop=shop_b,
    )
    assert len(seller_events) == 1
    linked_card, payload = seller_events[0]
    # The card whose run last wrote the title is the one the seller overrode.
    assert linked_card == card_id and payload["card_link"] == "last_write"
    assert payload["attribution"] == "seller_change" and payload["fields"] == ["title"]
    await _assert_isolated(journey, "product re-read")


# -- step 5: the impact reader skips the simulated execution ----------------------------------


#: The impact reader is run as if this many days after the writes (past every reading window).
IMPACT_HORIZON_DAYS = 60


def _impact_reference_date() -> date:
    # Writes are stamped with the database clock, so "after the windows" is measured from now.
    return datetime.now(UTC).date() + timedelta(days=IMPACT_HORIZON_DAYS)


async def _impact_reader(journey: Journey) -> Any:
    async with committing_juli_app_session() as session:
        return await run_daily_impact_reader(session, _impact_reference_date())


async def _step_5_impact(journey: Journey) -> None:
    owner = journey.owner_engine
    shop_b = journey.shop_b
    assert shop_b is not None
    result = await _impact_reader(journey)
    # B's execution was enumerated, found to be on the sandbox merchant, and skipped.
    assert result.executions_skipped_simulated == 1
    assert _impact_readings(owner, shop_b) == 0
    kinds = {
        kind
        for (kind,) in _owner_rows(
            owner, "SELECT event_type FROM public.card_events WHERE shop_id = :shop", shop=shop_b
        )
    }
    assert not kinds & {"impact_preliminary", "impact_final"}, kinds
    await _assert_isolated(journey, "impact reader")


# -- step 6: nothing ever reached for another shop's credential -------------------------------


def _step_6_credentials(journey: Journey) -> None:
    calls = journey.replay.calls
    tokens = {call.token for call in calls}
    # Only B's token, the sandbox token, and the unauthenticated OAuth host ever appear.
    assert tokens <= {None, B_TOKEN, SANDBOX_TOKEN}, tokens
    assert not tokens & set(A_TOKENS)
    for call in calls:
        if call.token == B_TOKEN and call.cipher is not None:
            assert call.cipher == B_CIPHER, call
        if call.token == SANDBOX_TOKEN and call.cipher is not None:
            assert call.cipher == SANDBOX_CIPHER, call
    # B's credential only ever read; the one write was signed by the sandbox credential.
    writes = [call for call in calls if call.method == "PUT"]
    assert [call.token for call in writes] == [SANDBOX_TOKEN]
    assert any(call.token == B_TOKEN and call.path == AUTHORIZED_SHOPS_PATH for call in calls)
    # The sandbox credential was used for that write path alone (never a bulk read of B's shop).
    sandbox_paths = {call.path for call in calls if call.token == SANDBOX_TOKEN}
    # P76-5: the confirmed draft is scored by TikTok (read-only) right before the edit.
    assert sandbox_paths == {
        f"/product/202309/products/{WEAK_PRODUCT_ID}",
        "/product/202411/products/diagnose_optimize",
    }


async def _warm_up_shop_a(journey: Journey) -> None:
    """Shop A is a mature shop: its seeded execution has already been measured.

    The impact reader walks every shop's executions, so without this its first run would add
    A's readings in the middle of B's journey and "A is unchanged" could not be asserted.
    """
    await _impact_reader(journey)
    journey.a_before = _counts(journey.owner_engine, journey.tables, journey.shop_a)
    assert _impact_readings(journey.owner_engine, journey.shop_a) > 0
    journey.sandbox_before = _counts(journey.owner_engine, journey.tables, journey.sandbox_shop)


#: The journey is ~20 s on a laptop (a migrated database, seven steps, two worker legs); the
#: repo-wide 30 s per-test timeout is too tight for it. 120 s is the brief's ceiling.
JOURNEY_TIMEOUT_SECONDS = 120


@pytest.mark.timeout(JOURNEY_TIMEOUT_SECONDS)
@pytest.mark.asyncio
async def test_new_shop_runs_the_whole_journey(journey: Journey, monkeypatch) -> None:
    await _warm_up_shop_a(journey)
    with patch("requests.Session.request", side_effect=journey.replay.request):
        await _step_1_oauth(journey)
        await _step_2_ingest(journey)
        await _step_3_approve_and_run(journey, monkeypatch)
        await _step_4_seller_edit(journey)
        await _step_5_impact(journey)
    _step_6_credentials(journey)
