#!/usr/bin/env python
"""READ-ONLY: why does each product of one shop have (or not have) an Optimize Product card?

Usage, on the VPS, from the release directory::

    cd /root/releases/current
    set -a && . /etc/juli/api.env && set +a
    .venv/bin/python diagnose_cards.py <shop_uuid>

What it does (no writes anywhere):

* opens ONE transaction, marks it ``READ ONLY`` before anything else, runs inside
  ``with_shop_scope`` (the same tenant scope the daily task uses) and ROLLS BACK
  at the end. There is no ``commit`` in this file. No TikTok call, no LLM call.
* re-runs the app's own planner (``plan_optimize_product_cards`` -> D29
  ``plan_shop_cards``) on the stored analytics, exactly as the daily scoring
  pass does;
* replays, read-only, the emission ladder of ``emit_optimize_product_cards``
  (decision cooldown, D29.4 other-metric, expired-card cooldown, card already
  open / in flight) for every proposal;
* replays, read-only, the surfacing budget of ``apply_emission_budget``
  (daily slots 3 Juli / 1 Seller Center / 1 content, weekly cap, open cap,
  Ops overrides, the seller's "Số thẻ mở cùng lúc").

Prints product short id + truncated title only. Never prints order / buyer data,
seller notes, or the database URL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

TITLE_WIDTH = 34


def _short_pid(tiktok_id: str | None) -> str:
    text = str(tiktok_id or "?")
    return "…" + text[-6:] if len(text) > 7 else text


def _title(text: str | None) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= TITLE_WIDTH else value[: TITLE_WIDTH - 1] + "…"


def _money(value: Decimal | float | None) -> str:
    if value is None:
        return "-"
    return f"{int(Decimal(str(value)).quantize(Decimal('1'))):,}".replace(",", ".")


def _payload(card) -> dict:
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


async def diagnose(session, shop_id: uuid.UUID, now: datetime) -> None:  # noqa: C901, PLR0912, PLR0915
    from sqlalchemy import select

    from juli_backend.core.config import decision_emission_config
    from juli_backend.models.models import ActionCard, Product
    from juli_backend.services import decision_reasons
    from juli_backend.services.action_cards import emission_budget as eb
    from juli_backend.services.action_cards import persist
    from juli_backend.services.action_cards.basis import (
        basis_unchanged,
        product_basis_fields,
        stored_basis,
    )
    from juli_backend.services.action_cards.optimize_product_cards import (
        OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        WITHDRAWN_STATUS,
        _basis,
        chain_for,
        is_adr106_card,
        is_quick_card,
        live_metrics_by_product,
        plan_optimize_product_cards,
        proposal_metric,
    )
    from juli_backend.services.action_cards.subjects import subject_product_ref
    from juli_backend.services.ops import overrides as ops_overrides
    from juli_backend.services.optimize_product.decision_cards import (
        DEFAULT_TOP_K,
        LEVER_CODES,
        SELLER_CENTER_ANGLES,
    )
    from juli_backend.services.optimize_product.volatility import assess_product
    from juli_backend.services.shop_rules import configured_max_open_cards
    from juli_backend.services.shop_rules.diag_tunables import diag_tunables

    print(f"shop {shop_id}  ·  run at {now.isoformat(timespec='seconds')}  ·  READ ONLY\n")

    # ------------------------------------------------------------ catalog + cards
    products = list(
        (await session.execute(select(Product).where(Product.shop_id == shop_id))).scalars()
    )
    by_uuid = {str(p.id): p for p in products}

    op_cards = list(
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id,
                    ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                )
            )
        ).scalars()
    )
    # products.id -> its newest card per lever (any status)
    newest: dict[str, dict[str, ActionCard]] = defaultdict(dict)
    for card in sorted(op_cards, key=lambda c: c.revision):
        ref = subject_product_ref(card.subject_type, card.subject_id)
        if ref is None:
            continue
        lever = eb.card_lever(card) or "?"
        newest[ref][lever] = card

    def card_state(card: ActionCard) -> str:
        if card.status == "active":
            if card.surfaced_at is not None:
                return "OPEN" + (" (quick)" if is_quick_card(card) else "")
            return f"draft[{card.suppressed_reason or 'not yet budgeted'}]"
        if card.status in ("approved", "executing") or card.executed_at is not None:
            return f"in-flight:{card.status}"
        if card.status == WITHDRAWN_STATUS:
            return "withdrawn" + (f"[{card.suppressed_reason}]" if card.suppressed_reason else "")
        return card.status

    def cards_text(product_uuid: str | None) -> str:
        if product_uuid is None or product_uuid not in newest:
            return "-"
        return ", ".join(f"{lv}:{card_state(c)}" for lv, c in sorted(newest[product_uuid].items()))

    # ------------------------------------------------------------ the planner
    op_plan = await plan_optimize_product_cards(session, shop_id, now=now)
    if op_plan is None:
        print(
            "plan_optimize_product_cards returned None: no daily product-grain analytics "
            "stored for this shop (or none in the lookback window). The daily task then keeps "
            "the rule pipeline's single shop-level card; no per-product cards at all.\n"
        )
    tunables = await diag_tunables(session, shop_id)
    plan = op_plan.plan if op_plan is not None else None

    if plan is not None:
        print(
            f"as_of (newest analytics day) {op_plan.as_of}  ·  products with daily rows "
            f"{plan.products_scored}  ·  excluded {len(plan.excluded)}  ·  skipped "
            f"{len(plan.skips)}  ·  proposals kept {len(plan.proposals)}  ·  "
            f"overflow beyond top_k={DEFAULT_TOP_K}/type {plan.overflow}"
        )
        m = plan.medians
        print(
            f"shop medians: ctr={m.ctr} ctor={m.ctor} aov={m.aov} peers={dict(m.peers)}\n"
            "note: the live planner is called WITHOUT discount_cap_set (False) and without "
            "promotion facts, so product_discount / flash_sale / shipping_discount can never be "
            "a 'rule' lever here; Seller-Center cards come only from BMSM (target=aov) or a "
            "'needs discount cap' pending card.\n"
        )

    # ------------------------------------------------------------ emission ladder replay
    cfg = decision_emission_config()
    overrides = await ops_overrides.shop_overrides(session, shop_id)
    eff = await eb._with_shop_card_cap(session, shop_id, cfg, overrides)
    seller_cap = await configured_max_open_cards(session, shop_id)

    verdict_by_proposal: dict[tuple[str, str], str] = {}
    if plan is not None:
        cooldowns = await decision_reasons.active_cooldowns(session, shop_id, now=now)
        live_metrics = await live_metrics_by_product(session, shop_id, now=now, full_run=True)
        for proposal in plan.proposals:
            key = (proposal.product_id, LEVER_CODES[proposal.lever])
            product = op_plan.products.get(proposal.product_id)
            if product is None:
                verdict_by_proposal[key] = "SKIP: product row missing"
                continue
            subject, latest = await chain_for(
                session, shop_id, product, LEVER_CODES[proposal.lever]
            )
            reason = cooldowns.get((str(product.id), LEVER_CODES[proposal.lever]))
            if reason is not None:
                verdict_by_proposal[key] = (
                    f"SKIP decision_cooldown (seller {reason.action}/{reason.reason_code}, 7d)"
                )
                continue
            metric = proposal_metric(proposal)
            other = {
                m
                for card_id, m in live_metrics.get(str(product.id), {}).items()
                if latest is None or card_id != latest.id
            }
            if other - {metric}:
                verdict_by_proposal[key] = (
                    f"SKIP other_metric_active (product holds {sorted(other - {metric})})"
                )
                continue
            basis = {
                **_basis(proposal),
                **await product_basis_fields(
                    session, shop_id, workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY, subject=subject
                ),
            }
            if latest is None:
                verdict_by_proposal[key] = "new draft -> budget"
            elif (
                latest.status == "active"
                and latest.surfaced_at is not None
                and is_quick_card(latest)
            ):
                same = decision_reasons.card_basis(latest).lever_code == LEVER_CODES[proposal.lever]
                verdict_by_proposal[key] = (
                    "card OPEN (quick card upgraded in place)"
                    if same
                    else "quick card withdrawn -> new draft -> budget"
                )
            elif (
                latest.status == WITHDRAWN_STATUS
                or persist._is_unsurfaced_draft(latest)
                or (latest.status == "active" and not is_adr106_card(latest))
            ):
                stored = latest.suppressed_reason if latest.status == "active" else None
                verdict_by_proposal[key] = "draft rewritten -> budget" + (
                    f" (last budget: {stored})" if stored else ""
                )
            elif latest.status == eb.EXPIRED_STATUS:
                same = decision_reasons.card_basis(latest).lever_code == LEVER_CODES[proposal.lever]
                if same and not eb.expired_card_returns(
                    latest,
                    now=now,
                    cooldown_days=cfg.cooldown_days,
                    validity_days=cfg.validity_days,
                ):
                    when = eb.expired_at(latest, validity_days=cfg.validity_days)
                    back = (when + timedelta(days=cfg.cooldown_days)).date() if when else "?"
                    verdict_by_proposal[key] = f"SKIP expired_cooldown (returns {back})"
                else:
                    verdict_by_proposal[key] = "new revision after expiry -> budget"
            elif (
                latest.status == "active"
                and latest.surfaced_at is not None
                and basis_unchanged(stored_basis(latest), basis)
            ):
                verdict_by_proposal[key] = "card OPEN (re-scored in place)"
            elif latest.status != decision_reasons.DISMISSED_CARD_STATUS and (
                basis_unchanged(stored_basis(latest), basis)
                or persist._card_still_stands(latest, now=now, cooldown_days=cfg.cooldown_days)
            ):
                label = (
                    "card OPEN"
                    if latest.status == "active" and latest.surfaced_at is not None
                    else f"in-flight/standing ({latest.status})"
                )
                verdict_by_proposal[key] = f"{label}: no new revision"
            else:
                verdict_by_proposal[key] = "new revision -> budget"

    # ------------------------------------------------------------ per-product table
    rows: list[list[str]] = []
    proposed_ids = set()
    if plan is not None:
        for p in plan.proposals:
            proposed_ids.add(p.product_id)
            product = op_plan.products.get(p.product_id)
            code = LEVER_CODES[p.lever]
            slot = "seller_center" if p.lever in SELLER_CENTER_ANGLES else "juli"
            kpi = p.kpi
            metric_txt = p.target_metric or "-"
            if kpi is not None:
                metric_txt += f" {kpi.current:.4g}->{kpi.target:.4g}"
            rows.append(
                [
                    str(p.rank),
                    slot,
                    _short_pid(p.product_id),
                    _title(product.title or product.name if product else p.title),
                    f"{p.stage.value}/{code}",
                    p.status,
                    metric_txt,
                    _money(p.recoverable_gmv_per_day),
                    _money(p.ranking_gmv_per_day),
                    p.assessment.stability if p.assessment else "-",
                    verdict_by_proposal.get((p.product_id, code), "?"),
                    cards_text(str(product.id) if product else None),
                ]
            )

        skip_by_id = {s.product_id: s.reason for s in plan.skips}
        for pid in sorted(op_plan.days):
            if pid in proposed_ids:
                continue
            product = op_plan.products.get(pid)
            a = assess_product(
                pid, op_plan.days.get(pid, []), as_of=op_plan.as_of, tunables=tunables
            )
            if pid in plan.excluded:
                why = f"excluded: {plan.excluded[pid]}"
            elif pid in skip_by_id:
                why = skip_by_id[pid]
                if why == "d29:no_lever_for_target_metric":
                    why += f" (target={a.target_metric})"
            else:
                why = f"overflow: ranked below top_k={DEFAULT_TOP_K} for its executor type"
            gmv = (
                f"gmv/d {_money(a.gmv_current)} vs {_money(a.gmv_earlier)}"
                if getattr(a, "gmv_current", None) is not None
                else ""
            )
            rows.append(
                [
                    "-",
                    "-",
                    _short_pid(pid),
                    _title(
                        (product.title or product.name) if product else "(not in products table)"
                    ),
                    "-",
                    "-",
                    a.target_metric or "-",
                    "-",
                    "-",
                    a.stability,
                    f"NO CARD: {why}" + (f" [{gmv}]" if gmv else ""),
                    cards_text(str(product.id) if product else None),
                ]
            )

    no_rows = [
        p for p in products if op_plan is None or str(p.tiktok_product_id) not in op_plan.days
    ]
    lookback = None
    if op_plan is not None:
        lookback = f"{min(min(d.day for d in s) for s in op_plan.days.values())}..{op_plan.as_of}"
    for p in sorted(no_rows, key=lambda x: (str(x.status or ""), str(x.tiktok_product_id))):
        rows.append(
            [
                "-",
                "-",
                _short_pid(p.tiktok_product_id),
                _title(p.title or p.name),
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                f"NO CARD: no daily product analytics rows in lookback {lookback or ''} "
                f"(status {p.status})",
                cards_text(str(p.id)),
            ]
        )

    print("PER PRODUCT (rank = card priority within plan; slot = executor's daily slot)")
    _print_table(
        [
            "rank",
            "slot",
            "product",
            "title",
            "stage/lever",
            "group",
            "metric now->target",
            "recov GMV/d",
            "rank value",
            "stability",
            "verdict / skip reason",
            "existing cards (lever:state)",
        ],
        rows,
    )

    if plan is not None:
        print("\nSKIP REASONS (products without a proposal):")
        counts = Counter(r[10].split(" (")[0].split(" [")[0] for r in rows if r[0] == "-")
        for reason, n in counts.most_common():
            print(f"  {n:4d}  {reason}")
        levers = Counter(
            ("seller_center" if p.lever in SELLER_CENTER_ANGLES else "juli", LEVER_CODES[p.lever])
            for p in plan.proposals
        )
        print("\nPROPOSALS BY SLOT/LEVER:", dict(levers))

    # ------------------------------------------------------------ budget replay
    stmt = (
        select(ActionCard)
        .where(ActionCard.shop_id == shop_id, ActionCard.status == "active")
        .order_by(ActionCard.priority.asc(), ActionCard.workflow_key.asc())
    )
    candidates = list((await session.execute(stmt)).scalars())
    week_rows = await eb._surfacings_this_week(session, shop_id, eb.shop_week_start(now))
    day_start = eb._shop_day_start_utc(now)
    surfaced_today = sum(1 for r in week_rows if _aware(r.first_surfaced_at) >= day_start)
    used_today = await eb._surfaced_today_by_slot(session, week_rows, day_start)
    open_cards, drafts = [], []
    for card in candidates:
        if card.surfaced_at is None:
            drafts.append(card)
        elif now - _aware(card.surfaced_at) < timedelta(days=eff.validity_days) or (
            card.workflow_key in eb.CAMPAIGN_PLAN_WORKFLOW_KEYS
        ):
            open_cards.append(card)
    open_counted = sum(
        1 for c in open_cards if c.workflow_key not in eb.CAMPAIGN_PLAN_WORKFLOW_KEYS
    )
    limits = (
        (eff.daily_new_cap - surfaced_today, eb.SUPPRESSED_REASON_DAILY_CAP),
        (eff.weekly_new_cap - len(week_rows), eb.SUPPRESSED_REASON_WEEKLY_CAP),
        (eff.max_open - open_counted, eb.SUPPRESSED_REASON_ACTIVE_CAP),
    )
    room, room_reason = min(limits, key=lambda item: item[0])
    room = max(room, 0)
    slot_room = {s: max(n - used_today.get(s, 0), 0) for s, n in eff.daily_slots}

    print("\nSURFACING BUDGET (apply_emission_budget, replayed read-only)")
    print(
        f"  limits: daily_new_cap={eff.daily_new_cap} weekly_new_cap={eff.weekly_new_cap} "
        f"max_open={eff.max_open} (seller rule max_open_cards={seller_cap}) "
        f"validity={eff.validity_days}d cooldown={eff.cooldown_days}d "
        f"daily_slots={dict(eff.daily_slots)} (no backfill between slots)"
    )
    print(
        f"  surfaced today={surfaced_today} by slot={used_today} · this week={len(week_rows)} · "
        f"open now={open_counted} · room now={room} (binding: {room_reason}) · "
        f"slot room today={slot_room}"
    )
    open_by = Counter((c.workflow_key, eb.daily_slot(c)) for c in open_cards)
    print(f"  open cards by (workflow, slot): {dict(open_by)}")
    for c in sorted(open_cards, key=lambda c: c.surfaced_at):
        ref = subject_product_ref(c.subject_type, c.subject_id)
        prod = by_uuid.get(ref) if ref else None
        print(
            f"    OPEN {c.workflow_key:<20} slot={eb.daily_slot(c):<13} lever={eb.card_lever(c) or '-':<18} "
            f"product={_short_pid(prod.tiktok_product_id) if prod else '-'} "
            f"{_title((prod.title or prod.name) if prod else '')} "
            f"surfaced={_aware(c.surfaced_at).date()} prio={c.priority}"
        )

    eligible = []
    pre: dict[uuid.UUID, str] = {}
    for card in drafts:
        if not eb.ops_card_enabled(card, overrides):
            pre[card.id] = eb.SUPPRESSED_REASON_OPS_DISABLED
        elif eb._in_cooldown(card, now=now, cooldown_days=eff.cooldown_days):
            pre[card.id] = eb.SUPPRESSED_REASON_COOLDOWN
        elif card.workflow_key in eb.CAMPAIGN_PLAN_WORKFLOW_KEYS:
            pre[card.id] = "campaign (outside limits)"
        else:
            eligible.append(card)
    chosen = {
        c.id
        for c in eb.daily_slot_pick(eligible, room, slot_room, tuple(s for s, _ in eff.daily_slots))
    }
    room_left = room - len(chosen)
    print(f"\n  DRAFTS ({len(drafts)}) — what the next budget run would do with the stored drafts:")
    draft_rows = []
    for card in drafts:
        ref = subject_product_ref(card.subject_type, card.subject_id)
        prod = by_uuid.get(ref) if ref else None
        if card.id in pre:
            outcome = pre[card.id]
        elif card.id in chosen:
            outcome = "WOULD SURFACE"
        else:
            outcome = (
                room_reason if room_left <= 0 else f"{eb.SUPPRESSED_REASON_DAILY_CAP} (slot full)"
            )
        draft_rows.append(
            [
                str(card.priority),
                card.workflow_key,
                eb.daily_slot(card),
                eb.card_lever(card) or "-",
                _short_pid(prod.tiktok_product_id) if prod else "-",
                _title((prod.title or prod.name) if prod else ""),
                card.suppressed_reason or "-",
                outcome,
            ]
        )
    if draft_rows:
        _print_table(
            ["prio", "workflow", "slot", "lever", "product", "title", "stored reason", "next run"],
            draft_rows,
        )
    else:
        print(
            "    (none) — every proposal is already open / in flight / skipped, or the "
            "producer wrote no draft"
        )


async def run(shop_id: uuid.UUID) -> None:
    from sqlalchemy import text

    from juli_backend.core.async_db import async_database_url
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.database.tenant_context import with_shop_scope

    factory = ensure_worker_session_factory(async_database_url(os.environ["DATABASE_URL"]))
    now = datetime.now(UTC)
    async with factory() as session:
        try:
            # First statement of the transaction: nothing below can write.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            async with with_shop_scope(session, shop_id):
                await diagnose(session, shop_id, now)
        finally:
            await session.rollback()
    print("\n(rolled back; nothing written)")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        shop_id = uuid.UUID(sys.argv[1])
    except ValueError:
        print("argument must be the shop UUID (shops.id)")
        return 2
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set: run `set -a && . /etc/juli/api.env && set +a` first")
        return 2
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(shop_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
