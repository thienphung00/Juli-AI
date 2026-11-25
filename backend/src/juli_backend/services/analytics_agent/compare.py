"""Build-and-compare (C6): a `compare` block of exactly 4 options, each priced by OPP.

Options come from OPP's `compare` (versions of one card kind) or from the stored opportunities of
different levers. The figures are OPP's (ΔGMV, Δ lợi nhuận, chi phí), formatted here and nothing
else; the pick is the highest Δ lợi nhuận among the priced options, as OPP returned it (shop-level
strategies come back on the net level, product-level on the contribution level). A missing option
states OPP's reason. The lead names the figure the pick was made on.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.types import CardEnginePort, DataPort, LabelTable

N_OPTIONS = 4
NO_OPPORTUNITY_VI = "chưa có cơ hội"
TITLE_VI = "So sánh 4 phương án"


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _row(labels: LabelTable, n: int, o: dict[str, Any], lever: str) -> dict[str, Any]:
    lever = str(o.get("lever") or o.get("kind") or lever)
    code = o.get("card_code")
    ref = o.get("card_ref") or (f"open:{code}" if code else None)
    version = o.get("version") or (None if ref else o.get("id") or o.get("opportunity_id"))
    row: dict[str, Any] = {
        "option": str(o.get("option") or f"{n}. {labels.kind(lever)}"),
        "lever": lever,
        "card_ref": ref,
        "version": None if version is None else str(version),
        "inputs": dict(o.get("inputs") or {}),
        "gmv_delta_vi": fmt.value_id("gmv", _f(o.get("delta_gmv"))),
        "profit_delta_vi": fmt.value_id("profit", _f(o.get("delta_profit"))),
        "cost_vi": fmt.value_id("cost_ads", _f(o.get("cost"))),
        "recommended": False,
        "_profit": _f(o.get("delta_profit")),
    }
    if not ref and not version or o.get("reason") and o.get("delta_profit") is None:
        row["card_ref"], row["version"] = None, None
        row["reason"] = str(o.get("reason") or NO_OPPORTUNITY_VI)
    return row


def _by_lever(opps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The best published opportunity of each lever (highest Δ lợi nhuận as stored)."""
    best: dict[str, dict[str, Any]] = {}
    for o in opps:
        if o.get("outcome") != "published":
            continue
        k = str(o.get("kind"))
        if k not in best or (_f(o.get("delta_profit")) or 0.0) > (
            _f(best[k].get("delta_profit")) or 0.0
        ):
            best[k] = o
    return best


async def options(
    data: DataPort,
    labels: LabelTable,
    *,
    kind: str | None,
    levers_: list[str],
    item: str | None,
) -> list[dict[str, Any]]:
    """Exactly 4 option rows (priced, or a stated reason)."""
    raw: list[dict[str, Any]] = []
    if kind and not levers_:
        res = await data.compare_options(kind, item=item)
        raw = [{**o, "kind": o.get("lever") or kind} for o in (res.get("options") or [])]
    else:
        best = _by_lever(await data.opportunities(item=item))
        wanted = list(levers_)
        for lv in wanted:  # a lever asked for with no published row: its own reason
            o = best.get(lv)
            raw.append(
                o
                if o is not None
                else {"kind": lv, "reason": NO_OPPORTUNITY_VI, "delta_profit": None}
            )
        if len(raw) < N_OPTIONS:  # the next best opportunities of other levers
            rest = sorted(
                (o for k, o in best.items() if k not in wanted),
                key=lambda o: -(_f(o.get("delta_profit")) or 0.0),
            )
            raw += rest[: N_OPTIONS - len(raw)]
    raw = raw[:N_OPTIONS]
    rows = [_row(labels, i + 1, o, str(o.get("kind") or kind or "")) for i, o in enumerate(raw)]
    while len(rows) < N_OPTIONS:  # a missing option states why
        rows.append(
            _row(
                labels,
                len(rows) + 1,
                {"kind": kind or "", "reason": NO_OPPORTUNITY_VI, "delta_profit": None},
                kind or "",
            )
        )
    return rows


def pick(rows: list[dict[str, Any]]) -> int | None:
    """Index of the highest Δ lợi nhuận among the priced options (first on a tie)."""
    best: int | None = None
    for i, r in enumerate(rows):
        p = r.get("_profit")
        if r.get("reason") or p is None:
            continue
        if best is None or p > rows[best]["_profit"]:
            best = i
    return best


async def build(
    data: DataPort,
    labels: LabelTable,
    *,
    kind: str | None,
    levers_: list[str],
    item: str | None,
    as_of_vi: str = "",
) -> dict[str, Any]:
    """The `compare` event plus `lead_figure_vi` (the figure the pick was made on)."""
    rows = await options(data, labels, kind=kind, levers_=levers_, item=item)
    i = pick(rows)
    lead = ""
    if i is not None:
        rows[i]["recommended"] = True
        lead = f"{rows[i]['option']}: lợi nhuận tăng {rows[i]['profit_delta_vi']}"
    for r in rows:
        r.pop("_profit", None)
    return {
        "type": "data_answer",
        "kind": "compare",
        "title_vi": TITLE_VI,
        "fresh_vi": as_of_vi,
        "rows": rows,
        "stop": "data_answer",
        "lead_figure_vi": lead,
    }


def lead_text(block: dict[str, Any]) -> str:
    """The answer's lead: the pick and the figure it was picked on, or why there is none."""
    if block["lead_figure_vi"]:
        return f"Nên chọn {block['lead_figure_vi']}."
    return "Juli chưa có đủ số liệu để chọn một phương án."


TOP_ITEM_DAYS = 30


async def _item(
    data: DataPort, engine: CardEnginePort | None, kinds: list[str], phrase: str, as_of: date
) -> str | None:
    """The product the options are for: the one named, else (when a kind needs a product) the
    biggest by GMV in the last 30 days, read from `query(group_by="item")` (an order over the
    returned rows)."""
    if phrase:
        hits = await data.catalog_search(phrase)
        if hits:
            return str(hits[0]["item_id"])
    needs = bool(kinds) and engine is not None and any(engine.needs_item(k) for k in kinds)
    if not needs:
        return None
    res = await data.metrics(
        ["gmv"], as_of - timedelta(days=TOP_ITEM_DAYS - 1), as_of, scope="shop", group_by="item"
    )
    rows = [r for r in res.get("rows", []) if r.get("gmv") is not None]
    return str(max(rows, key=lambda r: float(r["gmv"]))["item"]) if rows else None


async def run_compare(
    data: DataPort,
    engine: CardEnginePort | None,
    labels: LabelTable,
    as_of: date,
    kinds: list[str],
    phrase: str = "",
) -> tuple[dict[str, Any], str]:
    """The `compare` event and the lead sentence. One kind = 4 options of that kind; several
    kinds = one option per kind; none = the best opportunities of different levers."""
    item = await _item(data, engine, kinds, phrase, as_of)
    block = await build(
        data,
        labels,
        kind=kinds[0] if len(kinds) == 1 else None,
        levers_=kinds if len(kinds) > 1 else [],
        item=item,
        as_of_vi=f"Số liệu đến hết {as_of:%d/%m}",
    )
    return block, lead_text(block)
