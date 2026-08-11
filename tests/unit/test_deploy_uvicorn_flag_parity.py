"""The deployed API process must be launched with the same flags as the unit file.

`deploy.sh`'s api lane is blue/green: it starts the candidate as a *transient*
`systemd-run` unit with a uvicorn command line written inline in the script, and only
then switches nginx's upstream to it. `infra/systemd/juli-api.service` is therefore not
what serves traffic after a deploy — it is only used when the box boots.

That split is invisible. #905 added `--proxy-headers --forwarded-allow-ips=127.0.0.1` to
the unit file; the deploy succeeded and `grep proxy-headers` on the VPS unit matched, but
the process actually serving traffic was launched from deploy.sh's own arg list without
them:

    unit file  : ... --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
    live :8020 : ... --workers 1

Behaviour was correct anyway, but only by luck: uvicorn 0.52 already defaults
``proxy_headers=True`` and ``forwarded_allow_ips=127.0.0.1``, which was confirmed on the
running process. A security-relevant setting should be stated, not inherited from a
library default a version bump can flip — and #921 has just demonstrated how exposed this
repo is to resolver drift. The next flag added to the unit file may not be so lucky.

This test compares the two flag lists directly. It is deliberately about *flags* and not
whole-line equality, since the port and release path legitimately differ between the two.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "infra" / "scripts" / "deploy.sh"
API_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-api.service"

# Differ legitimately between the boot unit and a blue/green candidate.
_POSITIONAL_FLAGS = {"--host", "--port"}


def _flags(text: str) -> set[str]:
    """Long-option names appearing in a uvicorn invocation, ignoring their values."""
    return {m for m in re.findall(r"--[a-z0-9][a-z0-9-]*", text)} - _POSITIONAL_FLAGS


def _unit_execstart() -> str:
    text = API_UNIT.read_text(encoding="utf-8")
    lines, collecting, out = text.splitlines(), False, []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("ExecStart="):
            collecting = True
        if collecting:
            out.append(stripped.rstrip("\\").strip())
            if not stripped.endswith("\\"):
                break
    assert out, "no ExecStart found in juli-api.service"
    return " ".join(out)


def _deploy_candidate_command() -> str:
    """The uvicorn portion of the systemd-run candidate launch.

    Sliced from the uvicorn binary onward so systemd-run's own options (--unit,
    --collect, --property) are not mistaken for uvicorn flags — they legitimately have
    no counterpart in the unit file's ExecStart.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    start = text.index('systemd-run --unit="juli-api-candidate-')
    end = text.index(">&2", start)
    body = text[start:end]
    uvicorn_at = body.index("/.venv/bin/uvicorn")
    return " ".join(
        line.strip().rstrip("\\").strip()
        for line in body[uvicorn_at:].splitlines()
        if not line.strip().startswith("#")
    )


def test_candidate_launch_and_unit_file_use_the_same_uvicorn_flags():
    unit_flags = _flags(_unit_execstart())
    deploy_flags = _flags(_deploy_candidate_command())

    missing = unit_flags - deploy_flags
    assert not missing, (
        "infra/systemd/juli-api.service passes uvicorn flags that deploy.sh's blue/green "
        f"candidate does not: {sorted(missing)}. The candidate is what serves traffic "
        "after a deploy, so these flags would be silently absent in production while the "
        "unit file on the box says otherwise. Add them to the systemd-run invocation in "
        "deploy_lane_api()."
    )

    extra = deploy_flags - unit_flags
    assert not extra, (
        "deploy.sh's candidate passes uvicorn flags the unit file does not: "
        f"{sorted(extra)}. The two must agree, or a reboot silently changes behaviour "
        "relative to a deploy."
    )


def test_the_proxy_header_flags_are_present_in_both():
    """Pinned by name — this specific pair is what #905 depends on."""
    for name, text in (
        ("juli-api.service", _unit_execstart()),
        ("deploy.sh candidate", _deploy_candidate_command()),
    ):
        assert "--proxy-headers" in text, f"{name} is missing --proxy-headers"
        assert "--forwarded-allow-ips=127.0.0.1" in text, (
            f"{name} is missing --forwarded-allow-ips=127.0.0.1 — unscoped proxy trust "
            "lets any caller spoof the address written into the audit trail"
        )


def test_the_parsers_are_not_vacuous():
    """Both extractors must actually find a uvicorn invocation.

    A parser that silently returns an empty string would make the comparison above pass
    for the worst possible reason.
    """
    for name, text in (
        ("juli-api.service", _unit_execstart()),
        ("deploy.sh candidate", _deploy_candidate_command()),
    ):
        assert "uvicorn" in text, f"{name} extractor did not find a uvicorn command"
        # >= 1, not a content threshold: this guards the extractor, and conflating it
        # with "how many flags should exist" would make it fire twice for one cause.
        assert len(_flags(text)) >= 1, f"{name} extractor found no flags: {text!r}"
