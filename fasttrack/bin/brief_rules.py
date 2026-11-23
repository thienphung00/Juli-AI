#!/usr/bin/env python3
"""fasttrack/bin/brief_rules.py BRIEF.md [--top N] [--memory-dir DIR] [--json]

Why (pipeline-eval 2026-W47): 18 "memory note not applied" and 18 "platform-doc miss"
incidents. The notes and owner decisions existed, but never reached the executor's brief,
and Shopee / TikTok behaviour was assumed before anyone looked at a real page or a probe.

What it does, for one executor brief:
  1. Standing rules: ranks the coordinator's feedback/project memory notes and the owner
     decisions in `state.py` by term overlap with the brief, and prints them as the brief's
     RULES rows (EXECUTOR-BRIEF.md §3), one per note, to be applied and evidenced.
  2. PLATFORM row: when the brief touches vendor behaviour (Shopee / TikTok pages, fills,
     readers, fees, API fields), the slice needs a real page capture or sandbox probe plus
     the doc it was checked against, BEFORE the first edit.
  3. LIB row: when the brief touches a library API, a Context7 lookup (`npx ctx7@latest`)
     cited in `## Sources`.

The output is local: notes can name clients, so never paste it into a committed file or PR
text unscrubbed (`open_pr.py` scrubs PR text). Exit 0 always; it advises, the verifier gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLATFORM_TERMS = (
    "shopee",
    "tiktok",
    "seller centre",
    "seller center",
    "connector",
    "fill",
    "reader",
    "read-back",
    "voucher",
    "combo",
    "flash sale",
    "deal sốc",
    "dvht",
    "affiliate",
    "fee",
    "phí",
    "settlement",
    "openapi",
    "partner center",
    "price_detail",
    "webhook",
    "sync",
)
LIB_TERMS = (
    "fastapi",
    "sqlalchemy",
    "alembic",
    "pydantic",
    "asyncpg",
    "celery",
    "redis",
    "httpx",
    "react",
    "next.js",
    "nextjs",
    "tailwind",
    "vitest",
    "playwright",
    "zod",
    "tanstack",
    "recharts",
    "chrome.",
    "manifest v3",
    "openpyxl",
    "pandas",
    "upgrade",
    "new dependency",
    "library",
)
STOP = set(
    "the a an and or of to in on for is are be with as by at it this that from not no never "
    "when each every one all any its into than then only before after over under per via use "
    "used uses same new owner session sessions juli rule rules note notes".split()
)


def default_memory_dir() -> Path:
    home = Path.home()
    slug = "-" + str(home).strip("/").replace("/", "-")
    return home / ".claude" / "projects" / slug / "memory"


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ỹđ0-9_+.-]{3,}", text.lower()) if w not in STOP}


def front(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if v.strip():
                out[k.strip()] = v.strip().strip('"')
    return out


def load_notes(mem: Path) -> list[dict]:
    notes = []
    for p in sorted(mem.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        t = p.read_text(errors="replace")
        fm = front(t)
        kind = fm.get("type")  # nested `metadata:\n  type: x` is flattened by front()
        if kind not in ("feedback", "project"):
            continue
        name = fm.get("name", p.stem)
        desc = fm.get("description", "")
        notes.append(
            {
                "name": name,
                "desc": desc,
                "kind": kind,
                "path": str(p),
                "head": words(name.replace("-", " ") + " " + desc),
                "body": words(t),
            }
        )
    return notes


def load_decisions() -> list[dict]:
    d = os.environ.get("JULI_FASTTRACK_STATE_DIR")
    if not d:
        try:
            import subprocess

            common = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=True
            ).stdout.strip()
            d = str(Path(common).resolve() / "fasttrack-state")
        except Exception:
            return []
    p = Path(d) / "STATE.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("decisions", [])


def rank(brief: set[str], notes: list[dict], top: int) -> list[dict]:
    scored = []
    for n in notes:
        s = 3 * len(brief & n["head"]) + len(brief & n["body"]) / 10
        if n["kind"] == "feedback":
            s *= 1.5  # standing rules from owner corrections first
        if s >= 3:
            scored.append((round(s, 1), n))
    scored.sort(key=lambda x: -x[0])
    return [dict(n, score=s) for s, n in scored[:top]]


def hits(text: str, terms: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [t for t in terms if re.search(r"(?<![a-z])" + re.escape(t), low)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("brief", type=Path)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--memory-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    text = a.brief.read_text()
    mem = a.memory_dir or Path(os.environ.get("JULI_MEMORY_DIR") or default_memory_dir())
    notes = load_notes(mem) if mem.is_dir() else []
    bw = words(text)
    chosen = rank(bw, notes, a.top)
    decisions = [d for d in load_decisions() if len(bw & words(d["text"])) >= 2]
    plat, lib = hits(text, PLATFORM_TERMS), hits(text, LIB_TERMS)
    if a.json:
        print(
            json.dumps(
                {
                    "notes": [
                        {k: n[k] for k in ("name", "desc", "kind", "path", "score")} for n in chosen
                    ],
                    "decisions": decisions,
                    "platform": plat,
                    "library": lib,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not mem.is_dir():
        print(f"WARN no memory dir at {mem} (set --memory-dir or JULI_MEMORY_DIR)", file=sys.stderr)
    print("<!-- brief_rules.py output: LOCAL ONLY, may name clients; scrub before any commit -->")
    print("### Rows to add to §3 (each needs evidence that the rule was applied)")
    print("| id | requirement | source | verification | evidence |\n|---|---|---|---|---|")
    for i, n in enumerate(chosen, 1):
        print(
            f"| R{i} | apply: {n['desc'][:160]} | memory [[{n['name']}]] | verifier checks the diff against the note | |"
        )
    for i, d in enumerate(decisions, 1):
        print(
            f"| D{i} | owner decision #{d['id']}: {d['text'][:160]} | state.py decide ({d['at']}) | verifier checks the diff | |"
        )
    if plat:
        print(
            f"| PLATFORM | real page capture or sandbox probe of the vendor behaviour, plus the doc it was checked against, BEFORE the first edit (terms: {', '.join(plat[:6])}) | standing rule (W47 M10) | capture/probe path + doc URL in `## Sources` | |"
        )
    if lib:
        print(
            f"| LIB | Context7 lookup (`npx ctx7@latest docs <lib> <topic>`) for each library API touched (terms: {', '.join(lib[:6])}) | standing rule (W47 M8a) | lookup cited in `## Sources` | |"
        )
    if not (chosen or decisions or plat or lib):
        print("| — | no standing rule matched: the coordinator confirms none applies | | | |")
    print("\n### §4 memory notes to read")
    for n in chosen:
        print(f"- {n['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
