"""The reference ``kpi.json`` -> contract terms (services/shopee_kpi/contracts.py).

Synthetic files only: real contract terms are client data.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from juli_backend.services.shopee_kpi.contracts import (
    LOCAL_KEYS,
    ContractFileError,
    parse_contract_file,
)
from juli_backend.services.shopee_kpi.rules import ContractTermsError


def _doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_note": "synthetic",
        "client": "Synthetic shop",
        "contract": "01/2099/SYN (gửi 01/01/2099, chưa ký)",
        "appendix_signed": None,
        "measure_start": "2099-01-01",
        "pass": 0.03,
        "target": 0.05,
        "min_clicks": 50,
        "flows": {
            "the_san_pham": {"metrics": ["impressions", "ctr"]},
            "ca_shop": {"metrics": ["ctor", "aov"], "role": "theo_doi"},
        },
        "exclusions": {"sale_days": ["11-11"], "pad_days": 1, "extra": []},
        "adjustments": [],
        "achieved": [],
        "shop_daily_columns": {"clicks": "Lượt truy cập"},
    }
    doc.update(over)
    return doc


def test_terms_keep_every_key_but_the_reference_bookkeeping():
    parsed = parse_contract_file(_doc())

    assert parsed.contract_ref == "01/2099/SYN"
    assert parsed.measure_start == date(2099, 1, 1)
    assert not LOCAL_KEYS & parsed.params.keys()
    assert parsed.params["min_clicks"] == 50
    assert parsed.params["flows"]["ca_shop"]["role"] == "theo_doi"


def test_an_explicit_contract_ref_wins_over_the_file():
    assert parse_contract_file(_doc(), contract_ref=" REF-1 ").contract_ref == "REF-1"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"adjustments": [{"flow": "the_san_pham"}]}, "adjustments"),
        ({"measure_start": None}, "measure_start"),
        ({"measure_start": "01/11/2099"}, "YYYY-MM-DD"),
        ({"contract": ""}, "contract reference"),
        ({"contract": "X" * 65}, "longer than"),
        ({"flows": {}}, "no flows"),
    ],
)
def test_a_file_that_cannot_be_a_contract_is_refused(over, message):
    with pytest.raises(ContractFileError) as exc:
        parse_contract_file(_doc(**over))

    assert message in str(exc.value)


def test_terms_the_kpi_job_would_refuse_are_refused_before_any_write():
    with pytest.raises(ContractTermsError) as exc:
        parse_contract_file(_doc(target=None))

    assert "target" in str(exc.value)
