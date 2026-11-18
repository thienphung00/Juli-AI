"""Reader blocks of the Connector state: the new reason, the merge of a non-daily run, and the
dataset map kept equal to the Connector's READER_DATASETS (t2-backend, batch 1118c)."""

from __future__ import annotations

import re
from pathlib import Path

from juli_backend.services.shopee_recommendations import connector_state as cs

CONFIG_TS = Path(__file__).resolve().parents[2] / "apps/connector/src/platforms/shopee/config.ts"

LOGIN = {"section": "phan_tich_ban_hang", "reason": "login", "readers": ["shop_totals", "traffic"]}


def test_password_recheck_is_a_block_reason_for_datacenter_readers():
    blocks = cs.reader_blocks_of(
        {
            "shop_totals": "blocked:password_recheck",
            "product_period": "blocked:password_recheck|password_modal",
            "orders": "done",
        }
    )
    assert blocks == [
        {
            "section": "phan_tich_ban_hang",
            "reason": "password_recheck",
            "readers": ["shop_totals", "product_period"],
        }
    ]


def test_a_run_stopping_password_recheck_is_a_seller_centre_block():
    blocks = cs.reader_blocks_of({"traffic": "blocked_password_recheck"})
    assert blocks == [
        {"section": "seller_centre", "reason": "password_recheck", "readers": ["traffic"]}
    ]


def test_merge_removes_done_readers_and_drops_an_empty_section():
    merged = cs.merge_reader_blocks(
        [LOGIN], {"shop_totals": "done:shop_overview=posted", "traffic": "done:shop_traffic=posted"}
    )
    assert merged == []


def test_merge_keeps_readers_the_reread_did_not_report():
    merged = cs.merge_reader_blocks([LOGIN], {"shop_totals": "done:shop_overview=posted"})
    assert merged == [{**LOGIN, "readers": ["traffic"]}]


def test_merge_adds_a_newly_blocked_reader_to_its_group_or_a_new_one():
    merged = cs.merge_reader_blocks(
        [LOGIN],
        {"product_period": "blocked:login", "item_traffic": "blocked:password_recheck"},
    )
    assert merged == [
        {**LOGIN, "readers": ["shop_totals", "traffic", "product_period"]},
        {
            "section": "phan_tich_ban_hang",
            "reason": "password_recheck",
            "readers": ["item_traffic"],
        },
    ]


def test_merge_moves_a_reader_whose_block_reason_changed():
    merged = cs.merge_reader_blocks([LOGIN], {"traffic": "blocked:password_recheck"})
    assert merged == [
        {**LOGIN, "readers": ["shop_totals"]},
        {"section": "phan_tich_ban_hang", "reason": "password_recheck", "readers": ["traffic"]},
    ]


def test_a_partial_outcome_does_not_clear_a_block():
    assert cs.merge_reader_blocks([LOGIN], {"shop_totals": "partial:page_cap"}) == [LOGIN]


def test_reader_dataset_map_equals_the_connector_config():
    text = CONFIG_TS.read_text(encoding="utf-8")
    body = text.split("export const READER_DATASETS", 1)[1].split("};", 1)[0]
    parsed = {
        reader: tuple(re.findall(r'"([a-z_]+)"', datasets))
        for reader, datasets in re.findall(r"^\s*([a-z_]+):\s*\[([^\]]*)\]", body, re.M)
    }
    assert parsed, "READER_DATASETS not found in config.ts"
    assert parsed == cs.READER_DATASETS


def test_a_done_that_only_ignored_or_queued_leaves_the_block():
    outcomes = {
        "shop_totals": "done:order_lines=ignored|partial:order_cards:http_200",
        "traffic": "done:shop_traffic:2026-11-14=ignored,traffic_overview=queued",
    }
    assert cs.merge_reader_blocks([LOGIN], outcomes) == [LOGIN]
