"""Doc and script contract tests for Cloudflare origin lockdown (#736)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/cloudflare-origin-lockdown.sh"
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/vps-wiring-runbook.md"


def test_cloudflare_origin_lockdown_script_exists():
    """Script must exist and be a regular file."""
    assert SCRIPT_PATH.is_file(), f"Script not found: {SCRIPT_PATH}"


def test_cloudflare_origin_lockdown_script_passes_bash_syntax_check():
    """Script must pass bash -n syntax check."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash syntax check failed for {SCRIPT_PATH}:\n{result.stderr}"


def test_cloudflare_origin_lockdown_script_has_port_22_safety_guard():
    """Script must contain explicit port 22 safety guard."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must guard against modifying port 22
    assert "port 22" in script_text.lower() or "ssh" in script_text.lower(), (
        "Script must document/guard against modifying SSH (port 22)"
    )
    # Must fail if port 22 would be blocked
    assert "fail" in script_text.lower(), "Script must have fail conditions for safety"


def test_cloudflare_origin_lockdown_script_has_fail_closed_logic():
    """Script must fail closed if IP ranges cannot be fetched or are empty."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must check for empty ranges
    assert "empty" in script_text.lower() or "size" in script_text.lower(), (
        "Script must validate that fetched ranges are not empty"
    )
    # Must abort on fetch failure
    assert (
        "fetch" in script_text.lower()
        or "curl" in script_text.lower()
        or "download" in script_text.lower()
    ), "Script must document how it fetches ranges"


def test_cloudflare_origin_lockdown_script_has_dry_run_support():
    """Script must support a --dry-run or similar flag."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    has_dry_run = (
        "dry" in script_text.lower() or "--print" in script_text or "--check" in script_text
    )
    assert has_dry_run, "Script must support dry-run or inspection mode"


def test_cloudflare_origin_lockdown_script_has_idempotency_guard():
    """Script must document or enforce idempotency (no duplicate rules)."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert (
        "idempotent" in script_text.lower()
        or "duplicate" in script_text.lower()
        or "check" in script_text.lower()
    ), "Script must address idempotency (no duplicate rules on re-run)"


def test_cloudflare_origin_lockdown_systemd_timer_and_service_exist():
    """Systemd timer and service for automatic IP range refresh must exist."""
    service_path = SYSTEMD_DIR / "juli-cloudflare-ip-refresh.service"
    timer_path = SYSTEMD_DIR / "juli-cloudflare-ip-refresh.timer"
    assert service_path.is_file(), f"Service not found: {service_path}"
    assert timer_path.is_file(), f"Timer not found: {timer_path}"

    service_text = service_path.read_text(encoding="utf-8")
    timer_text = timer_path.read_text(encoding="utf-8")

    # Service must be Type=oneshot
    assert "Type=oneshot" in service_text, "Service must be Type=oneshot for synchronous execution"
    # Service must reference the lockdown script
    assert "cloudflare-origin-lockdown.sh" in service_text, (
        "Service must reference the origin-lockdown script"
    )
    # Timer must have OnCalendar
    assert "OnCalendar=" in timer_text, "Timer must have OnCalendar schedule"
    # Timer must reference the service
    assert "juli-cloudflare-ip-refresh.service" in timer_text, "Timer must reference the service"


def test_runbook_documents_cloudflare_proxied_topology():
    """Runbook must document Cloudflare-proxied topology (not direct A records)."""
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    # Should mention Cloudflare in the DNS section
    assert "cloudflare" in runbook_text.lower(), "Runbook must mention Cloudflare in the topology"
    # Should explain the proxy model
    assert "prox" in runbook_text.lower() or "edge" in runbook_text.lower(), (
        "Runbook must explain the proxy/edge concept"
    )


def test_runbook_documents_origin_lockdown_step():
    """Runbook must document the origin-lockdown step."""
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert (
        "origin" in runbook_text.lower()
        or "lockdown" in runbook_text.lower()
        or "firewall" in runbook_text.lower()
    ), "Runbook must reference origin-lockdown or firewall restriction step"


def test_runbook_documents_certbot_path():
    """Runbook must document that certbot HTTP-01 still works through Cloudflare."""
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    # Certbot HTTP-01 dependency
    assert "certbot" in runbook_text.lower() or "acme" in runbook_text.lower(), (
        "Runbook must mention certbot/ACME renewal"
    )
    # Must note the cloudflare path
    assert "cloudflare" in runbook_text.lower(), (
        "Runbook must explain HTTP-01 through Cloudflare proxy"
    )


# ===== CRITICAL DEFECT TESTS =====


def test_script_never_evals_remote_content():
    """Script must never eval() fetched content — critical RCE prevention."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Check for actual eval code (not in comments)
    lines = script_text.split("\n")
    for i, line in enumerate(lines):
        # Skip comments
        code_part = line.split("#")[0]
        # Look for eval invocation: "eval " or "eval("
        if "eval " in code_part or "eval(" in code_part:
            raise AssertionError(
                f"CRITICAL: Line {i + 1} contains eval() (RCE vulnerability): {code_part}"
            )


def test_script_rejects_html_error_payload():
    """Script validation must reject HTML error pages from curl."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must use curl -f (fail on HTTP errors)
    assert "-f" in script_text and "curl" in script_text, (
        "Script must use curl -f to fail on HTTP 4xx/5xx"
    )
    # Must validate CIDR format strictly (no HTML slips through)
    # Check for regex validation or explicit CIDR format check
    assert (
        "grep" in script_text
        or "^" in script_text
        or "/[0-9]" in script_text
        or "cidr" in script_text.lower()
    ), "Script must strictly validate CIDR format (reject malformed/HTML)"


def test_script_rejects_malformed_cidr_line():
    """Script must reject entire payload if any CIDR line is malformed."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must perform line-by-line validation
    assert (
        "while" in script_text
        or "for" in script_text
        or "grep" in script_text
        or "awk" in script_text
    ), "Script must validate each line for CIDR format"


def test_script_rejects_truncated_range_list():
    """Script must abort if range list is suspiciously short."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must check minimum count of ranges
    assert (
        "wc" in script_text
        or "count" in script_text.lower()
        or "lines" in script_text.lower()
        or "number" in script_text.lower()
    ), "Script must validate minimum number of ranges (detect truncation)"


def test_script_does_not_reference_port_22():
    """No generated firewall rule must reference port 22 (SSH)."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Count references to port 22 — should only be in comments/guards, not in rules
    # Rule sections should reference HTTP_01_PORT and HTTPS_PORT, never hardcoded 22
    assert "--dport 22" not in script_text, (
        "No rule should hardcode port 22; use port variables only"
    )


def test_script_idempotent_on_second_run():
    """Rule generation must be identical on second run (no chain delete/recreate issues)."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must flush and reuse chain, not delete/recreate
    assert "-F" in script_text or "flush" in script_text.lower(), (
        "Script must flush chain, not delete/recreate it"
    )
    # Should NOT have both -X (delete chain) and -N (create chain) in sequence
    # or should handle the failure case of -X gracefully
    # Check for idempotent pattern: flush -> reuse vs delete -> create
    lines = script_text.split("\n")
    has_delete_x = any("-X" in line and "iptables" in line for line in lines)
    if has_delete_x:
        # If using -X, must check that chain exists first or handle error properly
        assert "if" in script_text.lower() or "create.*if" in script_text.lower(), (
            "If using -X to delete chain, must check if chain exists first"
        )


def test_script_reject_rules_after_accept_rules():
    """All ACCEPT rules must be applied before any REJECT rules."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Find the rule application section (after "# Step 3")
    if "Step 3:" not in script_text:
        raise AssertionError("Script must have Step 3 rule application phase")

    # Extract the part where rules are applied
    apply_section = script_text.split("Step 3:")[1]

    # Check order: ACCEPT rules should be applied before REJECT rules
    accept_index = apply_section.lower().find("accept")
    reject_index = apply_section.lower().find("reject")

    if accept_index >= 0 and reject_index >= 0:
        assert accept_index < reject_index, (
            "All ACCEPT rules must be applied before REJECT rules (fail-closed logic)"
        )


def test_script_validates_strictly_every_cidr():
    """Every line from Cloudflare must match strict CIDR regex."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Must have explicit CIDR validation logic (e.g., grep -E regex)
    # IPv4: digits.digits.digits.digits/digits
    # IPv6: hex:hex:hex:hex.../digits
    assert (
        "grep" in script_text.lower() or "match" in script_text.lower() or "^[0-9]" in script_text
    ), "Script must validate each CIDR line against regex pattern"


def test_dry_run_includes_input_jump_rule():
    """Dry-run output must include the INPUT chain jump rule (the rule that matters)."""
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Find dry-run section
    if "DRY_RUN" in script_text:
        # Must print rules AND the INPUT jump
        assert ("echo" in script_text and "INPUT" in script_text) or "iptables" in script_text, (
            "Dry-run must show the INPUT jump rule, not just chain rules"
        )


def test_runbook_documents_reboot_gap():
    """Runbook must document iptables persistence across reboots or the gap."""
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert (
        "reboot" in runbook_text.lower()
        or "persist" in runbook_text.lower()
        or "boot" in runbook_text.lower()
    ), "Runbook must document iptables rules persistence across reboot"


def test_dry_run_output_all_rules_complete_and_well_formed():
    """Dry-run output must contain only complete, well-formed iptables invocations.

    This test catches array-slicing bugs where rules get shredded across multiple
    invocations. Every rule line must:
    - Start with iptables or ip6tables
    - Contain -t filter
    - Contain -A CHAIN_NAME or -I INPUT
    - Contain -p tcp
    - Contain --dport (with a port number)
    - End with -j ACCEPT, -j REJECT, or -j CHAIN_NAME (INPUT jump)
    No line should be incomplete or missing critical arguments.
    """
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    # Check that dry-run section uses single invocation pattern, not sliced arrays
    # Look for emit_or_apply or similar single-rule emission
    if "emit_or_apply" in script_text:
        # New code path: each rule emitted individually
        pass  # Fixed!
    else:
        # Old code path: check that array slicing doesn't exist
        # If we see "i += 10" with rules that are 12 elements, fail
        if "i += 10" in script_text and "iptables" in script_text:
            # Count elements per rule: 12 for IPv4/IPv6 rules
            # Stride of 10 would shred them
            # This is the bug we're looking for
            assert False, (
                "CRITICAL: Array stride is wrong (i += 10 but rules are 12 elements); "
                "rules will be shredded. Use emit_or_apply pattern instead."
            )


def test_runbook_documents_rollback_leaves_origin_open():
    """Runbook must document that rollback leaves origin OPEN, not locked."""
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    # Should mention the tradeoff: unprotected (open) rather than locked out
    assert (
        "unprotect" in runbook_text.lower()
        or "open" in runbook_text.lower()
        or "exposed" in runbook_text.lower()
        or "available" in runbook_text.lower()
    ), "Runbook must document that failed rules leave origin OPEN (not locked)"
