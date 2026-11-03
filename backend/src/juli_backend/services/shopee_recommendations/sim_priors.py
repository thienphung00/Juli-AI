"""Import of the buyer simulation's `juli-sim/priors/v1` export (ADR-121 d.8) and its use as a
weighted prior.

The simulation stays local; an audited Ops import writes the file (per shop, never merged
across shops) to a run table, and the prediction reads it as a prior weighted by the per
change_kind gate (``gate_weight``: 0.0 or 1.0 from the simulation's own validation; Ops may
override per kind, recorded). Weight 0 leaves the prediction byte-identical to the no-simulation
path (tested). The file holds product ids and is client data: it is read at import time and
stored in the shop's own tenant row, never copied into the repository.

Schema: ``~/juli-sim-pilot/funnel/README.md`` section "juli-sim/priors/v1". Rows used: segment
``all`` (the other segments are kept for the Phân tích hypothesis view).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

FORMAT = "juli-sim/priors/v1"
MAX_ROWS = 20_000
ROW_FIELDS = (
    "product_id",
    "change_kind",
    "variant",
    "segment",
    "metric",
    "med",
    "lo90",
    "hi90",
    "kg_value",
    "eligible",
    "gate_weight",
    "gate_status",
)
#: Compact stored row, in this order (``to_stored`` / ``from_stored``).
STORED = (
    "product_id",
    "change_kind",
    "variant",
    "segment",
    "metric",
    "med",
    "lo90",
    "hi90",
    "kg_value",
    "eligible",
)


class SimImportError(ValueError):
    """The file is not a valid priors/v1 export (the message says why; no value is quoted)."""


@dataclass(frozen=True)
class SimRow:
    product_id: str
    change_kind: str
    variant: str
    segment: str
    metric: str
    med: float
    lo90: float
    hi90: float
    kg_value: float | None
    eligible: bool


@dataclass
class SimPriors:
    run_id: str
    shop_alias: str
    model_version: str
    priors_version: str
    gate: dict[str, dict[str, Any]]
    rows: list[SimRow] = field(default_factory=list)
    _index: dict[tuple[str, str, str], list[SimRow]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {}
        for r in self.rows:
            if r.segment == "all":
                self._index.setdefault((r.product_id, r.change_kind, r.metric), []).append(r)

    def gate_weight(self, sim_kind: str) -> float:
        g = self.gate.get(sim_kind)
        return 0.0 if not g else float(g.get("weight", 0.0))

    def gate_status(self, sim_kind: str) -> str:
        g = self.gate.get(sim_kind)
        return "not_validated" if not g else str(g.get("status", "not_validated"))

    def lookup(
        self, product_id: str, sim_kind: str, metric: str, variant_hints: Sequence[str] | str | None
    ) -> SimRow | None:
        rows = self._index.get((product_id, sim_kind, metric), [])
        hints = [variant_hints] if isinstance(variant_hints, str) else list(variant_hints or [])
        for h in hints:
            for r in rows:
                if r.variant == h:
                    return r
        return None

    def kg_value(self, product_id: str, sim_kind: str) -> float | None:
        """Largest knowledge-gradient among the product's eligible variants of that kind."""
        best: float | None = None
        for (pid, kind, _), rows in self._index.items():
            if pid == product_id and kind == sim_kind:
                for r in rows:
                    if (
                        r.eligible
                        and r.kg_value is not None
                        and (best is None or r.kg_value > best)
                    ):
                        best = r.kg_value
        return best

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_version": self.model_version,
            "priors_version": self.priors_version,
            "rows": len(self.rows),
            "gate": {
                k: {"weight": v.get("weight"), "status": v.get("status")}
                for k, v in self.gate.items()
            },
        }

    def to_stored(self) -> list[list[Any]]:
        return [[getattr(r, f) for f in STORED] for r in self.rows]

    @classmethod
    def from_stored(cls, header: Mapping[str, Any], stored: Sequence[Sequence[Any]]) -> SimPriors:
        rows = [SimRow(*r) for r in stored]  # type: ignore[arg-type]
        return cls(
            header["run_id"],
            header.get("shop_alias", ""),
            header.get("model_version", ""),
            header.get("priors_version", ""),
            dict(header.get("gate", {})),
            rows,
        )


def _f(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SimImportError(f"row field {field_name} is not a number")
    return float(value)


def parse_priors(
    doc: Mapping[str, Any], *, gate_overrides: Mapping[str, float] | None = None
) -> SimPriors:
    """Validate and read a priors/v1 document. ``gate_overrides`` (kind -> weight in [0, 1])
    replaces the file's gate for those kinds; the override is recorded in the gate entry."""
    if doc.get("format") != FORMAT:
        raise SimImportError("format is not juli-sim/priors/v1")
    if doc.get("platform") != "shopee":
        raise SimImportError("platform must be shopee")
    run_id = doc.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise SimImportError("run_id missing")
    raw_rows = doc.get("rows")
    if not isinstance(raw_rows, list):
        raise SimImportError("rows missing")
    if len(raw_rows) > MAX_ROWS:
        raise SimImportError(f"more than {MAX_ROWS} rows")
    gate_in = doc.get("gate")
    if not isinstance(gate_in, dict):
        raise SimImportError("gate missing")
    gate: dict[str, dict[str, Any]] = {}
    for kind, g in gate_in.items():
        w = _f(g.get("weight"), "gate.weight")
        if not 0.0 <= w <= 1.0:
            raise SimImportError("gate weight outside [0, 1]")
        gate[kind] = {
            k: g.get(k)
            for k in (
                "weight",
                "status",
                "reason",
                "scorer",
                "delta_elpd",
                "se",
                "n_products",
                "cov90",
            )
            if k in g
        }
    for kind, w in (gate_overrides or {}).items():
        if not 0.0 <= float(w) <= 1.0:
            raise SimImportError("override weight outside [0, 1]")
        gate.setdefault(kind, {"status": "not_validated"})
        gate[kind] = {**gate[kind], "weight": float(w), "override": True}
    versions = doc.get("versions") or {}
    rows: list[SimRow] = []
    for r in raw_rows:
        if not isinstance(r, dict) or any(
            k not in r
            for k in (
                "product_id",
                "change_kind",
                "variant",
                "segment",
                "metric",
                "med",
                "lo90",
                "hi90",
            )
        ):
            raise SimImportError("a row misses a required field")
        lo, hi, med = _f(r["lo90"], "lo90"), _f(r["hi90"], "hi90"), _f(r["med"], "med")
        if lo > hi:
            raise SimImportError("a row has lo90 > hi90")
        kg = r.get("kg_value")
        rows.append(
            SimRow(
                str(r["product_id"]),
                str(r["change_kind"]),
                str(r["variant"]),
                str(r["segment"]),
                str(r["metric"]),
                med,
                lo,
                hi,
                None if kg is None else _f(kg, "kg_value"),
                bool(r.get("eligible", False)),
            )
        )
    return SimPriors(
        run_id,
        str(doc.get("shop_alias", "")),
        str(versions.get("model_version", "")),
        str(versions.get("priors_version", "")),
        gate,
        rows,
    )
