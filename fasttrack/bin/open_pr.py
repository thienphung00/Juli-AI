#!/usr/bin/env python3
"""fasttrack/bin/open_pr.py --head BRANCH --title T --body-file F [--base fasttrack/optimize-product] --session S

Opens a PR through the GitHub REST API with curl (gh's Go TLS fails in the sandbox).
The repo is PUBLIC, so before anything is posted it scans the title, the body and every
commit message in base..head for private data and refuses on a hit:
  - e-mail addresses (except GitHub/Anthropic noreply), VN phone numbers,
  - JWTs / bearer tokens / API keys, database URLs carrying a password,
  - the shared state's `public_scrub_terms` fact (comma list: real shop ids, client names
    the owner wants kept out of public text) — `state.py fact public_scrub_terms "a,b" --session S`.
File contents are gitleaks' job (fasttrack/check.sh); this covers the free text.

Guards: base must be fasttrack/*; head must be pushed; body file must be non-empty.
Records the PR number on the batch in the shared state.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "state", Path(__file__).resolve().parent.parent / "state.py"
)
assert _spec and _spec.loader
state = importlib.util.module_from_spec(_spec)
sys.modules["state"] = state
_spec.loader.exec_module(state)

PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "vn-phone": re.compile(r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    "bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),
    "api-key": re.compile(r"(?:sk-[A-Za-z0-9-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})"),
    "db-url-password": re.compile(r"postgres(?:ql)?://[^:\s/]+:[^@\s]+@"),
}
EMAIL_OK = re.compile(
    r"(?i)(noreply@anthropic\.com|users\.noreply\.github\.com|@example\.(com|org)$)"
)


def scan(text: str, terms: list[str]) -> list[str]:
    hits = []
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            if name == "email" and EMAIL_OK.search(m.group(0)):
                continue
            hits.append(f"{name}: {m.group(0)[:60]}")
    low = text.lower()
    for t in terms:
        if t and t.lower() in low:
            hits.append(f"scrub term: {t}")
    return hits


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--head", required=True)
    p.add_argument("--base", default=state.DEPLOY_BRANCH)
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True, type=Path)
    p.add_argument("--session", required=True)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    if not a.base.startswith("fasttrack/"):
        print(f"REFUSED base must be fasttrack/* (got {a.base})", file=sys.stderr)
        return 1
    if not a.body_file.is_file() or not a.body_file.read_text().strip():
        print(f"REFUSED body file {a.body_file} missing or empty", file=sys.stderr)
        return 1
    if (
        subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{a.head}"],
            capture_output=True,
        ).returncode
        != 0
    ):
        print(f"REFUSED {a.head} is not pushed to origin", file=sys.stderr)
        return 1
    body = a.body_file.read_text()
    subprocess.run(["git", "fetch", "-q", "origin", a.base, a.head], capture_output=True)
    msgs = state.git("log", "--format=%B", f"origin/{a.base}..origin/{a.head}", check=False)
    with state.locked_state(write=False) as st:
        terms = [
            t.strip() for t in st["facts"].get("public_scrub_terms", {}).get("value", "").split(",")
        ]
    hits = scan("\n".join([a.title, body, msgs]), terms)
    if hits:
        print("REFUSED the repo is public and this PR text carries private data:", file=sys.stderr)
        for h in sorted(set(hits)):
            print(f"  - {h}", file=sys.stderr)
        print(
            "Remove it from the title/body (or reword the commit messages) and retry.",
            file=sys.stderr,
        )
        return 1
    payload = json.dumps({"title": a.title, "head": a.head, "base": a.base, "body": body})
    if a.dry_run:
        print(f"OK dry run: would open {a.head} -> {a.base} ({len(body)} chars body)")
        return 0
    tok = state.github_token()
    out = subprocess.run(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            "-H",
            f"Authorization: Bearer {tok}",
            "-H",
            "Accept: application/vnd.github+json",
            f"https://api.github.com/repos/{state.REPO}/pulls",
            "--data-binary",
            "@-",
        ],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        resp = json.loads(out.stdout)
    except json.JSONDecodeError:
        print(f"FAILED {out.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    if "number" not in resp:
        print(f"FAILED {resp.get('message')} {resp.get('errors', '')}", file=sys.stderr)
        return 1
    print(f"opened PR #{resp['number']}: {resp['html_url']}")
    state.main(
        [
            "batch",
            a.head,
            "--session",
            a.session,
            "--status",
            "pr-open",
            "--pr",
            str(resp["number"]),
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
