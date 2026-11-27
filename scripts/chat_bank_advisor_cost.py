"""Estimate the cost of the Chat bank's paid set BEFORE running it (owner rule: state what and the
estimated $ and wait for a yes). Reads `tests/unit/analytics_agent/bank/advisor_cases.json` and
prices each question with the current price table (`juli_agent_api.config`) and models
(`juli_agent_api.ports` defaults, or the env overrides): one parse, one router request per
expected intent, one written summary per intent, and the advisor up to its per-answer cap for an
advice question (hand-written set + generated sample). Prints a per-case line, a typical total
and an upper bound. Calls nothing.

    PYTHONPATH=backend/src:. python scripts/chat_bank_advisor_cost.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from juli_backend.services.analytics_agent import routing
from juli_backend.services.analytics_agent.advisor import cost_cap_usd
from juli_backend.services.analytics_agent.summary import SUMMARY_SYSTEM
from juli_backend.services.analytics_agent.writer import WRITER_SYSTEM
from juli_backend.services.juli_agent_api import config, ports

BANK = Path(__file__).resolve().parents[1] / "tests/unit/analytics_agent/bank"
CASES = BANK / "advisor_cases.json"
SAMPLE = BANK / "paid_sample.json"  # the stratified sample of the generated combinations
CHARS_PER_TOKEN = 3.0  # Vietnamese with diacritics tokenises denser than English
PARSE_OUT, WRITE_IN_DATA, WRITE_OUT = 600, 1_500, 400
ADVICE_WORDS = ("nên", "làm sao", "lam sao", "ưu tiên", "kế hoạch", "xử lý", "có nên")


def tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def model(env: str, default: str) -> str:
    return os.environ.get(env, "").strip() or default


def estimate(case: dict) -> tuple[float, float]:
    """(typical, upper bound) in USD for one question."""
    q = case["question"]
    parse_m = model(ports.PARSE_MODEL_ENV, ports.DEFAULT_PARSE_MODEL)
    write_m = model(ports.WRITE_MODEL_ENV, ports.DEFAULT_WRITE_MODEL)
    parse_in = tokens(routing.PARSE_SYSTEM) + tokens(json.dumps(routing.INTENT_TOOL)) + tokens(q)
    parse = 2 * config.llm_cost_usd(parse_m, parse_in, PARSE_OUT)  # one retry at worst
    exp = case.get("expect") or {}
    n = max(1, len(exp.get("stop") or [None]), exp.get("n_answers_min") or 1)
    route_in = tokens(json.dumps(routing.routing_questions({}))) + 200
    route = n * config.jev_cost_usd(route_in)
    write_in = max(tokens(WRITER_SYSTEM), tokens(SUMMARY_SYSTEM)) + WRITE_IN_DATA
    write = n * 2 * config.llm_cost_usd(write_m, write_in, WRITE_OUT)  # one rewrite at worst
    advice = cost_cap_usd() if any(w in q.lower() for w in ADVICE_WORDS) else 0.0
    typical = parse / 2 + route + write / 2 + advice / 2
    return typical, parse + route + write + advice


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    cases += json.loads(SAMPLE.read_text(encoding="utf-8"))["cases"]
    tot = up = 0.0
    for c in cases:
        t, u = estimate(c)
        tot, up = tot + t, up + u
        print(f"{c['id']:<34} ~${t:.4f}  (max ${u:.4f})")
    cap = cost_cap_usd()
    print(f"\n{len(cases)} questions: ~${tot:.3f} typical, at most ${up:.3f}")
    print(f"(advisor cap ${cap:.3f} per advice answer; prices: juli_agent_api.config)")


if __name__ == "__main__":
    main()
