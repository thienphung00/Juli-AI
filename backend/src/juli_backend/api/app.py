import logging
from typing import Any

from fastapi import APIRouter, FastAPI

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.api.middleware import (
    CorrelationIdMiddleware,
    RequestTimingMiddleware,
    RunsListInvalidationMiddleware,
    install_error_boundary,
)
from juli_backend.api.routes.action_cards import router as action_cards_router
from juli_backend.api.routes.agent_runs import router as agent_runs_router
from juli_backend.api.routes.auth_tiktok import router as auth_tiktok_router
from juli_backend.api.routes.auth_tiktok_business_account_holder import (
    router as auth_tiktok_business_account_holder_router,
)
from juli_backend.api.routes.auth_tiktok_business_advertiser import (
    router as auth_tiktok_business_advertiser_router,
)
from juli_backend.api.routes.connector_fill_flag import demo_router as demo_connector_fill_router
from juli_backend.api.routes.connector_fill_flag import ops_router as ops_connector_fill_router
from juli_backend.api.routes.creators import router as creators_router
from juli_backend.api.routes.debug_tiktok import router as debug_tiktok_router
from juli_backend.api.routes.demo_analysis import router as demo_analysis_router
from juli_backend.api.routes.demo_analytics import router as demo_analytics_router
from juli_backend.api.routes.demo_content_analysis import (
    router as demo_content_analysis_router,
)
from juli_backend.api.routes.demo_content_runs import router as demo_content_runs_router
from juli_backend.api.routes.demo_decisions import router as demo_decisions_router
from juli_backend.api.routes.demo_execution import router as demo_execution_router
from juli_backend.api.routes.demo_planned_changes import router as demo_planned_changes_router
from juli_backend.api.routes.demo_rules import router as demo_rules_router
from juli_backend.api.routes.demo_run_changes import router as demo_run_changes_router
from juli_backend.api.routes.demo_run_flows import router as demo_run_flows_router
from juli_backend.api.routes.demo_shop_inputs import router as demo_shop_inputs_router
from juli_backend.api.routes.demo_shopee_analytics import router as demo_shopee_analytics_router
from juli_backend.api.routes.demo_shopee_builder import router as demo_shopee_builder_router
from juli_backend.api.routes.demo_shopee_market import router as demo_shopee_market_router
from juli_backend.api.routes.demo_shopee_pages import router as demo_shopee_pages_router
from juli_backend.api.routes.demo_shopee_reco_manual import router as demo_shopee_reco_manual_router
from juli_backend.api.routes.demo_shopee_reco_plan import router as demo_shopee_reco_plan_router
from juli_backend.api.routes.demo_shopee_recommendations import (
    router as demo_shopee_recommendations_router,
)
from juli_backend.api.routes.executions import router as executions_router
from juli_backend.api.routes.ingest import router as ingest_router
from juli_backend.api.routes.ingest_fill import jobs_router as ingest_fill_jobs_router
from juli_backend.api.routes.ingest_fill import router as ingest_fill_router
from juli_backend.api.routes.ingest_fill import seller_router as demo_fill_jobs_router
from juli_backend.api.routes.ingest_market import router as ingest_market_router
from juli_backend.api.routes.ingest_order_ref import router as ingest_order_ref_router
from juli_backend.api.routes.me import router as me_router
from juli_backend.api.routes.ops import router as ops_router
from juli_backend.api.routes.ops_billing import router as ops_billing_router
from juli_backend.api.routes.ops_contract_shops import router as ops_contract_shops_router
from juli_backend.api.routes.ops_planned_changes import router as ops_planned_changes_router
from juli_backend.api.routes.ops_proposals import router as ops_proposals_router
from juli_backend.api.routes.ops_shop_inputs import router as ops_shop_inputs_router
from juli_backend.api.routes.ops_shopee_analytics import router as ops_shopee_analytics_router
from juli_backend.api.routes.ops_shopee_backtest import router as ops_shopee_backtest_router
from juli_backend.api.routes.ops_shopee_builder import router as ops_shopee_builder_router
from juli_backend.api.routes.ops_shopee_dashboards import router as ops_shopee_dashboards_router
from juli_backend.api.routes.ops_shopee_keywords import router as ops_shopee_keywords_router
from juli_backend.api.routes.ops_shopee_kpi import router as ops_shopee_kpi_router
from juli_backend.api.routes.ops_shopee_market import router as ops_shopee_market_router
from juli_backend.api.routes.ops_shopee_orders import router as ops_shopee_orders_router
from juli_backend.api.routes.ops_shopee_reco_manual import router as ops_shopee_reco_manual_router
from juli_backend.api.routes.ops_shopee_reco_plan import router as ops_shopee_reco_plan_router
from juli_backend.api.routes.ops_shopee_recommendations import (
    router as ops_shopee_recommendations_router,
)
from juli_backend.api.routes.ops_trial_signups import router as ops_trial_signups_router
from juli_backend.api.routes.orders import router as orders_router
from juli_backend.api.routes.outcomes import router as outcomes_router
from juli_backend.api.routes.products import router as products_router
from juli_backend.api.routes.recommendations import router as recommendations_router
from juli_backend.api.routes.reviewer import router as reviewer_router
from juli_backend.api.routes.shop_invites import router as shop_invites_router
from juli_backend.api.routes.shops import router as shops_router
from juli_backend.api.routes.trial_signups import router as trial_signups_router
from juli_backend.api.routes.webhook_tiktok import router as webhook_tiktok_router
from juli_backend.api.routes.workflow_outcomes import router as workflow_outcomes_router
from juli_backend.core.config import is_production

logger = logging.getLogger(__name__)


def warm_route_state(app: FastAPI) -> None:
    """Build FastAPI's per-route request state now instead of inside the first request.

    Recent FastAPI builds each route's dependant graph and response fields lazily, the
    first time the router matches a request, for every route it walks past. With the P90
    router growth (~200 routes) that is a few hundred milliseconds of synchronous CPU on
    the sole uvicorn worker's event loop, paid by whichever request arrives first — long
    enough to starve a concurrent ``/health`` probe (#927 exit gate). The state is cached
    on the included-router objects, so one match against a path no route owns walks and
    caches everything, and routes added to the top-level app afterwards (``/health``) do
    not invalidate it.
    """
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/__route_warmup__",
        "root_path": "",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    try:
        for route in app.router.routes:
            route.matches(scope)
    except Exception:  # pragma: no cover - warm-up is an optimisation, never fatal
        logger.warning("route_state_warmup_failed", exc_info=True)


def create_app(*, lifespan: Any | None = None) -> FastAPI:
    """Build and return the Juli API application."""
    # Interactive docs, the ReDoc view and the raw schema hand any caller who can reach
    # the host a complete map of every route, its parameters and its models. Harmless in
    # development, a free reconnaissance pass in production (ADR-061, #903). Passing
    # None to FastAPI does not merely hide them — the routes are never registered.
    production = is_production()
    app = FastAPI(
        title="Juli API",
        version="0.1.0",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=lifespan,
    )

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(agent_runs_router)
    v1_router.include_router(auth_tiktok_router)
    v1_router.include_router(auth_tiktok_business_advertiser_router)
    v1_router.include_router(auth_tiktok_business_account_holder_router)
    v1_router.include_router(shops_router)
    v1_router.include_router(me_router)
    v1_router.include_router(orders_router)
    v1_router.include_router(products_router)
    v1_router.include_router(recommendations_router)
    v1_router.include_router(outcomes_router)
    v1_router.include_router(executions_router)
    v1_router.include_router(action_cards_router)
    v1_router.include_router(workflow_outcomes_router)
    v1_router.include_router(creators_router)
    v1_router.include_router(demo_analytics_router)
    v1_router.include_router(demo_analysis_router)
    v1_router.include_router(demo_decisions_router)
    v1_router.include_router(demo_execution_router)
    v1_router.include_router(demo_run_changes_router)
    v1_router.include_router(demo_run_flows_router)
    v1_router.include_router(demo_content_runs_router)
    v1_router.include_router(demo_content_analysis_router)
    v1_router.include_router(demo_rules_router)
    v1_router.include_router(demo_shop_inputs_router)
    # P90 step 7: the Shopee shop screens' read APIs (seller scope and Ops viewer).
    v1_router.include_router(demo_shopee_analytics_router)
    # P91 D-6: the plan routes (/plan, /plans, /change-sets) go before the {card_id} routes
    v1_router.include_router(demo_shopee_reco_plan_router)
    v1_router.include_router(demo_shopee_recommendations_router)
    v1_router.include_router(demo_shopee_reco_manual_router)
    v1_router.include_router(demo_shopee_builder_router)
    v1_router.include_router(demo_shopee_market_router)
    v1_router.include_router(demo_shopee_pages_router)
    v1_router.include_router(demo_planned_changes_router)
    v1_router.include_router(demo_connector_fill_router)
    # Fast track P16 (D25): the Juli Ops console and the seller's invite accept.
    v1_router.include_router(ops_router)
    # Fast track P20 (D28.3 / D28.4): Juli Ops tabs Chi phí and Thời hạn.
    v1_router.include_router(ops_billing_router)
    v1_router.include_router(ops_proposals_router)
    v1_router.include_router(ops_shopee_reco_plan_router)
    v1_router.include_router(ops_shopee_recommendations_router)
    v1_router.include_router(ops_shopee_reco_manual_router)
    v1_router.include_router(ops_shopee_builder_router)
    v1_router.include_router(ops_shopee_market_router)
    v1_router.include_router(ops_shopee_backtest_router)
    v1_router.include_router(ops_planned_changes_router)
    v1_router.include_router(ops_connector_fill_router)
    v1_router.include_router(ops_contract_shops_router)
    v1_router.include_router(ops_shopee_kpi_router)
    v1_router.include_router(ops_shopee_dashboards_router)
    v1_router.include_router(ops_shopee_keywords_router)
    v1_router.include_router(ops_shopee_orders_router)
    v1_router.include_router(ops_shop_inputs_router)
    v1_router.include_router(ops_shopee_analytics_router)
    v1_router.include_router(shop_invites_router)
    # Fast track P24 (D31.3 / D31.4): the ingest gateway and Juli Connector pairing.
    v1_router.include_router(ingest_fill_router)
    v1_router.include_router(ingest_fill_jobs_router)
    v1_router.include_router(demo_fill_jobs_router)
    v1_router.include_router(ingest_market_router)
    v1_router.include_router(ingest_order_ref_router)
    v1_router.include_router(ingest_router)
    # Fast track P32-A (D42): the partner reviewer's own routes (who am I, simulate).
    v1_router.include_router(reviewer_router)
    # Fast track P33-F (D43): the public free-trial sign-up and its Ops tab.
    v1_router.include_router(trial_signups_router)
    v1_router.include_router(ops_trial_signups_router)
    app.include_router(v1_router)
    # The diagnostic router is not mounted in production at all. Its own
    # ENABLE_TIKTOK_DEBUG flag is deliberately NOT consulted here: the environment check
    # takes precedence, so an operator who leaves the flag on cannot expose it (#903 AC).
    # Not-mounted beats mounted-and-404ing — an unregistered route cannot be reached by a
    # future refactor that forgets the guard.
    if not production:
        app.include_router(debug_tiktok_router)
    # Not under /v1 — TikTok Partner Center calls the literal path it was
    # registered with (see juli_backend.services.webhook.app.WEBHOOK_PATH).
    app.include_router(webhook_tiktok_router)

    # P21: request timing sits just inside correlation, so its http_request event carries
    # the correlation id and its clock covers routing, handlers and the response body.
    app.add_middleware(RequestTimingMiddleware)
    # P82: a write to a shop drops its cached runs lists (the poll's few-second cache).
    app.add_middleware(RunsListInvalidationMiddleware)
    # P32-A (D42): bind the reviewer gate into get_current_user and mask every
    # reviewer response. Inside timing / correlation, outside the routes and the
    # exception handlers, so a refused reviewer request is masked too.
    reviewer_gate.install(app)
    # Correlation must wrap everything, so it is added last (Starlette applies middleware
    # outermost-last) and therefore sees the request before any route or handler runs.
    app.add_middleware(CorrelationIdMiddleware)
    install_error_boundary(app)
    warm_route_state(app)

    return app
