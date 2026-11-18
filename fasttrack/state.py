#!/usr/bin/env python3
"""fasttrack/state.py — one shared, machine-readable state for parallel fast-track sessions.

Why: the 2026-11-16 pipeline baseline (pipeline-eval/BASELINE-2026-11-16.md) found the
shared state (deploy-branch tip, batch branches, migration numbers, deploy tags and
their results, env facts, open owner asks) living in chat — 173 cross-session messages
a week, >= 6 collisions. Every session reads and writes THIS file instead.

Storage: <git common dir>/fasttrack-state/STATE.json (shared by every worktree of the
clone, never committed, never pushed) + events.jsonl (append-only history, read by
pipeline-eval for metrics). Override with JULI_FASTTRACK_STATE_DIR.

Commands (all print a short human summary; --json for machine output):
  show                                   current state, stale entries flagged
  refresh                                re-read the deploy-branch tip, batch merge status,
                                         and pending deploy-tag conclusions (GitHub API)
  check --session S [--branch B]         refresh, then list BLOCKERS for S; exit 1 if any.
                                         Run before rebase / push / "ready" / tag.
  session S --role R [--owns a,b]        register or update a session
  batch B --session S [--status X] [--pr N] [--note TEXT]
                                         register/update a batch branch (head/base from git)
  claim-migration N --session S --name NAME --branch B [--transfer-from S0 --approved-by WHO]
                                         a claim held by S0 moves to S only with both flags
  migration N --status merged|live|released
  tag-record TAG SHA --session S         record a deploy tag (tag-deploy.sh does this)
  tag-result TAG --conclusion C [--run-id ID]
  fact KEY VALUE --session S             env/infra fact (prod DB host, prod migration head, ...)
  ask --session S TEXT                   open question for the owner
  answer ID TEXT                         close it
  ab-assign BATCH SLICE --session S      A/B arm for an executor slice (balanced per batch)
  ab-result SLICE --field value ...      record slice outcome metrics
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

DEPLOY_BRANCH = "fasttrack/optimize-product"
REPO = "thienphung00/Juli-AI"
STALE_HOURS = 24
MIGRATIONS_DIR = "backend/src/juli_backend/database/migrations/versions"
BATCH_STATUSES = ("building", "ready", "pr-open", "merged", "abandoned")
MIGRATION_STATUSES = ("claimed", "merged", "live", "released")
AB_FIELDS = (
    "owner_defects",
    "done_disproved",
    "evidence_rows",
    "evidence_total",
    "test_runs",
    "test_failures",
    "gate",
    "tokens",
    "wall_minutes",
)


# --------------------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------------------


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args: str, cwd: str | None = None, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def state_dir() -> Path:
    env = os.environ.get("JULI_FASTTRACK_STATE_DIR")
    if env:
        return Path(env)
    common = Path(git("rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = Path.cwd() / common
    return common.resolve() / "fasttrack-state"


def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "deploy_branch": {"name": DEPLOY_BRANCH, "tip": None, "checked_at": None},
        "sessions": {},
        "batches": {},
        "migrations": {},
        "tags": [],
        "facts": {},
        "asks": [],
        "ab": {},
    }


@contextlib.contextmanager
def locked_state(write: bool = True):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "STATE.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = d / "STATE.json"
        st = json.loads(path.read_text()) if path.exists() else empty_state()
        for k, v in empty_state().items():
            st.setdefault(k, v)
        yield st
        if write:
            st["updated_at"] = now()
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".STATE.", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(st, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)


def event(kind: str, **data: Any) -> None:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "events.jsonl", "a") as f:
        f.write(json.dumps({"at": now(), "kind": kind, **data}, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------------------
# remote reads (all best-effort: a failure is reported, never silently treated as fresh)
# --------------------------------------------------------------------------------------


def remote_tip() -> str | None:
    out = subprocess.run(
        ["git", "ls-remote", "origin", f"refs/heads/{DEPLOY_BRANCH}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.split()[0]


def github_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    return out.stdout.strip() or None


def github_get(path: str) -> Any:
    """GET api.github.com via curl (gh's Go TLS fails in the sandbox; curl works)."""
    tok = github_token()
    if not tok:
        raise RuntimeError("no GitHub token (gh auth token is empty)")
    cmd = [
        "curl",
        "-sS",
        "-f",
        "-H",
        f"Authorization: Bearer {tok}",
        "-H",
        "Accept: application/vnd.github+json",
        f"https://api.github.com{path}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"GET {path}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def deploy_run_for_tag(tag: str) -> dict[str, Any] | None:
    q = urllib.parse.quote(tag)
    data = github_get(
        f"/repos/{REPO}/actions/workflows/fasttrack-deploy.yml/runs?branch={q}&per_page=5"
    )
    runs = data.get("workflow_runs") or []
    return runs[0] if runs else None


def remote_head(branch: str) -> str | None:
    """The sha of origin's `branch`, or None when it is not pushed (or origin is unreadable)."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.split()[0]


def current_head(name: str, b: dict[str, Any]) -> str | None:
    """The batch branch's head from git now; the stored head only when git has no such ref."""
    return git("rev-parse", "--verify", "-q", f"{name}^{{commit}}", check=False) or b.get("head")


def batch_landed(name: str, b: dict[str, Any], tip: str) -> bool:
    """True when the batch's current head is on the tip.

    A batch registered before anything was built has head == base (often == tip); that is
    not a merge (2026-11-17: batch-1117a was marked merged 3 commits ahead of the tip).
    """
    head = current_head(name, b)
    if head:
        b["head"] = head
    if not head or head == b.get("base"):
        return False
    return is_ancestor(head, tip)


def is_ancestor(a: str, b: str) -> bool:
    return (
        subprocess.run(["git", "merge-base", "--is-ancestor", a, b], capture_output=True).returncode
        == 0
    )


# --------------------------------------------------------------------------------------
# logic
# --------------------------------------------------------------------------------------


def refresh(st: dict[str, Any]) -> list[str]:
    """Update tip, batch merge status and tag conclusions. Returns warnings."""
    warn: list[str] = []
    tip = None
    try:
        tip = remote_tip()
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        warn.append(f"could not read origin tip: {e}")
    if tip:
        old = st["deploy_branch"].get("tip")
        st["deploy_branch"].update(tip=tip, checked_at=now())
        if old != tip:
            event("tip-moved", old=old, new=tip)
        subprocess.run(
            ["git", "fetch", "-q", "origin", DEPLOY_BRANCH], capture_output=True, timeout=120
        )
        for name, b in st["batches"].items():
            if b.get("status") in ("merged", "abandoned"):
                continue
            if batch_landed(name, b, tip):
                b.update(status="merged", updated_at=now())
                event("batch-merged", batch=name, head=b["head"], tip=tip)
            else:
                rh = remote_head(name)
                b.update(remote_head=rh, pushed=bool(rh) and rh == b.get("head"))
    elif not warn:
        warn.append("origin tip unreadable (network?) — state may be stale")
    for t in st["tags"]:
        if t.get("conclusion") in (None, "pending", "in_progress", "queued"):
            try:
                run = deploy_run_for_tag(t["tag"])
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
                warn.append(f"could not read deploy run for {t['tag']}: {e}")
                continue
            if run:
                t["run_id"] = run["id"]
                t["conclusion"] = run.get("conclusion") or run.get("status")
                if run.get("conclusion"):
                    event(
                        "tag-result", tag=t["tag"], conclusion=run["conclusion"], run_id=run["id"]
                    )
    return warn


def migration_numbers_in(ref: str) -> set[int]:
    out = git("ls-tree", "--name-only", f"{ref}:{MIGRATIONS_DIR}", check=False)
    nums = set()
    for line in out.splitlines():
        m = re.match(r"(\d{3,})_", line)
        if m:
            nums.add(int(m.group(1)))
    return nums


def blockers(st: dict[str, Any], session: str, branch: str | None) -> tuple[list[str], list[str]]:
    """(blocking, advisory) messages for `session` working on `branch`."""
    block: list[str] = []
    adv: list[str] = []
    tip = st["deploy_branch"].get("tip")
    if not tip:
        block.append("deploy-branch tip unknown — run `state.py refresh` with network")
    # pending / failed tags
    if st["tags"]:
        last = st["tags"][-1]
        if last.get("conclusion") in (None, "pending", "in_progress", "queued"):
            block.append(
                f"deploy tag {last['tag']} ({last['sha'][:8]}) has no result yet — do not tag or merge on top"
            )
        elif last.get("conclusion") != "success":
            adv.append(
                f"last deploy tag {last['tag']} FAILED ({last.get('conclusion')}) — prod is NOT at {last['sha'][:8]}"
            )
    if branch:
        head = git("rev-parse", branch, check=False)
        if tip and head and not is_ancestor(tip, head):
            block.append(
                f"{branch} does not contain the deploy tip {tip[:8]} — merge origin/{DEPLOY_BRANCH} first"
            )
        # migration numbers on the branch that nobody claimed / someone else claimed
        if tip:
            new_nums = migration_numbers_in(branch) - migration_numbers_in(tip)
            for n in sorted(new_nums):
                c = st["migrations"].get(str(n))
                if not c:
                    block.append(
                        f"migration {n} on {branch} is not claimed — `state.py claim-migration {n} ...`"
                    )
                elif c.get("session") != session:
                    block.append(f"migration {n} is claimed by {c.get('session')}, not {session}")
    for a in st["asks"]:
        if a.get("status") == "open" and a.get("session") == session:
            adv.append(f"open owner ask #{a['id']}: {a['text'][:120]}")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=STALE_HOURS)
    for name, b in st["batches"].items():
        if b.get("status") in ("building", "ready", "pr-open") and b.get("updated_at"):
            if dt.datetime.fromisoformat(b["updated_at"].replace("Z", "+00:00")) < cutoff:
                adv.append(f"batch {name} ({b.get('session')}) not updated for > {STALE_HOURS} h")
    return block, adv


def ab_assign(st: dict[str, Any], batch: str, slice_id: str, session: str) -> str:
    ab = st["ab"].setdefault(batch, {})
    if slice_id in ab:
        return ab[slice_id]["arm"]
    counts = {"A": 0, "B": 0}
    for s in ab.values():
        counts[s["arm"]] += 1
    # balanced: the arm with fewer slices; ties alternate by batch-wide order
    arm = (
        "A"
        if counts["A"] < counts["B"]
        else "B"
        if counts["B"] < counts["A"]
        else ("A" if len(ab) % 2 == 0 else "B")
    )
    ab[slice_id] = {"arm": arm, "session": session, "assigned_at": now(), "result": {}}
    event("ab-assign", batch=batch, slice=slice_id, arm=arm, session=session)
    return arm


def render(st: dict[str, Any]) -> str:
    lines = []
    db = st["deploy_branch"]
    lines.append(f"deploy tip  {str(db.get('tip'))[:12]}  (checked {db.get('checked_at')})")
    if st["tags"]:
        t = st["tags"][-1]
        lines.append(
            f"last tag    {t['tag']} {t['sha'][:8]} -> {t.get('conclusion')} (run {t.get('run_id')})"
        )
    lines.append("sessions:")
    for n, s in sorted(st["sessions"].items()):
        lines.append(f"  {n:16} {s.get('role', '')[:40]:40} owns={','.join(s.get('owns', []))}")
    lines.append("batches:")
    for n, b in sorted(st["batches"].items()):
        lines.append(
            f"  {n:40} {b.get('status', ''):9} {b.get('session', ''):14} head={str(b.get('head'))[:8]} pr={b.get('pr')}"
        )
    lines.append("migrations:")
    for n, m in sorted(st["migrations"].items(), key=lambda x: int(x[0])):
        lines.append(f"  {n} {m.get('name', '')} {m.get('status')} by {m.get('session')}")
    if st["facts"]:
        lines.append("facts:")
        for k, f in sorted(st["facts"].items()):
            lines.append(f"  {k} = {f.get('value')}  ({f.get('by')}, {f.get('at')})")
    open_asks = [a for a in st["asks"] if a.get("status") == "open"]
    if open_asks:
        lines.append("open owner asks:")
        for a in open_asks:
            lines.append(f"  #{a['id']} [{a.get('session')}] {a['text'][:140]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="state.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("refresh")
    c = sub.add_parser("check")
    c.add_argument("--session", required=True)
    c.add_argument("--branch")
    c.add_argument("--no-refresh", action="store_true")
    s = sub.add_parser("session")
    s.add_argument("name")
    s.add_argument("--role", default="")
    s.add_argument("--owns", default="")
    b = sub.add_parser("batch")
    b.add_argument("branch")
    b.add_argument("--session", required=True)
    b.add_argument("--status", choices=BATCH_STATUSES)
    b.add_argument("--pr", type=int)
    b.add_argument("--note")
    m = sub.add_parser("claim-migration")
    m.add_argument("number", type=int)
    m.add_argument("--session", required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--branch", required=True)
    m.add_argument("--transfer-from", help="session that holds the claim now")
    m.add_argument("--approved-by", help="who approved the transfer, e.g. 'owner, ask #6'")
    ms = sub.add_parser("migration")
    ms.add_argument("number", type=int)
    ms.add_argument("--status", required=True, choices=MIGRATION_STATUSES)
    t = sub.add_parser("tag-record")
    t.add_argument("tag")
    t.add_argument("sha")
    t.add_argument("--session", required=True)
    tr = sub.add_parser("tag-result")
    tr.add_argument("tag")
    tr.add_argument("--conclusion", required=True)
    tr.add_argument("--run-id", type=int)
    f = sub.add_parser("fact")
    f.add_argument("key")
    f.add_argument("value")
    f.add_argument("--session", required=True)
    a = sub.add_parser("ask")
    a.add_argument("text")
    a.add_argument("--session", required=True)
    an = sub.add_parser("answer")
    an.add_argument("id", type=int)
    an.add_argument("text")
    aa = sub.add_parser("ab-assign")
    aa.add_argument("batch")
    aa.add_argument("slice")
    aa.add_argument("--session", required=True)
    ar = sub.add_parser("ab-result")
    ar.add_argument("slice")
    for fld in AB_FIELDS:
        ar.add_argument(f"--{fld.replace('_', '-')}")
    args = p.parse_args(argv)

    if args.cmd in ("show",):
        with locked_state(write=False) as st:
            print(json.dumps(st, indent=2, ensure_ascii=False) if args.json else render(st))
        return 0

    if args.cmd == "refresh":
        with locked_state() as st:
            for w in refresh(st):
                print(f"WARN {w}", file=sys.stderr)
            print(json.dumps(st, indent=2, ensure_ascii=False) if args.json else render(st))
        return 0

    if args.cmd == "check":
        with locked_state() as st:
            warn = [] if args.no_refresh else refresh(st)
            block, adv = blockers(st, args.session, args.branch)
        for w in warn:
            print(f"WARN    {w}")
        for x in adv:
            print(f"NOTE    {x}")
        for x in block:
            print(f"BLOCKED {x}")
        print("check: BLOCKED" if block else "check: OK")
        event("check", session=args.session, branch=args.branch, blocked=len(block))
        return 1 if block else 0

    with locked_state() as st:
        if args.cmd == "session":
            s = st["sessions"].setdefault(args.name, {})
            s.update(role=args.role or s.get("role", ""), updated_at=now())
            if args.owns:
                s["owns"] = [x.strip() for x in args.owns.split(",") if x.strip()]
            event("session", name=args.name, role=s["role"])
        elif args.cmd == "batch":
            b = st["batches"].setdefault(args.branch, {"notes": []})
            head = current_head(args.branch, b)
            tip = st["deploy_branch"].get("tip")
            base = (
                git("merge-base", args.branch, tip, check=False)
                if (tip and head)
                else b.get("base")
            )
            rh = remote_head(args.branch)
            b.update(
                session=args.session,
                head=head,
                base=base or b.get("base"),
                remote_head=rh,
                pushed=bool(rh) and rh == head,
                updated_at=now(),
            )
            if args.status:
                b["status"] = args.status
            elif b.get("status") == "merged" and tip and not batch_landed(args.branch, b, tip):
                b["status"] = "building"  # the head moved past what was merged
                event("batch-unmerged", batch=args.branch, head=head, tip=tip)
            b.setdefault("status", "building")
            if args.pr:
                b["pr"] = args.pr
            if args.note:
                b["notes"].append({"at": now(), "text": args.note})
            event("batch", batch=args.branch, session=args.session, status=b["status"], head=head)
        elif args.cmd == "claim-migration":
            key = str(args.number)
            cur = st["migrations"].get(key)
            holder = cur.get("session") if cur else None
            transfer = bool(args.transfer_from) and holder not in (None, args.session)
            if args.transfer_from and args.transfer_from != holder:
                print(
                    f"REFUSED migration {key} is held by {holder}, not {args.transfer_from}",
                    file=sys.stderr,
                )
                return 1
            if transfer and not args.approved_by:
                print("REFUSED a transfer needs --approved-by (owner approval)", file=sys.stderr)
                return 1
            if transfer and cur.get("status") != "claimed":
                print(
                    f"REFUSED migration {key} is {cur.get('status')}; only a claim can move",
                    file=sys.stderr,
                )
                return 1
            if holder not in (None, args.session) and not transfer:
                print(
                    f"REFUSED migration {key} already claimed by {holder} ({cur.get('name')}); "
                    f"to move it: --transfer-from {holder} --approved-by <who>",
                    file=sys.stderr,
                )
                return 1
            st["migrations"][key] = {
                "session": args.session,
                "name": args.name,
                "branch": args.branch,
                "status": "claimed",
                "at": now(),
            }
            if transfer:
                st["migrations"][key].update(transferred_from=holder, approved_by=args.approved_by)
                event(
                    "claim-migration-transfer",
                    number=args.number,
                    from_session=holder,
                    to_session=args.session,
                    approved_by=args.approved_by,
                )
            else:
                event("claim-migration", number=args.number, session=args.session, name=args.name)
        elif args.cmd == "migration":
            st["migrations"].setdefault(str(args.number), {})["status"] = args.status
            event("migration", number=args.number, status=args.status)
        elif args.cmd == "tag-record":
            if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
                print("REFUSED sha must be a full 40-character sha", file=sys.stderr)
                return 1
            st["tags"].append(
                {
                    "tag": args.tag,
                    "sha": args.sha,
                    "session": args.session,
                    "at": now(),
                    "conclusion": "pending",
                    "run_id": None,
                }
            )
            event("tag", tag=args.tag, sha=args.sha, session=args.session)
        elif args.cmd == "tag-result":
            for t in st["tags"]:
                if t["tag"] == args.tag:
                    t["conclusion"] = args.conclusion
                    if args.run_id:
                        t["run_id"] = args.run_id
            event("tag-result", tag=args.tag, conclusion=args.conclusion, run_id=args.run_id)
        elif args.cmd == "fact":
            st["facts"][args.key] = {"value": args.value, "by": args.session, "at": now()}
            event("fact", key=args.key, value=args.value, session=args.session)
        elif args.cmd == "ask":
            nid = max([a["id"] for a in st["asks"]] or [0]) + 1
            st["asks"].append(
                {
                    "id": nid,
                    "session": args.session,
                    "text": args.text,
                    "status": "open",
                    "at": now(),
                }
            )
            event("ask", id=nid, session=args.session)
            print(f"ask #{nid} recorded")
        elif args.cmd == "answer":
            for a in st["asks"]:
                if a["id"] == args.id:
                    a.update(status="answered", answer=args.text, answered_at=now())
            event("answer", id=args.id)
        elif args.cmd == "ab-assign":
            arm = ab_assign(st, args.batch, args.slice, args.session)
            print(arm)
        elif args.cmd == "ab-result":
            for batch in st["ab"].values():
                if args.slice in batch:
                    res = batch[args.slice]["result"]
                    for fld in AB_FIELDS:
                        v = getattr(args, fld)
                        if v is not None:
                            res[fld] = v
                    event("ab-result", slice=args.slice, **res)
                    break
            else:
                print(f"REFUSED unknown slice {args.slice} — ab-assign it first", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
