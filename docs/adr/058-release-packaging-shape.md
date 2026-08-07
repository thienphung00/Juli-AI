# ADR 058: Release packaging shape — build output plus a production dependency install

**Status:** Accepted
**Date:** 2026-08-07
**Deciders:** #836 (slice P0-DEL-PKG), evidenced by the #835 spike and local measurement
**Related:** [ADR-057](057-pre-user-delivery-on-single-vps.md) · PRD #820 · implemented by #837

## Context

PRD #820 left one question open: are applications delivered as **self-contained build output**
(Next.js `output: 'standalone'`), or as **build output plus a production dependency install**?

Self-contained output was the *preferred* option on paper — smaller artifact, faster start, and no
dependency resolution on the server. Both `apps/demo` and `apps/landing` deliberately avoid it today,
each carrying a one-line comment in `next.config.ts` saying so. That comment records the *what* but
not the *why*, which is exactly the gap this ADR closes.

The rationale that had to be tested was the one PRD #820 flagged as the design's single friction
point: each slot resolves to a release through its own symlink, applications start from inside that
directory, and the workspace package manager's dependency tree is *itself* symlinked. If that
resolution failed, self-contained output would have been forced rather than chosen.

## Evidence

### 1. The #835 spike removed the argument that would have forced standalone

The [#835](https://github.com/thienphung00/Juli-AI/issues/835) spike ran on the production VPS and
passed 6/6. The pnpm symlinked dependency tree **survived slot indirection**: `next` resolved through
`demo-slot-a/apps/demo/node_modules/.bin/next`, systemd resolved a symlinked `WorkingDirectory`, two
slots ran concurrently, and all 11 referenced assets served correctly. **No package-manager friction
was observed at all.**

This **confirms** the existing rationale rather than refuting it. The risk that would have compelled
a switch did not materialise on the real server.

### 2. Measured comparison

Both shapes built and run locally from this workspace (`turbo run build --force`, then started the
way each shape is meant to be started).

| Axis | Build output + production install (current) | Self-contained (`output: 'standalone'`) |
|---|---|---|
| **Artifact size** | `apps/demo/.next` **12 MB**, `apps/landing/.next` **6.8 MB** — plus a workspace dependency tree | demo **36 MB** + 1.3 MB static; landing **35 MB** + 952 KB static — self-contained |
| **Start time** (to first 2xx) | demo **1.63 s**, landing **1.24 s** | demo **0.75 s** |
| **Server memory** | ~109 MB for two extra Next instances alongside the live one, measured on the VPS in #835 | not separately measured; the running server is the same Next server in both shapes |

Two readings of artifact size matter, and they point opposite ways. In isolation, standalone ships
**one ~37 MB self-contained tree** versus 12 MB of build output that is useless without dependencies.
But per *release*, the current shape resolves dependencies through pnpm's content-addressed store, so
`apps/demo/node_modules` is **24 KB of links** into a single ~600 MB workspace store shared by every
release, while standalone **duplicates its dependencies into every retained release**. With several
releases retained for rollback (#840), the current shape is the smaller total on an 80 GB disk. Disk
is not the binding constraint either way.

Start time does not differentiate them. Both are approximately one second, and cutover is gated on
candidate verification (#838), which dominates by orders of magnitude. A 0.9 s difference buys
nothing.

### 3. Standalone's entrypoint path is derived, not fixed

The standalone build does not emit `.next/standalone/server.js`. It emits the entrypoint at the app's
path **relative to the workspace root Next infers**, observed here as:

```
apps/demo/.next/standalone/.worktrees/issue-836/apps/demo/server.js
```

Next warned that it had inferred the root by scanning for lockfiles and had found more than one. In a
release model built on **git worktrees**, where the release directory's location is part of the
deployment layout, an entrypoint path that is a function of *where the checkout sits* cannot be a
fixed `ExecStart=` in a systemd unit without pinning `outputFileTracingRoot` explicitly.

This is a caution rather than a disqualifier, and one bounded honestly: the mis-inference reproduced
here is partly an artifact of local worktrees being nested *inside* the parent checkout, which is not
how VPS releases are laid out (`~/releases/<sha>` is not inside `~/Juli-AI-v2`). **It was not verified
on the server.** It is recorded because adopting standalone would make it a question that must be
answered before the slot layout is fixed, and #835 already answered the equivalent question for the
current shape.

## Decision

**Applications are packaged as build output plus a production dependency install.** Neither
`apps/demo` nor `apps/landing` uses `output: 'standalone'`.

The prior rationale is **confirmed**, now with evidence rather than assertion.

The decisive reason is not size or speed — those are a wash or mildly favour standalone. It is that
#835 proved the current shape works end-to-end through slot indirection on the real server, while
standalone would introduce a new determinism question on the critical path in exchange for a
start-time gain that verification makes irrelevant.

### What #837 must produce

The choice above must not be read as "the server runs `pnpm install`". PRD #820 requires that **no
application build step runs on the server**, and dependency resolution on a 2 vCPU / 4 GB box during a
release is precisely the pressure that requirement exists to remove.

So the artifact #837 builds in CI must contain **both halves**, ready to run:

1. the built output (`.next`) for each deployable, and
2. its production dependency tree, resolved in CI — not resolved again on the server.

The server's only remaining job is to place the artifact in a release directory, point a slot at it,
and start the process. `infra/scripts/build-demo.sh` currently runs `pnpm install --frozen-lockfile`
and `turbo run build` **on the server**; #837 removes both, and #844 removes the script once the
combined path has completed a real release.

## Consequences

- Both `next.config.ts` files cite this ADR, so the next reader finds the reasoning rather than a bare
  prohibition. A test asserts both the citation and the absence of `output: 'standalone'`, so the
  decision cannot drift silently.
- `apps/landing` was previously unpinned — only `apps/demo` was protected by a test. Both are now.
- Revisiting this is cheap and bounded: if #837 finds that shipping a resolved dependency tree from CI
  is impractical, standalone becomes the obvious alternative, and the only new work is pinning
  `outputFileTracingRoot` and re-verifying slot start on the server as #835 did.

## Alternatives considered

**Self-contained output (`output: 'standalone'`).** Rejected above. Genuinely attractive on
self-containment and start time; rejected because its advantage is not on any axis that binds here,
and because it would reopen a server-side question that #835 has already closed for the current shape.

**Deciding per application.** Rejected. Two packaging shapes means two deploy lanes and two failure
modes on a server whose whole delivery design is being simplified to one command (#844).
