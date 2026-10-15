"""List the property's sitemaps (errors, warnings, submitted vs indexed) and submit ours.

python -m scripts.seo.gsc_sitemaps            # list; exit 1 on errors or a missing sitemap
python -m scripts.seo.gsc_sitemaps --submit   # (re)submit config.SITEMAP_URL — read/write scope
python -m scripts.seo.gsc_sitemaps --sites    # which properties this Google account can read
"""

from __future__ import annotations

import argparse

from scripts.seo import config
from scripts.seo.gsc_client import GSC


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Search Console sitemaps.")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--sites", action="store_true")
    args = ap.parse_args(argv)

    gsc = GSC(write=args.submit)
    if args.sites:
        print("Google account:", gsc.account())
        sites = gsc.sites()
        for s in sites:
            print(f"{s['siteUrl']}  ({s['permissionLevel']})")
        if not any(s["siteUrl"] == config.SITE_URL for s in sites):
            print(
                f"✗ this account cannot read {config.SITE_URL} — re-run after deleting "
                f"{config.TOKEN_PATH} and choose the account that owns the property, or add "
                "this account as a user in Search Console > Settings > Users and permissions."
            )
            return 1
        return 0
    if args.submit:
        gsc.submit_sitemap(config.SITEMAP_URL)
        print("submitted", config.SITEMAP_URL)
    maps = gsc.sitemaps()
    bad = 0
    for m in maps:
        contents = ", ".join(
            f"{c['type']}: {c.get('submitted', 0)} submitted" for c in m.get("contents", [])
        )
        errors, warnings = int(m.get("errors", 0)), int(m.get("warnings", 0))
        bad += errors > 0
        print(
            f"{m['path']}  downloaded {m.get('lastDownloaded', '-')}  pending={m.get('isPending')}"
            f"  errors={errors} warnings={warnings}  [{contents}]"
        )
    if config.SITEMAP_URL not in {m["path"] for m in maps}:
        print("✗", config.SITEMAP_URL, "is not submitted — run with --submit")
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
