"""apiwatch — weekly watcher for TikTok Shop and Shopee API/doc changes (DECISIONS D31.10).

Fetches the platforms' PUBLIC documentation (no login, no platform credentials),
normalizes it to a stable JSON snapshot, diffs it against the committed snapshot in
``infra/apiwatch/snapshots/<platform>.json`` and renders a markdown report with the
endpoints and webhooks Juli uses listed first.

Run with any Python 3.11+ that has ``requests``::

    PYTHONPATH=infra/apiwatch python3 -m apiwatch run --platform all --out-dir /tmp/apiwatch

See docs/runbooks/apiwatch.md.
"""

SCHEMA_VERSION = 1
PLATFORMS = ("tiktok", "shopee")
