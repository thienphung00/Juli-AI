"""CLI.

    PYTHONPATH=infra/apiwatch python3 -m apiwatch run --platform all --out-dir OUT [--write]
    PYTHONPATH=infra/apiwatch python3 -m apiwatch diff OLD.json NEW.json --platform tiktok

``run`` writes ``OUT/<platform>.md`` (report), ``OUT/<platform>.changes.json`` and
``OUT/summary.json``; with ``--write`` it also replaces the committed snapshot when
its content changed. Exit status is 0 unless the watcher itself crashed: a
platform that could not be fetched shows up in the summary and the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apiwatch import PLATFORMS, sdk, shopee, snapshot, tiktok
from apiwatch import juli_usage as usage_mod
from apiwatch.diff import diff_snapshots
from apiwatch.fetch import Fetcher
from apiwatch.report import juli_titles, render, summary_counts, tag_juli

HERE = Path(__file__).resolve().parent
DEFAULT_SNAPSHOTS = HERE.parent / "snapshots"
DEFAULT_REPO_ROOT = HERE.parents[2]
MODULES = {"tiktok": tiktok, "shopee": shopee}


def _stats(snap: dict[str, Any]) -> dict[str, int]:
    return {k: len(snap.get(k) or {}) for k in ("endpoints", "webhooks", "changelog", "sdk")}


def analyse(
    platform: str,
    old: dict[str, Any] | None,
    new: dict[str, Any],
    usage: dict[str, Any],
) -> list[dict[str, Any]]:
    changes = diff_snapshots(old, new)
    tag_juli(changes, usage[platform], titles=juli_titles(usage[platform], old, new))
    return changes


def run_platform(platform: str, args: argparse.Namespace, usage: dict[str, Any]) -> dict[str, Any]:
    module = MODULES[platform]
    fetcher = Fetcher(delay=args.delay)
    if args.raw_in:
        raw = json.loads((Path(args.raw_in) / f"{platform}.raw.json").read_text(encoding="utf-8"))
    else:
        raw = module.fetch_raw(fetcher, limit=args.limit)
    if args.raw_dir:
        Path(args.raw_dir).mkdir(parents=True, exist_ok=True)
        (Path(args.raw_dir) / f"{platform}.raw.json").write_text(json.dumps(raw), encoding="utf-8")
    normalized = module.normalize(raw)
    sdk_data, sdk_errors = sdk.fetch(fetcher, module.SDK_REPOS)
    snap_path = Path(args.snapshots) / f"{platform}.json"
    old = snapshot.load(snap_path)
    new, kept = snapshot.build(platform, normalized, sdk_data, old, module.SDK_REPOS)
    new, text = snapshot.fit(new)
    changes = analyse(platform, old, new, usage)
    errors = {**(normalized.get("_errors") or {}), **sdk_errors}
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    report = render(
        platform,
        changes,
        date=date,
        errors=errors,
        failed_count=len(normalized.get("_failed") or []),
        kept_count=kept,
        stats=_stats(new),
        baseline=old is None,
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{platform}.md").write_text(report, encoding="utf-8")
    (out_dir / f"{platform}.changes.json").write_text(
        json.dumps(changes, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    old_text = snap_path.read_text(encoding="utf-8") if snap_path.exists() else None
    snapshot_changed = text != old_text
    if args.write and snapshot_changed:
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(text, encoding="utf-8")
    return {
        "platform": platform,
        "report": str(out_dir / f"{platform}.md"),
        "changes": summary_counts(changes),
        "has_changes": bool(changes),
        "snapshot_changed": snapshot_changed,
        "snapshot_bytes": len(text.encode("utf-8")),
        "compact": bool(new.get("compact")),
        "errors": errors,
        "failed_docs": len(normalized.get("_failed") or []),
        "requests": fetcher.requests,
        "stats": _stats(new),
    }


def cmd_run(args: argparse.Namespace) -> int:
    usage = usage_mod.load(Path(args.repo_root))
    platforms = PLATFORMS if args.platform == "all" else (args.platform,)
    results = {}
    for platform in platforms:
        print(f"apiwatch: {platform} ...", file=sys.stderr, flush=True)
        results[platform] = run_platform(platform, args, usage)
        r = results[platform]
        print(
            f"apiwatch: {platform}: {r['stats']} changes={r['changes']['total']} "
            f"juli={r['changes']['juli']} snapshot_changed={r['snapshot_changed']} "
            f"bytes={r['snapshot_bytes']} errors={len(r['errors'])} failed_docs={r['failed_docs']} "
            f"requests={r['requests']}",
            file=sys.stderr,
            flush=True,
        )
    summary = {"platforms": results}
    (Path(args.out_dir) / "summary.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8"
    )
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    usage = usage_mod.load(Path(args.repo_root))
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    changes = analyse(args.platform, old, new, usage)
    print(
        render(
            args.platform,
            changes,
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            errors={},
            failed_count=0,
            kept_count=0,
            stats=_stats(new),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apiwatch", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="fetch, snapshot, diff, report")
    run.add_argument("--platform", choices=("all", *PLATFORMS), default="all")
    run.add_argument("--snapshots", default=str(DEFAULT_SNAPSHOTS))
    run.add_argument("--out-dir", required=True)
    run.add_argument("--write", action="store_true", help="replace the snapshot file if changed")
    run.add_argument("--delay", type=float, default=0.35, help="min seconds between requests")
    run.add_argument("--limit", type=int, default=None, help="debug: cap docs fetched per kind")
    run.add_argument("--raw-dir", default=None, help="debug: also save the raw responses")
    run.add_argument("--raw-in", default=None, help="debug: re-normalize saved raw responses")
    run.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    run.set_defaults(func=cmd_run)
    diff = sub.add_parser("diff", help="report the diff between two snapshot files")
    diff.add_argument("old")
    diff.add_argument("new")
    diff.add_argument("--platform", choices=PLATFORMS, required=True)
    diff.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    diff.set_defaults(func=cmd_diff)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
