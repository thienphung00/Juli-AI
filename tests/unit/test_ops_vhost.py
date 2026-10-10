"""P16 ops.app-juli.com vhost and provisioning (D25.1): only /v1/ops/ proxied,
the demo upstream reused (never re-included), noindex, opt-in install."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VHOST = (REPO / "infra/nginx/ops.app-juli.com.conf").read_text(encoding="utf-8")
PROVISION = (REPO / "infra/scripts/provision-nginx.sh").read_text(encoding="utf-8")


def _active(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_ops_vhost_serves_only_the_ops_api_and_the_app():
    body = _active(VHOST)
    assert "server_name ops.app-juli.com;" in body
    assert "location /v1/ops/ {" in body and "proxy_pass http://juli_api/v1/ops/;" in body
    assert "location /v1/ {\n        return 404;" in body
    assert "proxy_pass http://juli_demo;" in body
    assert "include" not in body  # the demo vhost owns the upstream include
    assert 'X-Robots-Tag "noindex, nofollow" always' in body
    assert "/etc/letsencrypt/live/demo.app-juli.com/fullchain.pem" in body


def test_provisioning_installs_the_ops_vhost_only_on_request_and_after_the_cert():
    assert 'if [ "${INSTALL_OPS_VHOST:-0}" = "1" ]; then' in PROVISION
    assert "ops.app-juli.com" in PROVISION and "subjectAltName" in PROVISION
    assert (
        "for conf in app-juli.com.conf api.app-juli.com.conf demo.app-juli.com.conf; do"
        in PROVISION
    )
