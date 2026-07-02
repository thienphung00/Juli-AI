"""Runner-agnostic backtest dataset assembler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.ai.dataset.schema import REQUIRED_PARQUET_FILES
from backend.ai.dataset.synthetic import generate_synthetic_dataset
from backend.ai.dataset.validation import validate_backtest_dataset

DATASET_VERSION = "1.0.0"


def _to_orders_frame(orders: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "order_id": order["id"],
            "tiktok_order_id": order["tiktok_order_id"],
            "shop_id": order["shop_id"],
            "buyer_id": order["buyer_id"],
            "status": order["status"],
            "order_value": order["order_value"],
            "currency": order["currency"],
            "payment_time": order["payment_time"],
            "ship_time": order["ship_time"],
            "delivery_time": order["delivery_time"],
            "created_at": order["created_at"],
            "cancel_reason": order["cancel_reason"],
            "is_seller_fault": order["is_seller_fault"],
        }
        for order in orders
    ]
    return pd.DataFrame(rows)


def _to_returns_frame(returns: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "return_id": ret["id"],
            "tiktok_return_id": ret["tiktok_return_id"],
            "order_id": ret["order_id"],
            "tiktok_order_id": ret["tiktok_order_id"],
            "shop_id": ret["shop_id"],
            "buyer_id": ret["buyer_id"],
            "product_id": ret["product_id"],
            "sku_id": ret["sku_id"],
            "return_type": ret["return_type"],
            "return_condition": ret["return_condition"],
            "return_reason": ret["return_reason"],
            "refund_amount": ret["refund_amount"],
            "status": ret["status"],
            "created_at": ret["created_at"],
        }
        for ret in returns
    ]
    return pd.DataFrame(rows)


def _parse_iso_dates(values: list[str]) -> tuple[str | None, str | None]:
    timestamps = [value for value in values if value]
    if not timestamps:
        return None, None
    parsed = sorted(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in timestamps)
    start = parsed[0].date().isoformat()
    end = parsed[-1].date().isoformat()
    return start, end


def _compute_split_boundaries(order_dates: list[str], train_ratio: float = 0.8) -> dict[str, str]:
    timestamps = [
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in order_dates
        if value
    ]
    if not timestamps:
        today = datetime.now(UTC).date().isoformat()
        return {"train_end": today, "eval_start": today}

    timestamps.sort()
    split_index = max(0, int(len(timestamps) * train_ratio) - 1)
    train_end = timestamps[split_index].date().isoformat()
    eval_index = min(split_index + 1, len(timestamps) - 1)
    eval_start = timestamps[eval_index].date().isoformat()
    return {"train_end": train_end, "eval_start": eval_start}


def _write_parquet_frames(
    output_dir: Path,
    dataset: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    frames = {
        "orders": _to_orders_frame(dataset["orders"]),
        "order_items": pd.DataFrame(dataset["order_items"]),
        "returns": _to_returns_frame(dataset["returns"]),
        "labels": pd.DataFrame(dataset["labels"]),
        "ads": pd.DataFrame(dataset["ads"]),
    }
    row_counts: dict[str, int] = {}
    for name, frame in frames.items():
        path = output_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False, engine="pyarrow")
        row_counts[name] = len(frame)
    return row_counts


def assemble_backtest_dataset(
    output_dir: str | Path,
    *,
    seed: int = 42,
    n_shops: int = 5,
    orders_per_shop: int = 100,
    return_rate: float = 0.08,
    ads_days: int = 30,
    source: str = "synthetic",
) -> dict[str, Any]:
    """Generate synthetic backtest parquet + manifest and validate before returning."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    dataset = generate_synthetic_dataset(
        seed=seed,
        n_shops=n_shops,
        orders_per_shop=orders_per_shop,
        return_rate=return_rate,
        ads_days=ads_days,
    )

    row_counts = _write_parquet_frames(root, dataset)

    order_dates = [order["created_at"] for order in dataset["orders"]]
    return_dates = [ret["created_at"] for ret in dataset["returns"]]
    date_start, date_end = _parse_iso_dates(order_dates + return_dates)

    manifest = {
        "dataset_version": DATASET_VERSION,
        "dataset_dir": str(root.resolve()),
        "source": source,
        "seed": seed,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "date_range": {"start": date_start, "end": date_end},
        "split_boundaries": _compute_split_boundaries(order_dates),
        "row_counts": row_counts,
        "files": list(REQUIRED_PARQUET_FILES),
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    validation_summary = validate_backtest_dataset(root)
    return {"manifest": manifest, "validation": validation_summary}
