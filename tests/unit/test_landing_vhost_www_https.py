"""www.app-juli.com must have its own HTTPS server block that redirects to the apex.

Without it, a TLS request for www falls through to nginx's default server and its
certificate, and Cloudflare (Full strict) answers 526 — seen live on 2026-10-08
after provision-nginx.sh reinstalled the repo's vhost.
"""

import re
from pathlib import Path

LANDING_VHOST = Path(__file__).resolve().parents[2] / "infra" / "nginx" / "app-juli.com.conf"


def _server_blocks(text: str) -> list[str]:
    blocks, depth, start = [], 0, None
    for match in re.finditer(r"\bserver\s*\{|\{|\}", text):
        token = match.group(0)
        if token.startswith("server") and depth == 0:
            start, depth = match.start(), 1
        elif token == "{" and start is not None:
            depth += 1
        elif token == "}" and start is not None:
            depth -= 1
            if depth == 0:
                blocks.append(text[start : match.end()])
                start = None
    return blocks


def test_www_has_an_https_block_redirecting_to_the_apex() -> None:
    text = "\n".join(
        line for line in LANDING_VHOST.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    www_tls = [
        block
        for block in _server_blocks(text)
        if re.search(r"server_name\s+www\.app-juli\.com\s*;", block) and "listen 443 ssl" in block
    ]
    assert len(www_tls) == 1, "expected exactly one 443 server block for www.app-juli.com"
    block = www_tls[0]
    assert "ssl_certificate     /etc/letsencrypt/live/app-juli.com/fullchain.pem;" in block
    assert "return 301 https://app-juli.com$request_uri;" in block
