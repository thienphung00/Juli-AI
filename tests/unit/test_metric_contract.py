"""Python ↔ TS contract for the metric registry (doc §10, "Contract test").

``apps/demo/src/lib/metrics/registry.generated.ts`` is written by
``scripts/gen_metric_contract.py``. Regenerating it in memory must give the committed file
byte for byte, so a registry change without a regeneration fails here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from juli_backend.services.capabilities import CAPABILITIES
from juli_backend.services.metrics import METRICS

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/gen_metric_contract.py"
GENERATED = ROOT / "apps/demo/src/lib/metrics/registry.generated.ts"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_metric_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _union(text: str, name: str) -> list[str]:
    block = re.search(rf"export type {name} =\n((?:  \| \"[^\"]+\";?\n)+)", text)
    assert block is not None, name
    return re.findall(r'"([^"]+)"', block.group(1))


def test_committed_ts_equals_a_fresh_generation() -> None:
    assert GENERATED.read_text(encoding="utf-8") == _generator().render(), (
        "registry.generated.ts is stale: run python scripts/gen_metric_contract.py"
    )


def test_ts_ids_equal_the_registry() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    assert _union(text, "MetricId") == list(METRICS)
    keys = re.findall(r"^  ([a-z0-9_]+): \{ id: \"([a-z0-9_]+)\"", text, flags=re.M)
    assert [k for k, _ in keys] == list(METRICS)
    assert all(k == v for k, v in keys)


def test_ts_carries_unit_rounding_and_per_day_rule() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    for m in METRICS.values():
        row = re.search(rf"^  {m.id}: (\{{.*\}}),$", text, flags=re.M)
        assert row is not None, m.id
        flag = str(m.summable).lower()
        assert f'unit: "{m.unit.value}"' in row.group(1)
        assert f'rounding: "{m.rounding.value}"' in row.group(1)
        assert f"summable: {flag}, perDayAllowed: {flag}" in row.group(1)


def test_ts_capability_ids_equal_the_registry() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    line = re.search(r"export const CAPABILITY_IDS = \[(.*)\] as const;", text)
    assert line is not None
    assert re.findall(r'"([^"]+)"', line.group(1)) == list(CAPABILITIES)


def test_generated_header_says_do_not_edit() -> None:
    assert "do not edit" in GENERATED.read_text(encoding="utf-8").splitlines()[0]


def test_contract_lists_bmsm_and_bundle_apart() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    assert '"promo_bmsm"' in text and '"bundle"' in text
    assert "promo_bmsm" in CAPABILITIES
