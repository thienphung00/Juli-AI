"""Split a list of test files into M shards of similar size; print shard N's files.

Usage: ``python fasttrack/ci_shard.py N M < files.txt`` (1 <= N <= M). Every input file lands in
exactly one shard (the union of shards 1..M is the input, no file twice), so a sharded gate runs
the same tests as an unsharded one. Balance is greedy by file size (largest first, into the
lightest shard; ties by path), which tracks run time well enough for pytest files. Deterministic:
the same input always gives the same split, on any machine.
"""

from __future__ import annotations

import os
import sys


def shards(paths: list[str], m: int) -> list[list[str]]:
    """The M shards of ``paths`` (duplicates and blank lines dropped), each sorted by path."""
    unique = sorted({p.strip() for p in paths if p.strip()})
    sized = sorted(
        ((os.path.getsize(p) if os.path.exists(p) else 0, p) for p in unique),
        key=lambda item: (-item[0], item[1]),
    )
    bins: list[list[str]] = [[] for _ in range(m)]
    loads = [0] * m
    for size, path in sized:
        k = min(range(m), key=lambda i: (loads[i], i))
        bins[k].append(path)
        loads[k] += max(size, 1)
    return [sorted(b) for b in bins]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: ci_shard.py N M < files", file=sys.stderr)
        return 2
    n, m = int(argv[1]), int(argv[2])
    if not 1 <= n <= m:
        print(f"shard {n} of {m} is out of range", file=sys.stderr)
        return 2
    for path in shards(sys.stdin.read().splitlines(), m)[n - 1]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
