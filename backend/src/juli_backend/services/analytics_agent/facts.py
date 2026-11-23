"""What the writer is given, and the check that its text only uses that (E6 numbers check).

The writer never does arithmetic: every % change, daily average and difference is pre-computed here
and pre-formatted in the app's Vietnamese format. `numbers_check` then requires every number with
>= 3 digits and every % in the explanation to trace to a value the writer was given (the same value
rounded or re-expressed is fine: 183.755 -> "183.800", "184 nghìn"; 0,0307 -> "3,07%"). Card figures
(ΔGMV, Δ lợi nhuận, P50, version values) are never allowed in the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.types import LabelTable

RATES = {"ctr", "ctor", "margin", "cost_ratio"}
ADDITIVE = {
    "gmv",
    "orders",
    "units",
    "views",
    "clicks",
    "profit",
    "ads_spend",
    "ads_gmv",
    "net_revenue",
    "cost_total",
    "cost_ads",
    "cost_affiliate",
    "cost_offers",
}
KNOWN = ADDITIVE | RATES | {"aov", "roas"}
SCALE = {"nghìn": 1e3, "ngàn": 1e3, "k": 1e3, "triệu": 1e6, "tr": 1e6, "tỷ": 1e9}


@dataclass
class Facts:
    """Values the writer was given: `plain` in their own unit, `pct` as percent numbers."""

    plain: list[float] = field(default_factory=list)
    pct: list[float] = field(default_factory=list)

    def add(self, metric: str, v: float | None) -> None:
        if v is None:
            return
        if metric in RATES:
            self.pct.append(100 * v)
        else:
            self.plain.append(v)
            self.plain.append(abs(v))

    def add_pct(self, v: float | None) -> None:
        if v is not None:
            self.pct += [v, abs(v)]


def _change(
    metric: str, now: float | None, before: float | None, facts: Facts
) -> dict[str, str] | None:
    """% change (or points for a rate) and the difference, pre-formatted; recorded in `facts`."""
    if now is None or before is None:
        return None
    out: dict[str, str] = {}
    if metric not in RATES and before > 0:  # a % only on a positive base; a rate changes in points
        rel = 100 * (now - before) / before
        facts.add_pct(rel)
        out["thay_đổi"] = ("tăng " if rel > 0 else "giảm ") + fmt.decimal(abs(rel), 1) + "%"
    diff = now - before
    if metric in RATES:
        facts.add_pct(100 * diff)
        out["chênh_lệch"] = fmt.decimal(100 * abs(diff), 2) + " điểm %"
    else:
        facts.add(metric, diff)
        out["chênh_lệch"] = fmt.value(metric, abs(diff))
    return out


def _metric_of(f: dict[str, Any], chain_metric: str) -> str:
    if chain_metric == "cost_ratio" and f["level"] in ("product", "endpoint.product", "line"):
        return "cost_total"
    sub = f["node"].partition(".")[2]
    for cand in (sub, f["node"]):
        if cand in KNOWN:
            return cand
    return chain_metric if f["level"] == "shop" else chain_metric


def writer_input(chain_json: dict[str, Any], labels: LabelTable) -> tuple[dict[str, Any], Facts]:
    """The writer's view of one chain, with every derived number pre-computed, and the Facts."""
    facts = Facts()
    chain_metric = chain_json["metric"]
    window = chain_json["window"]
    n_days = 1
    if window.get("cur"):
        from datetime import date

        a, b = (date.fromisoformat(x) for x in window["cur"])
        n_days = (b - a).days + 1
    usual = bool(window.get("same_weekday"))
    steps = []
    for f in chain_json["findings"]:
        m = _metric_of(f, chain_metric)
        row: dict[str, Any] = {
            "mức": f["level"],
            "đối tượng": f["node_vi"],
            "trước": fmt.value(m, f["before"]),
            "sau": fmt.value(m, f["now"]),
        }
        facts.add(m, f["now"])
        facts.add(m, f["before"])
        row.update(_change(m, f["now"], f["before"], facts) or {})
        if m in ADDITIVE and f["now"] is not None and f["before"] is not None and n_days > 1:
            a_now, a_before = f["now"] / n_days, f["before"] / n_days
            facts.add(m, a_now)
            facts.add(m, a_before)
            row["trung_bình_ngày"] = {"sau": fmt.value(m, a_now), "trước": fmt.value(m, a_before)}
        elif usual and m in ADDITIVE:
            row["thường_ngày"] = fmt.value(
                m, f["before"]
            )  # `before` is the mean of the same weekdays
        if f["contribution_pct"] is not None:
            facts.add_pct(f["contribution_pct"])
            row["tỷ_trọng_%"] = fmt.decimal(abs(f["contribution_pct"]), 0)
        steps.append(row)
    summary: dict[str, Any] = {}
    if chain_json.get("explained_share") is not None:
        pct = 100 * chain_json["explained_share"]
        facts.add_pct(pct)
        summary["phần_giải_thích_%"] = fmt.decimal(pct, 0)
    shares = [
        f["contribution_pct"]
        for f in chain_json["findings"]
        if f["contribution_pct"] is not None and f["level"] in ("source", "product", "line")
    ]
    if len(shares) > 1:
        total = sum(abs(s) for s in shares[:2])
        facts.add_pct(total)
        summary["tổng_hai_mục_lớn_nhất_%"] = fmt.decimal(total, 0)
    from juli_backend.services.analytics_agent.writer import STOP_VI

    inp = {
        "kỳ": window["label_vi"],
        "kết_luận": STOP_VI.get(chain_json["stop_reason"], ""),
        "chi_tiết": steps,
        "tóm_tắt": summary,
        "sự_kiện": [e["kind"] for e in chain_json.get("events", [])],
    }
    return inp, facts


# ------------------------------------------------------------------ the check

_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b20\d{2}\b")
_NUM = re.compile(
    r"(?<![\w,.])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?\s*(%|nghìn|ngàn|triệu|tỷ|tr\b|k\b|đ|₫)?"
)
_CARD_WORDS = re.compile(r"\bP50\b|Δ", re.I)


def _tokens(text: str) -> list[tuple[str, float, float, bool]]:
    """(raw, value, rounding tolerance, is_percent) for every number worth checking."""
    out = []
    for m in _NUM.finditer(_DATE.sub(" ", text)):
        ip, frac, unit = m.group(1), m.group(2) or "", m.group(3) or ""
        digits = ip.replace(".", "")
        is_pct = unit == "%"
        if len(digits) < 3 and not is_pct:
            continue
        scale = SCALE.get(unit, 1.0)
        value = float(f"{digits}.{frac}" if frac else digits) * scale
        if frac:
            step = 10 ** -len(frac)
        else:
            step = 10 ** (len(digits) - len(digits.rstrip("0"))) if digits.strip("0") else 1
        out.append((m.group(0).strip(), value, step * scale / 2 + 1e-9, is_pct))
    return out


def numbers_check(text: str, facts: Facts | list[Facts], *, card_figures: list[float]) -> list[str]:
    """Failures: card figures, then numbers / percentages not traced to a given value."""
    allf = facts if isinstance(facts, list) else [facts]
    plain = [v for f in allf for v in f.plain]
    pct = [v for f in allf for v in f.pct]
    body = "\n".join(text.splitlines()[1:])  # the first line is the restated question
    fails: list[str] = []
    if _CARD_WORDS.search(body):
        fails.append("card_words")
    for raw, value, tol, is_pct in _tokens(body):
        if any(abs(value - c) <= max(tol, 0.5) for c in card_figures) and not is_pct:
            fails.append(f"card_figure:{raw}")
        elif not any(abs(value - v) <= tol for v in (pct if is_pct else plain)):
            fails.append(f"untraced:{raw}")
    return fails
