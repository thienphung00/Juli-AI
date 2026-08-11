"""Credentials-in-URL guard tests (#904 / ADR-061).

Covers the exit gate from the issue: the checker must flag the synthetic
violating fixture, must report zero findings against the real backend/tests/
scripts tree, and the suppression annotation must actually suppress (only
when it carries an explicit reason).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = ROOT / "agent-runtime/scripts/ci/check_credentials_in_url.py"
SYNTHETIC_FIXTURE = ROOT / "tests/fixtures/credentials_in_url/synthetic/bad_credentials_in_url.py"

sys.path.insert(0, str(ROOT / "agent-runtime/scripts/ci"))
from check_credentials_in_url import (  # noqa: E402
    CREDENTIAL_KEY_NAMES,
    scan_file,
    scan_paths,
)


def _run_checker(*extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CHECK_SCRIPT), *extra]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)


def test_flags_synthetic_violation_fixture() -> None:
    """The purpose-built fixture must fail with a nonzero exit and name every
    violating credential key across all three detection shapes."""
    result = _run_checker(str(SYNTHETIC_FIXTURE))

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "credentials_in_url: FAIL" in combined
    assert "key 'app_secret'" in combined  # params= dict literal
    assert "key 'access_token'" in combined  # subscript assignment into params
    assert "key 'refresh_token'" in combined  # urlencode()
    assert "key 'api_key'" in combined  # f-string URL literal


def test_zero_findings_on_current_repository_tree() -> None:
    """Default invocation (no args) mirrors the lint job's ruff scope
    (backend/src/juli_backend, tests, scripts) and must be clean — the OAuth
    slice (#896/bfade493) already merged and the two legitimate vendor
    exceptions (TikTok client.py, Zalo zalo.py) carry suppression comments."""
    result = _run_checker()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "credentials_in_url: PASS" in result.stdout


def test_correct_body_based_usage_is_not_flagged(tmp_path: Path) -> None:
    """The sibling-correct pattern — credentials in `json=`, not `params=` —
    must produce zero findings, matching every real call site in this repo
    after #896."""
    good = tmp_path / "good_body_based.py"
    good.write_text(
        "import requests\n\n"
        "def exchange(app_secret: str, refresh_token: str) -> None:\n"
        "    payload = {'app_secret': app_secret, 'refresh_token': refresh_token}\n"
        "    requests.post('https://auth.example.com/token', json=payload, timeout=10)\n",
        encoding="utf-8",
    )

    assert scan_file(good, repo_root=tmp_path) == []


def test_pagination_and_client_id_keys_are_not_false_positives(tmp_path: Path) -> None:
    """`page_token`/`app_key` are pagination cursors / a public OAuth client
    id, not secrets — a naive "token"/"key" substring match would flag both."""
    fine = tmp_path / "pagination.py"
    fine.write_text(
        "import requests\n\n"
        "def list_orders(page_token: str) -> None:\n"
        "    params = {'app_key': 'not-a-secret-client-id', 'page_token': page_token}\n"
        "    requests.get('https://api.example.com/v1/orders', params=params, timeout=10)\n",
        encoding="utf-8",
    )

    assert scan_file(fine, repo_root=tmp_path) == []


def test_suppression_annotation_clears_the_finding(tmp_path: Path) -> None:
    """`# creds-url-guard: allow -- <reason>` on the flagged line suppresses
    it; the same code with no annotation at all is flagged."""
    unsuppressed = tmp_path / "unsuppressed.py"
    unsuppressed.write_text(
        "import requests\n\n"
        "def send(token: str) -> None:\n"
        "    requests.post('https://vendor.example.com/msg', "
        "params={'access_token': token}, timeout=10)\n",
        encoding="utf-8",
    )
    assert len(scan_file(unsuppressed, repo_root=tmp_path)) == 1

    suppressed = tmp_path / "suppressed.py"
    suppressed.write_text(
        "import requests\n\n"
        "def send(token: str) -> None:\n"
        "    requests.post(\n"
        "        'https://vendor.example.com/msg',\n"
        "        # creds-url-guard: allow -- vendor requires access_token as a query param\n"
        "        params={'access_token': token},\n"
        "        timeout=10,\n"
        "    )\n",
        encoding="utf-8",
    )
    assert scan_file(suppressed, repo_root=tmp_path) == []


def test_suppression_without_a_reason_does_not_count(tmp_path: Path) -> None:
    """A bare `# creds-url-guard: allow` with nothing after `--` is not a
    valid suppression — the annotation must carry an explicit reason."""
    no_reason = tmp_path / "no_reason.py"
    no_reason.write_text(
        "import requests\n\n"
        "def send(token: str) -> None:\n"
        "    requests.post(\n"
        "        'https://vendor.example.com/msg',\n"
        "        params={'access_token': token},  # creds-url-guard: allow\n"
        "        timeout=10,\n"
        "    )\n",
        encoding="utf-8",
    )

    assert len(scan_file(no_reason, repo_root=tmp_path)) == 1


def test_known_production_exceptions_carry_the_suppression_comment() -> None:
    """Regression guard: the two vendor-required access-token-in-URL call
    sites must keep their suppression comment. If someone deletes the
    comment without also fixing the underlying call, this test — not just
    CI's use of the checker — catches it directly."""
    client_py = ROOT / "backend/src/juli_backend/integrations/tiktok/client.py"
    zalo_py = ROOT / "backend/src/juli_backend/services/alerts/channels/zalo.py"

    assert "creds-url-guard: allow --" in client_py.read_text(encoding="utf-8")
    assert "creds-url-guard: allow --" in zalo_py.read_text(encoding="utf-8")


def test_auth_code_is_deliberately_excluded_from_the_credential_set() -> None:
    """`auth_code` is excluded on purpose (OAuth's inbound redirect contract,
    not a secret this codebase chooses to place in a URL) — see the module
    docstring. Locking this in as a test so it isn't "fixed" by accident."""
    assert "authcode" not in CREDENTIAL_KEY_NAMES
    assert "appsecret" in CREDENTIAL_KEY_NAMES
    assert "accesstoken" in CREDENTIAL_KEY_NAMES


@pytest.mark.parametrize(
    "scan_root",
    ["backend/src/juli_backend", "tests", "scripts"],
)
def test_scan_paths_clean_on_each_default_root(scan_root: str) -> None:
    """Exercise `scan_paths` (the function `main()` calls) directly against
    each of the three default roots individually, so a failure names exactly
    which root regressed."""
    hits = scan_paths([ROOT / scan_root], repo_root=ROOT)
    assert hits == [], hits
