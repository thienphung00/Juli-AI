"""Read-only catalog scan: the stage diagnosis over a whole shop (ADR-106).

Applies :func:`~juli_backend.services.optimize_product.diagnosis.diagnose_product`
to every product a shop sold in the current window and writes **test cards** —
the analysis a seller or the team reads before any run exists. Nothing here
writes to TikTok: the live source builds ``ProductionReadResources`` only,
whose transport guard rejects any non-read method before signing
(``integrations/tiktok/guarded_client.py``).

Two sources, one pipeline — ``live`` pulls A-34 (three windows), GetProduct
and GetProduct per product and saves every raw response to a snapshot
directory; ``snapshot`` replays such a directory (which is also how the unit
test drives it). The live fetcher is TikTok/DB wiring, which the services layer
must not import (import-boundary gate), so it lives in the CLI wrapper
``scripts/optimize_product_catalog_scan.py`` and is passed to :func:`main` as
``live_fetcher``.

Snapshot layout (all JSON)::

    meta.json                   as_of, windows, counts
    a34_current.json            A-34 products over the current 14-day window
    a34_prior.json              A-34 products over the prior 28-day window
    a34_last28.json             A-34 products over the last 28 days (GMV_28d)
    products/<id>.json          GetProduct payload (title, description, images, skus)
    diagnoses/<id>.json         optional, one data.products[] entry of the
                                diagnoses endpoint when it has been captured

Outputs: ``cards.json`` (ranked cards + skips, machine-readable) and
``report.md`` (summary, angle matrix across all five angles, top cards,
skips, caveats).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from juli_backend.services.optimize_product.cards import build_cards
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.diagnosis import (
    ANGLE_CODES,
    Angle,
    Diagnosis,
    Skip,
    diagnose_product,
)
from juli_backend.services.optimize_product.funnel import (
    FunnelWindow,
    ProductFunnel,
    ShopMedians,
)
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    derive_local_evidence,
    listing_signals_from_product,
    parse_tiktok_diagnoses,
)

PRODUCT_CARD = "PRODUCT_CARD"

LiveFetcher = Callable[..., Coroutine[Any, Any, None]]


# --------------------------------------------------------------------------- windows


def windows(as_of: date, config: StageDiagnosisConfig) -> dict[str, tuple[str, str]]:
    """ISO ``[start_date_ge, end_date_lt)`` pairs; ``as_of`` is the last included day."""
    end_current = as_of + timedelta(days=1)
    start_current = end_current - timedelta(days=config.current_window_days)
    start_prior = start_current - timedelta(days=config.prior_window_days)
    start_28 = end_current - timedelta(days=28)
    return {
        "current": (start_current.isoformat(), end_current.isoformat()),
        "prior": (start_prior.isoformat(), start_current.isoformat()),
        "last28": (start_28.isoformat(), end_current.isoformat()),
    }


# --------------------------------------------------------------------------- snapshot writer


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


# --------------------------------------------------------------------------- snapshot → funnels


def _load(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def _a34_index(payload: Any) -> dict[str, dict]:
    products = (payload or {}).get("products") if isinstance(payload, dict) else payload
    return {str(p["id"]): p for p in (products or []) if isinstance(p, dict) and p.get("id")}


def build_inputs(
    snapshot: Path, config: StageDiagnosisConfig
) -> tuple[list[ProductFunnel], dict[str, dict], dict[str, list[Evidence]], dict[str, str]]:
    """Funnels, listing signals, evidence and exclusion reasons for every product."""
    current = _a34_index(_load(snapshot / "a34_current.json"))
    prior = _a34_index(_load(snapshot / "a34_prior.json"))
    last28 = _a34_index(_load(snapshot / "a34_last28.json"))
    meta = _load(snapshot / "meta.json") or {}
    as_of = date.fromisoformat(meta["as_of"]) if meta.get("as_of") else None

    funnels: list[ProductFunnel] = []
    signals_by_id: dict[str, dict] = {}
    evidence_by_id: dict[str, list[Evidence]] = {}
    excluded: dict[str, str] = {}
    for product_id, item in current.items():
        detail = _load(snapshot / "products" / f"{product_id}.json") or {}
        detail = detail.get("data", detail) if "data" in detail else detail
        title = str(detail.get("title") or item.get("title") or product_id)
        signals = listing_signals_from_product({**detail, "id": product_id}, config)
        signals_by_id[product_id] = asdict(signals)
        if signals.excluded_reason:
            excluded[product_id] = signals.excluded_reason
        if signals.status not in (None, "ACTIVATE"):
            excluded.setdefault(product_id, f"status {signals.status}")

        evidence = derive_local_evidence(signals, config)
        diag_entry = _load(snapshot / "diagnoses" / f"{product_id}.json")
        if isinstance(diag_entry, dict):
            evidence = parse_tiktok_diagnoses(diag_entry) + evidence
        evidence_by_id[product_id] = evidence

        cur_window = FunnelWindow.from_a34_total_performance(
            item.get("total_performance") or {}, days=config.current_window_days
        )
        prior_item = prior.get(product_id)
        prior_window = (
            FunnelWindow.from_a34_total_performance(
                prior_item.get("total_performance") or {}, days=config.prior_window_days
            )
            if prior_item
            else None
        )
        scope = "ALL_CHANNELS"
        card_cur = FunnelWindow.from_a34_product_card(item, days=config.current_window_days)
        if card_cur is not None:
            cur_window, scope = card_cur, PRODUCT_CARD
            card_prior = (
                FunnelWindow.from_a34_product_card(prior_item, days=config.prior_window_days)
                if prior_item
                else None
            )
            prior_window = card_prior if card_prior is not None else prior_window

        gmv_28 = FunnelWindow.from_a34_total_performance(
            (last28.get(product_id) or {}).get("total_performance") or {}, days=28
        ).gmv
        age_days = None
        create_time = detail.get("create_time")
        if create_time and as_of:
            age_days = (as_of - datetime.fromtimestamp(int(create_time)).date()).days

        funnels.append(
            ProductFunnel(
                product_id=product_id,
                title=title,
                current=cur_window,
                prior=prior_window,
                gmv_28d=gmv_28,
                age_days=age_days,
                channel_scope=scope,
            )
        )
    return funnels, signals_by_id, evidence_by_id, excluded


# --------------------------------------------------------------------------- report


def angle_matrix(evidence: list[Evidence], funnel: ProductFunnel) -> dict[str, str]:
    """All five angles for one product: what evidence each has, or why not."""
    codes = {e.code for e in evidence}
    row: dict[str, str] = {}
    for angle in (Angle.ANH_BIA, Angle.TIEU_DE, Angle.MO_TA):
        hits = sorted(codes & ANGLE_CODES[angle])
        row[angle.value] = ", ".join(hits) if hits else "không có bằng chứng"
    row[Angle.GIAM_GIA.value] = (
        "chỉ khi không còn mã mô tả và shop đã đặt trần giảm giá"
        if not (codes & ANGLE_CODES[Angle.MO_TA])
        else "chưa xét: mô tả còn mã"
    )
    ipo = funnel.current.items_per_order
    row[Angle.MUA_NHIEU_GIAM_NHIEU.value] = (
        f"trung bình {ipo.quantize(Decimal('0.01'))} món/đơn"
        if ipo
        else "chưa có đơn trong 14 ngày"
    )
    return row


def write_report(
    out_dir: Path,
    *,
    as_of: str,
    cards: list,
    skips: list[Skip],
    funnels: list[ProductFunnel],
    medians: ShopMedians,
    evidence_by_id: dict[str, list[Evidence]],
    config: StageDiagnosisConfig,
) -> None:
    lines: list[str] = []
    lines.append("# Quét catalog — Optimize Product (phân tích, chỉ đọc)\n")
    lines.append(
        f"Ngày dữ liệu cuối: **{as_of}** · sản phẩm có bán trong 14 ngày: **{len(funnels)}**"
    )
    lines.append(
        f"· card đề xuất thử nghiệm: **{len(cards)}** "
        f"(trong đó {sum(c.within_open_slots for c in cards)} "
        f"nằm trong {config.max_open_cards_per_shop} slot mở) · bỏ qua: **{len(skips)}**\n"
    )
    lines.append("## Trung bình shop (chỉ sản phẩm đủ volume)\n")
    lines.append("| KPI | Trung bình | Số sản phẩm đủ volume |\n|---|---|---|")
    for name, value in (("CTR", medians.ctr), ("CTOR", medians.ctor), ("AOV", medians.aov)):
        shown = (
            "— (dưới 5 sản phẩm)"
            if value is None
            else (
                f"{(value * 100).quantize(Decimal('0.01'))} %"
                if name != "AOV"
                else f"{value.quantize(Decimal('1')):,} ₫".replace(",", ".")
            )
        )
        lines.append(f"| {name} | {shown} | {medians.peers.get(name.lower(), 0)} |")
    lines.append("")

    lines.append("## Theo góc độ\n")
    by_angle = Counter(c.angle for c in cards)
    lines.append("| Góc độ | Số card |\n|---|---|")
    for angle in Angle:
        lines.append(f"| {angle.value} | {by_angle.get(angle.value, 0)} |")
    lines.append("")

    lines.append("## Card đề xuất thử nghiệm (xếp theo khoảng cách × GMV 28 ngày)\n")
    lines.append(
        "| # | Sản phẩm | Main KPI | Lý do | Góc độ | Hành động thử | Đo | Slot |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    for c in cards:
        slot = "mở" if c.within_open_slots else "chờ"
        lines.append(
            f"| {c.rank} | {c.title[:60]} (`{c.product_id}`) | {c.main_kpi} {c.main_kpi_value} | "
            f"{c.reason} | {c.angle} | {c.action} | {', '.join(c.measure)} | {slot} |"
        )
    lines.append("")

    lines.append("## Ma trận góc độ cho từng sản phẩm\n")
    lines.append(
        "| Sản phẩm | ảnh bìa | tiêu đề | mô tả | giảm giá sản phẩm | mua nhiều giảm nhiều "
        "| kênh dữ liệu |\n|---|---|---|---|---|---|---|"
    )
    for funnel in funnels:
        row = angle_matrix(evidence_by_id.get(funnel.product_id, []), funnel)
        lines.append(
            f"| {funnel.title[:50]} | {row[Angle.ANH_BIA.value]} | {row[Angle.TIEU_DE.value]} | "
            f"{row[Angle.MO_TA.value]} | {row[Angle.GIAM_GIA.value]} | "
            f"{row[Angle.MUA_NHIEU_GIAM_NHIEU.value]} | {funnel.channel_scope} |"
        )
    lines.append("")

    lines.append("## Bỏ qua và lý do\n")
    by_reason = Counter(s.reason for s in skips)
    for reason, count in by_reason.most_common():
        lines.append(f"- `{reason}`: {count}")
    lines.append("")

    caveats = Counter(cv for c in cards for cv in c.caveats)
    if caveats:
        lines.append("## Giới hạn của lần quét này\n")
        for text, count in caveats.most_common():
            lines.append(f"- {text} ({count} card)")
        lines.append("")
    lines.append(
        "Mọi con số là ước tính trên dữ liệu D-1 của TikTok. Card chỉ là đề xuất thử nghiệm; "
        "không có thay đổi nào được ghi lên TikTok trong lần quét này."
    )
    (out_dir / "report.md").write_text("\n".join(lines))


def run_snapshot(snapshot: Path, out_dir: Path, config: StageDiagnosisConfig) -> dict:
    funnels, signals_by_id, evidence_by_id, excluded = build_inputs(snapshot, config)
    medians = ShopMedians.from_products(
        (f for f in funnels if f.product_id not in excluded), config
    )
    diagnoses: list[Diagnosis] = []
    skips: list[Skip] = []
    for funnel in funnels:
        result = diagnose_product(
            funnel,
            medians,
            evidence_by_id.get(funnel.product_id, []),
            config,
            excluded_reason=excluded.get(funnel.product_id),
        )
        if isinstance(result, Diagnosis):
            diagnoses.append(result)
        else:
            skips.append(result)
    cards = build_cards(diagnoses, config)
    meta = _load(snapshot / "meta.json") or {}
    as_of = str(meta.get("as_of") or "?")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": as_of,
        "config": asdict(config),
        "medians": {
            "ctr": str(medians.ctr) if medians.ctr is not None else None,
            "ctor": str(medians.ctor) if medians.ctor is not None else None,
            "aov": str(medians.aov) if medians.aov is not None else None,
            "peers": medians.peers,
        },
        "cards": [c.to_dict() for c in cards],
        "skips": [
            {"product_id": s.product_id, "title": s.title, "reason": s.reason} for s in skips
        ],
        "signals": signals_by_id,
    }
    (out_dir / "cards.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )
    write_report(
        out_dir,
        as_of=as_of,
        cards=cards,
        skips=skips,
        funnels=funnels,
        medians=medians,
        evidence_by_id=evidence_by_id,
        config=config,
    )
    return payload


def main(argv: list[str] | None = None, *, live_fetcher: LiveFetcher | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", choices=("live", "snapshot"), required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1)
    )
    parser.add_argument("--max-products", type=int, default=200)
    parser.add_argument("--sleep", type=float, default=0.3, help="seconds between live calls")
    args = parser.parse_args(argv)
    config = StageDiagnosisConfig()
    if args.source == "live":
        if live_fetcher is None:
            raise SystemExit(
                "--source live needs a live fetcher; run scripts/optimize_product_catalog_scan.py"
            )
        asyncio.run(
            live_fetcher(
                args.snapshot_dir,
                args.as_of,
                config,
                max_products=args.max_products,
                sleep_s=args.sleep,
            )
        )
    payload = run_snapshot(args.snapshot_dir, args.out_dir, config)
    print(
        f"products={len(payload['signals'])} cards={len(payload['cards'])} "
        f"skips={len(payload['skips'])} → {args.out_dir / 'report.md'}"
    )
    return 0
