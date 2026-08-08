"""The staleness alarm must fire on simulated staleness, not on a real outage (#853).

#853's acceptance criteria require the alert be verified by simulating a stale
envelope rather than by waiting for one, and require "stale" to be distinguishable
from "endpoint down" — they need different responses.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "check-kpi-freshness.py"
_spec = importlib.util.spec_from_file_location("check_kpi_freshness", _SCRIPT)
assert _spec and _spec.loader
freshness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(freshness)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _payload(*, computed_at=None, orders_stale=False, intervals_stale=False, kpi_stale=False):
    return {
        "envelope_version": 1,
        "computed_at": (computed_at or NOW).isoformat(),
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "value": 172945097.0,
                "stale": kpi_stale,
            },
            "ctor": {"availability": "available", "value": 0.05, "stale": False},
        },
        "source_freshness": {
            "silver.orders": {"stale": orders_stale, "age_seconds": 90000},
            "analytics_performance_intervals": {"stale": intervals_stale, "age_seconds": 3600},
        },
    }


def test_fresh_envelope_passes():
    code, problems = freshness.evaluate(_payload(), now=NOW)

    assert code == freshness.EXIT_FRESH
    assert problems == []


def test_old_envelope_is_stale():
    """The original #853 incident: computed_at 25 hours behind."""
    code, problems = freshness.evaluate(_payload(computed_at=NOW - timedelta(hours=25)), now=NOW)

    assert code == freshness.EXIT_STALE
    assert any("reconcile is not completing" in p for p in problems)


def test_envelope_just_inside_the_window_passes():
    code, _ = freshness.evaluate(
        _payload(computed_at=NOW - timedelta(seconds=freshness.ENVELOPE_MAX_AGE_SECONDS)),
        now=NOW,
    )

    assert code == freshness.EXIT_FRESH


def test_fresh_envelope_over_a_frozen_feed_is_still_stale():
    """The failure this whole change introduces: gold recomputes hourly on dead data,
    so computed_at looks perfect and only source freshness gives it away."""
    code, problems = freshness.evaluate(_payload(orders_stale=True), now=NOW)

    assert code == freshness.EXIT_STALE
    assert any("silver.orders has not advanced" in p for p in problems)


def test_stale_but_available_kpis_are_named():
    code, problems = freshness.evaluate(_payload(kpi_stale=True), now=NOW)

    assert code == freshness.EXIT_STALE
    assert any("serving stale values for: gmv_tiktok" in p for p in problems)


def test_missing_source_freshness_is_not_silently_passed():
    """An envelope predating this field must not read as healthy."""
    payload = _payload()
    del payload["source_freshness"]

    code, problems = freshness.evaluate(payload, now=NOW)

    assert code == freshness.EXIT_STALE
    assert any("cannot verify" in p for p in problems)


@pytest.mark.parametrize(
    "payload",
    [{}, {"computed_at": "not-a-timestamp"}, {"kpis": {}}],
    ids=["empty", "bad_timestamp", "no_computed_at"],
)
def test_malformed_payload_is_unreachable_not_stale(payload):
    """A different fault needing a different response — must not page as staleness."""
    code, problems = freshness.evaluate(payload, now=NOW)

    assert code == freshness.EXIT_UNREACHABLE
    assert problems


def test_exit_codes_are_distinct():
    assert len({freshness.EXIT_FRESH, freshness.EXIT_STALE, freshness.EXIT_UNREACHABLE}) == 3


def test_threshold_matches_the_envelope_contract():
    """Alarm and envelope must not disagree about what stale means."""
    from juli_backend.services.gold_kpi_envelope_contract import SOURCE_STALE_AFTER_SECONDS

    assert freshness.ENVELOPE_MAX_AGE_SECONDS == SOURCE_STALE_AFTER_SECONDS["silver.orders"]


def test_cli_reports_stale_from_a_file(tmp_path, capsys):
    import json

    target = tmp_path / "payload.json"
    target.write_text(json.dumps(_payload(computed_at=NOW - timedelta(days=2))))

    assert freshness.main(["--from-file", str(target)]) == freshness.EXIT_STALE
    assert "STALE" in capsys.readouterr().err


def test_cli_reports_unreachable_on_bad_json(tmp_path, capsys):
    target = tmp_path / "broken.json"
    target.write_text("<html>502 Bad Gateway</html>")

    assert freshness.main(["--from-file", str(target)]) == freshness.EXIT_UNREACHABLE
    assert "UNREACHABLE" in capsys.readouterr().err


def test_fetch_sends_an_explicit_user_agent():
    """The edge rejects the default "Python-urllib/x.y" with 403. Without an explicit
    User-Agent this alarm reports UNREACHABLE on every run and gets ignored."""
    captured = {}

    class _FakeResponse:
        def read(self):
            return b'{"computed_at": "2026-08-08T12:00:00+00:00"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["ua"] = request.get_header("User-agent")
        return _FakeResponse()

    original = freshness.urllib.request.urlopen
    freshness.urllib.request.urlopen = fake_urlopen
    try:
        freshness.fetch("https://example.invalid/x", 10)
    finally:
        freshness.urllib.request.urlopen = original

    assert captured["ua"] == freshness.USER_AGENT
    assert "python-urllib" not in captured["ua"].lower()
