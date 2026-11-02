#!/usr/bin/env python3
"""LOCAL ONLY: does the backend Shopee KPI job reproduce the juli-client-ops reference tools?

Compares, metric by metric, three things on a client's real local data:

1. **data path** -- the daily series the job reads from ``platform_daily_metrics`` (local
   Postgres, loaded through the ingest gateway) vs the reference's normalised CSVs;
2. **KPI + expected move** -- ``services.shopee_kpi.rules`` / ``.expected_move`` on the
   database series vs ``tools/kpi.py`` / ``tools/expected_move.py`` run on the CSVs;
3. **flow GLM** -- ``services.shopee_kpi.flow_glm`` on the reference CSV vs a stored
   ``flow_model.py`` output folder (``params.json``, ``baseline.csv``).

Prints ``match`` or ``differs by X %`` per metric. ``--show-values`` also prints the
values (terminal only). Nothing is written anywhere except the reference tools' own
output in a temporary directory. Never commit the inputs or the output of this script:
they are client data.

    PYTHONPATH=backend/src python scripts/shopee_kpi_parity.py \
        --database-url postgresql://...local \
        --shop-id <uuid> --kpi-json <client>/kpi.json --levers <client>/plan/levers.json \
        --daily-csv <snapshot>/daily.csv --shop-daily-csv <snapshot>/shop_daily.csv \
        --reference-tools <juli-client-ops>/tools --model-dir <snapshot>/model/<ver> \
        --measure-start YYYY-MM-DD --as-of YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import subprocess  # nosec B404
import sys
import tempfile
import uuid
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from juli_backend.services.shopee_kpi import expected_move, flow_glm
from juli_backend.services.shopee_kpi.rules import (
    ContractTerms,
    DayTotals,
    Series,
    flows_from_params,
    kpi_report,
)

REL_TOL = 1e-6


class Tally:
    def __init__(self, show: bool) -> None:
        self.show = show
        self.n_match = 0
        self.n_diff = 0

    def check(
        self, label: str, ours: float | None, ref: float | None, tol: float = REL_TOL
    ) -> None:
        if ours is None or ref is None:
            ok = ours is None and ref is None
            verdict = "match (both empty)" if ok else "differs (one side empty)"
        else:
            denom = abs(ref) if ref else 1.0
            rel = abs(ours - ref) / denom
            ok = rel <= tol
            verdict = "match" if ok else f"differs by {rel * 100:.4f} %"
        if ok:
            self.n_match += 1
        else:
            self.n_diff += 1
        values = f"  [ours={ours!r} ref={ref!r}]" if self.show else ""
        print(f"  {label:<58} {verdict}{values}")


def load_reference_series(
    daily_csv: Path, shop_csv: Path, cols: dict[str, str]
) -> dict[str, Series]:
    acc: dict[str, dict[date, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0] * 4))
    with daily_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            row = acc[r["flow"].strip()][date.fromisoformat(r["date"].strip())]
            for i, k in enumerate(("impressions", "clicks", "orders", "gmv")):
                row[i] += float(r[k] or 0)
    out: dict[str, Series] = {
        flow: {d: (v[0], v[1], v[2], v[3]) for d, v in days.items()} for flow, days in acc.items()
    }
    shop: dict[date, DayTotals] = {}
    with shop_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            shop[date.fromisoformat(r["date"].strip())] = (
                0.0,
                float(r[cols["clicks"]] or 0),
                float(r[cols["orders"]] or 0),
                float(r[cols["gmv"]] or 0),
            )
    out["ca_shop"] = shop
    return out


async def load_db_series(database_url: str, shop_id: uuid.UUID) -> dict[str, Series]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.services.shopee_kpi.job import load_series

    engine = create_async_engine(async_database_url(database_url))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            series = await load_series(session, shop_id)
            await session.rollback()
    finally:
        await engine.dispose()
    return series


def run_reference(args: argparse.Namespace, out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tools = Path(args.reference_tools)
    common = ["--shop-daily", str(args.shop_daily_csv), "--measure-start", args.measure_start]
    subprocess.run(  # nosec B603
        [
            sys.executable,
            str(tools / "kpi.py"),
            str(args.kpi_json),
            str(args.daily_csv),
            "--as-of",
            args.as_of,
            "--out",
            str(out),
            *common,
        ],
        check=True,
        capture_output=True,
        cwd=tools,
    )
    subprocess.run(  # nosec B603
        [
            sys.executable,
            str(tools / "expected_move.py"),
            str(args.kpi_json),
            str(args.daily_csv),
            "--levers",
            str(args.levers),
            "--out",
            str(out),
            *common,
        ],
        check=True,
        capture_output=True,
        cwd=tools,
    )
    kpi = json.loads((out / f"kpi_{args.as_of}.json").read_text())
    em = json.loads((out / f"expected_move_{args.measure_start}.json").read_text())
    return kpi, em


def levers_from_file(path: Path) -> list[expected_move.LeverEffect]:
    out = []
    for lv in json.loads(path.read_text())["levers"]:
        for e in lv["effects"]:
            out.append(
                expected_move.LeverEffect(
                    lever_key=str(lv["id"]),
                    wave=int(lv.get("wave", 1)),
                    starts_on=date.fromisoformat(lv["start"]),
                    lag_days=int(lv.get("lag_days", 0)),
                    flow=e["flow"],
                    metric=e["metric"],
                    low=float(e["low"]),
                    high=float(e["high"]),
                    ends_on=date.fromisoformat(lv["end"]) if lv.get("end") else None,
                )
            )
    return out


def compare_series(
    t: Tally, db: dict[str, Series], ref: dict[str, Series], first: date, last: date
) -> None:
    print("1. data path: database series vs reference CSV (sums over the compared days)")
    for flow in sorted(ref):
        days = [first + timedelta(i) for i in range((last - first).days + 1)]
        s_db, s_ref = db.get(flow, {}), ref[flow]
        missing = sum(1 for d in days if d in s_ref and d not in s_db)
        if missing:
            print(f"  {flow}: {missing} reference days absent from the database")
        for i, name in enumerate(("impressions", "clicks", "orders", "gmv")):
            if flow == "ca_shop" and name == "impressions":
                continue
            a = sum(s_db[d][i] for d in days if d in s_db and d in s_ref)
            b = sum(s_ref[d][i] for d in days if d in s_db and d in s_ref)
            t.check(f"{flow}.{name}", a, b)
        worst = max(
            (
                abs(s_db[d][i] - s_ref[d][i])
                for d in days
                if d in s_db and d in s_ref
                for i in range(4)
                if not (flow == "ca_shop" and i == 0)
            ),
            default=0.0,
        )
        print(f"  {flow}: largest single-day absolute gap {worst:.4g}" if t.show else "", end="")
        if t.show:
            print()


def compare_kpi(
    t: Tally,
    terms: ContractTerms,
    series: dict[str, Series],
    as_of: date,
    ref: dict[str, Any],
    tag: str,
) -> None:
    print(f"2a. KPI (Phụ lục 01) on the {tag} series vs tools/kpi.py")
    ours = kpi_report(terms, series, as_of)
    for fr in ours.flows:
        rf = ref["flows"][fr.flow]
        if fr.eligible != rf["eligible"]:
            t.n_diff += 1
            print(f"  {fr.flow}.eligible differs")
        else:
            t.n_match += 1
        t.check(f"{fr.flow}.orders_28d", fr.orders_28d, rf["orders_28d"])
        for m, rm in zip(fr.metrics, rf["metrics"], strict=True):
            for key in ("baseline", "D", "last_window", "pass_level", "target_level"):
                ours_v = m.d_pct if key == "D" else getattr(m, key)
                t.check(f"{fr.flow}.{m.metric}.{key}", ours_v, rm.get(key))
            if m.window_days != rm["window_days"]:
                t.n_diff += 1
                print(f"  {fr.flow}.{m.metric}.window_days differs")
            fp, rfp = m.first_stable_pass, rm.get("first_stable_pass")
            if (fp or {}).get("window_end") != (rfp or {}).get("window_end"):
                t.n_diff += 1
                print(f"  {fr.flow}.{m.metric}.first_stable_pass differs")
    acc = ref["acceptance"]
    same = (ours.acceptance.eligible, ours.acceptance.passed, ours.acceptance.needed) == (
        acc["eligible"],
        acc["passed"],
        acc["needed"],
    )
    print(f"  acceptance tally {'match' if same else 'differs'}")


def compare_expected_move(
    t: Tally,
    terms: ContractTerms,
    series: dict[str, Series],
    levers: list[expected_move.LeverEffect],
    ref: dict[str, Any],
    tag: str,
) -> None:
    print(f"2b. expected move on the {tag} series vs tools/expected_move.py")
    em = expected_move.ExpectedMove(terms, series, levers)
    rows = {(f.flow, f.metric, f.milestone, f.trend_weight): f for f in em.forecasts()}
    for flow, metrics in ref["flows"].items():
        for metric, r in metrics.items():
            for ms in r["milestones"]:
                for scen, weight in (("no_trend", 0.0), ("trend", 1.0)):
                    f = rows.get((flow, metric, ms["milestone"], weight))
                    label = f"{flow}.{metric}.T{ms['milestone']}.{scen}"
                    if f is None:
                        t.n_diff += 1
                        print(f"  {label}: missing on our side")
                        continue
                    if f.window_end.isoformat() != ms["window_end"]:
                        t.n_diff += 1
                        print(f"  {label}: window end differs")
                    t.check(label + ".expected", f.expected, ms[scen]["expected"])
                    t.check(label + ".p_pass", f.p_pass, ms[scen]["p_pass"])
                    t.check(label + ".lo90", f.lo90, ms[scen]["lo90"])


def compare_glm(t: Tally, series: dict[str, Series], model_dir: Path) -> None:
    print("3. flow GLM (numpy IRLS) on the reference CSV vs the stored flow_model.py output")
    params = json.loads((model_dir / "params.json").read_text())
    with (model_dir / "baseline.csv").open(newline="") as f:
        base = {(r["flow"], r["metric"]): r for r in csv.DictReader(f)}
    origin = min(min(s) for f, s in series.items() if f != "ca_shop" and s)
    for key, p in sorted(params.items()):
        flow, metric = key.split("/")
        model = flow_glm.fit_rate(flow, metric, series.get(flow, {}), origin=origin)
        if p.get("status") != "ok":
            same = model is None
            print(
                f"  {key}: reference insufficient; ours "
                + ("insufficient (match)" if same else "fitted (differs)")
            )
            t.n_match += same
            t.n_diff += not same
            continue
        if model is None:
            t.n_diff += 1
            print(f"  {key}: ours insufficient, reference fitted")
            continue
        coef = model.coef
        worst = max(abs(coef[c] - v) for c, v in p["coef"].items())
        ok = worst < 1e-5
        t.n_match += ok
        t.n_diff += not ok
        print(f"  {key}.coefficients (max abs gap {worst:.2e}) {'match' if ok else 'differs'}")
        se = model.se
        t.check(f"{key}.se[Intercept]", se["Intercept"], p["se"]["Intercept"], 1e-4)
        t.check(f"{key}.dispersion", model.fit.dispersion, p["dispersion"], 1e-6)
        b = flow_glm.band(model)
        rb = base[(flow, metric)]
        for name in ("raw_rate", "adjusted_rate", "forecast_mean", "band90_low", "band90_high"):
            t.check(f"{key}.{name}", getattr(b, name), float(rb[name]), 1e-5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--shop-id", required=True)
    ap.add_argument("--kpi-json", required=True, type=Path)
    ap.add_argument("--levers", required=True, type=Path)
    ap.add_argument("--daily-csv", required=True, type=Path)
    ap.add_argument("--shop-daily-csv", required=True, type=Path)
    ap.add_argument("--reference-tools", required=True, type=Path)
    ap.add_argument("--model-dir", type=Path)
    ap.add_argument("--measure-start", required=True)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--show-values", action="store_true")
    args = ap.parse_args()
    if "127.0.0.1" not in args.database_url and "localhost" not in args.database_url:
        sys.exit("local databases only")

    cfg = json.loads(args.kpi_json.read_text())
    ref_series = load_reference_series(
        args.daily_csv, args.shop_daily_csv, cfg["shop_daily_columns"]
    )
    db_series = asyncio.run(load_db_series(args.database_url, uuid.UUID(args.shop_id)))
    start, as_of = date.fromisoformat(args.measure_start), date.fromisoformat(args.as_of)
    terms = ContractTerms.from_params(cfg, measure_start=start, flows=flows_from_params(cfg))
    levers = levers_from_file(args.levers)
    t = Tally(args.show_values)

    first = max(min(s) for s in ref_series.values())
    compare_series(t, db_series, ref_series, first, as_of)
    with tempfile.TemporaryDirectory() as tmp:
        ref_kpi, ref_em = run_reference(args, Path(tmp))
    for tag, series in (("database", db_series), ("reference CSV", ref_series)):
        compare_kpi(t, terms, series, as_of, ref_kpi, tag)
        compare_expected_move(t, terms, series, levers, ref_em, tag)
    if args.model_dir:
        compare_glm(t, ref_series, args.model_dir)
    print(f"\n{t.n_match} match, {t.n_diff} differ")
    return 0 if t.n_diff == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
