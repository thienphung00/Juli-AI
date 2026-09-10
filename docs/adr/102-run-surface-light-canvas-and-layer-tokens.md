# ADR-102: The run surface returns to the light Juli canvas, on layer tokens a glass pass can redefine

**Status:** Accepted
**Date:** 2026-09-10
**Deciders:** owner, with a Claude Code session (grill-with-docs, Architect)
**Supersedes:** [`PUI-DESIGN.md`](../product/agent-workflow-execution/PUI-DESIGN.md) §6's
visual *direction* — see "What this does and does not supersede" below for the precise
boundary, which is narrower than it first appears.
**Builds on:** [ADR-076](076-agent-demo-execution-experience.md) (the token-freedom
mandate and the staged run view, both untouched here),
[ADR-054](054-brand-pink-role-separation.md) (`#b0386a` is the only pink permitted as text on
light), [ADR-094](094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md) (the
two demo doors — unaffected).
**Design authority:** `PUI-DESIGN.md` remains the wireframe, stage-model, motion and
copy authority. Only its §6 visual direction moves.
**Scope:** W6 / PRD #1308, the Optimize Product run surface and the In-Progress run
ledger — every surface carrying `data-juli-surface="run"`.

## Context

`PUI-DESIGN.md` §6 exercised ADR-076's token-freedom mandate by choosing a dark focus
ground: *"a focus surface — quieter ground than the dashboard (reduced chrome, deeper
neutral), a single accent reserved for the live edge."* #1314 implemented it in
`packages/theme/run-surface-tokens.css` — grounds `#121214` / `#1c1c20` / `#232328`, a
`#ff5fa8` live-edge accent, a `#ff8dc0` focus ring, and two brightened semantic
overrides (`--juli-run-destructive: #ff6b70`, `--juli-run-info: #6d9bff`) that existed
solely to clear WCAG AA against `#121214`. #1316, #1317 and #1318 consumed those tokens
by name.

The owner walked the W6 HITL gate (#1322) on the deployed demo on 2026-09-10 and
rejected the surface, in part, on the grounds that it *"is completely out of place, did
not follow design.md or the Juli aesthetic."* Measured computed styles on the deployed
release `42ff1fff` confirmed the composite the owner was reacting to: a `#121214` island
inside the light four-destination shell, with `#6D9BFF` — a colour in no Juli palette —
doing the emphasis work, and the one brand accent invisible.

Two independent findings came out of that investigation and are recorded here because
they bound the decision:

1. **The dark ground was not the whole complaint, but it was half of it.** The run view
   renders inside `DemoShell`, so a dark focus surface sat beside the pink `demo-assistance`
   aside, the primary nav and a literal "Mock" toggle. The structural half of that — the
   run route rendering outside the shell chrome — is a sibling owner decision of the same
   session and is *not* reversed by this ADR. `PUI-DESIGN.md` §2's dedicated run page
   stands and is reinforced.

2. **The one accent never painted at all.** `apps/demo/src/app/globals.css` declares
   `.run-stepper__node { background: … }` at identical specificity to, and later in the
   sheet than, the token layer's `.juli-run-stepper-node--active`. Verified in the
   deployed stylesheet: `.juli-run-stepper-node--active` at byte 8420,
   `.run-stepper__node{` at byte 69932. So the surface's only brand-coloured element was
   cancelled by the cascade on every build ever shipped, and a generic blue was the only
   colour a seller saw. That is a consumer defect, fixed separately; it is recorded here
   because it explains why "does not read as Juli" was a stronger complaint than one
   stray token would justify.

The owner's decision was given with a forward constraint attached:

> *"we will likely refine the UI to a liquid glass style in the future. This option must
> be able to adapt into the future design seamlessly."*

That is two requirements, not one. The second is an architectural constraint on how the
tokens are shaped, and it is the more consequential of the two.

## Decision

### 1. The run surface is light, on the Juli canvas

The dark focus ground is withdrawn. Every surface carrying `data-juli-surface="run"` —
the staged run view and the In-Progress run ledger — sits on the white seller canvas
that `design.md` and `colors_and_type.css` already specify, with pink-tinted dividers and
`#fef5f6` as a secondary fill surface only, never a page wash.

*Rejected:* keeping the dark ground and fixing only the accent and the shell composition.
It would have satisfied the letter of the gate complaint while leaving the product
speaking two visual languages one click apart, and would have left the glass constraint
below unaddressed on the surface most likely to receive it first.

### 2. What this does and does not supersede

The boundary matters, because it is the difference between a one-file change and a wave.

**Superseded:** `PUI-DESIGN.md` §6's chosen *direction* — "quieter ground than the
dashboard (reduced chrome, deeper neutral)" — and the concrete values #1314 derived from
it.

**NOT superseded, and load-bearing:**

- **ADR-076's token-freedom mandate itself.** A scoped token layer for these surfaces
  remains correct and remains in force. This ADR exercises that mandate differently; it
  does not return the surface to app-wide tokens.
- **ADR-076 decision 3** (the dedicated run page, top stepper, full-width stage canvas).
  Untouched, and reinforced by the sibling decision that the run route leaves the shell
  chrome. A reader who finds §6 amended must not infer that §2 moved.
- **ADR-076 decision 7's** designation of `PUI-DESIGN.md` as the spec artifact. It is
  still the authority; this ADR amends one of its nine sections.
- **#1314's scoping contract, in full.** Every custom property stays under
  `[data-juli-surface="run"]` and never `:root`; the file never writes a `--juli-*`
  app-wide name; `packages/theme/tokens.css` stays byte-identical; nothing outside a
  `[data-juli-surface="run"]` subtree resolves a `--juli-run-*` name.

**That scoping contract is the reason this reversal is a one-file change.** A ground
reversal, an accent change and a semantic-colour re-derivation land inside
`packages/theme/run-surface-tokens.css` alone. No component is edited, no class name
moves, and the dashboard and the other ten workflows are provably unaffected. #1314 chose
the wrong values inside the right architecture, and the architecture is what is paying for
the correction.

### 3. The accent moves to `#b0386a`, and the numbers are why

Recorded here because this is the part of the decision a future reader is most likely to
want to re-litigate. Measured against `#ffffff`:

| Candidate | Contrast on white | Verdict on a light ground |
|---|---|---|
| `#ff5fa8` (#1314's live-edge accent) | **2.82:1** | Fails AA text (4.5:1) **and** the 3.0:1 non-text minimum. Unusable in any role. |
| `--juli-primary` `#f86ba5` | 2.75:1 | Fails both. |
| `--juli-primary-strong` `#e85a94` | 3.32:1 | Fails as text; `design.md`'s anti-pattern list forbids it as a text colour outright. |
| **`--juli-primary-text` `#b0386a`** | **5.80:1** | Passes as text, as a fill boundary, and — since white-on-`#b0386a` is also **5.80:1** — as a filled swatch with a label on it. |
| `--juli-primary-900` `#8c2d54` | 8.02:1 | Passes; darker than the brand reads. |

`--juli-run-live-edge` is therefore redefined to `var(--juli-primary-text)` (`#b0386a`),
which [ADR-054](054-brand-pink-role-separation.md) already establishes as the only pink
`colors_and_type.css` permits as text on light. Because one value clears both the fill
role and the thin-mark role at the same ratio, **the accent needs no fill/text split** —
one token continues to serve the stepper's active node, the streaming caret and the armed
CTA.

**The token keeps its name.** Renaming it to something generic would discard the
"reserved for the live edge only" discipline the name encodes, and it would force a
consumer edit. Delivering a ground reversal *and* an accent change with zero consumer
edits is the clearest available proof that decision 4's architecture does what it claims.

Two consequences of moving to a light ground that must not be discovered at an
accessibility gate, and are therefore decided here:

- **The scoped focus ring is retired.** `#ff8dc0` is **2.14:1** on white — worse than the
  accent it accompanied. `--juli-run-focus-ring` becomes the accent value.
  (Separately noted, not decided here: the *app-wide* `--juli-focus-ring`,
  `rgba(232, 90, 148, 0.58)`, is a 58% alpha of a 3.32:1 pink over white and also misses
  3:1. That is a pre-existing app-wide issue, out of this ADR's scope, and is recorded so
  it is not rediscovered as new.)
- **Three of the four semantic colours fail as text on white, and this surface uses two of
  them as text today.** Each gains a `-text` variant, while the base token continues to
  serve fills and tints:

  | Token | Base (fill/tint) | On white | `-text` variant | On white |
  |---|---|---|---|---|
  | success | `#16a34a` | 3.30:1 | `#15803d` | **5.02:1** |
  | warning | `#f59e0b` | 2.15:1 | `#b45309` | **5.02:1** |
  | destructive | `#e5484d` | 3.91:1 | `#b42318` | **6.57:1** |
  | info | `#2563eb` | **5.17:1** | none needed | — |

  The dark layer's two brightened overrides are deleted outright, since the base values
  are correct again on white. That removes `#6D9BFF` from the surface at the root rather
  than patching its usage — the colour the owner named is gone, not relocated.

### 4. Surfaces are layer tokens, so a future glass pass changes only the token file

This is the decision that answers the owner's forward constraint, and it is an
architectural commitment rather than a colour choice.

Literal ground colours (`--juli-run-bg`, `--juli-run-surface`, `--juli-run-surface-raised`,
`--juli-run-border`) are replaced by **four semantic layers** — `canvas`, `panel`,
`raised`, `overlay` — each carrying **four facets**: fill, border, shadow and blur.
`overlay` is defined although nothing consumes it yet, so a future sheet or popover has a
layer to land on rather than inventing one.

**The blur tokens are `0px` today and are consumed anyway.** Every panel rule declares
`backdrop-filter: blur(var(--juli-run-<layer>-blur))` now, at zero. This is the
load-bearing part of the decision and the reason the constraint is architectural rather
than aspirational: glass is not only a colour change, and **a pass that must add a CSS
property to every panel rule is a consumer change** — which would break the "token layer
only" promise on the first day it was tested. The same reasoning applies to `box-shadow`,
since a translucent surface needs elevation a flat one does not.

Every derived value is a `color-mix(in srgb, var(--base) N%, transparent)`, never a
hand-written `rgba()` literal. Tints, glows and hairlines then track their base
automatically, so redefining one accent redefines its glow — precisely what a glass pass
needs, and precisely what today's `rgba(255, 95, 168, 0.22)` literal prevents.

The governance rule is stated in the token file and in `packages/theme/MODULE.md`:

> A future re-theme of this surface — including a liquid-glass pass — changes this file
> only. Consumers reference layer tokens; they never declare a literal colour, blur,
> shadow or border-colour.

**A rule of this kind is only real if a test enforces it**, so the enforceable form is
part of the decision: no rule outside `packages/theme/run-surface-tokens.css` may declare
`background`, `background-color`, `border-color`, `box-shadow` or `backdrop-filter` with a
literal value on a run-surface selector.

### 5. The dark values are deleted, not retained behind a selector

*Rejected:* keeping the dark palette behind `html.dark` or a second surface attribute, in
case it is wanted back.

That is speculative generality. What makes a future re-theme — dark, glass, or otherwise —
cheap is the layer shape in decision 4, not a retained mode that nothing renders, nothing
tests, and no one maintains. An unused theme rots quietly and is then trusted by whoever
finds it. The values are recorded in this ADR and in #1314's history; that is where a
reversal would read them from.

## Rationale

The reasoning is set out in the decisions above and is not restated here. In brief: the
owner rejected the dark ground at the W6 gate (Context), and the accent that ground was
built around fails every WCAG threshold on white by measurement, not by opinion
(decision 3) — so "keep the dark accent on a light page" was never available. The forward
constraint the owner attached is a statement about *change cost*, not about appearance,
and change cost is determined by whether consumers reference semantics or literals — hence
decision 4, and hence the blur tokens existing at zero, which is the only way the promise
survives contact with a real glass pass. Decision 2's boundary and decision 5's deletion
both follow from the same principle: keep the architecture that made this cheap, discard
the values that did not survive review.

## Consequences

- **#1314 is substantially re-done.** Every value it chose was chosen *because* the ground
  was dark, and every one is withdrawn: the three grounds, the `#ff5fa8` accent, the
  `#1c1c20` accent foreground, the `#ff8dc0` focus ring, and the two brightened semantic
  overrides. Its contrast test is not adjusted but **re-derived from scratch**, because the
  ratios recorded in its own docstring — "destructive: 4.34:1 on the raised surface; info:
  3.62:1/3.29:1" — measure grounds that no longer exist.
- **Two of #1314's acceptance criteria become false**, and are named rather than quietly
  dropped: (a) any criterion asserting those contrast ratios against the dark grounds;
  (b) its "quieter, deeper-neutral ground than the app-wide white canvas" direction
  criterion, which is contradicted by the owner, not by the code. Its remaining criteria —
  the scoping contract, `tokens.css` byte-identity, the one-accent rule, and the
  dashboard's and other ten workflows' token values being unchanged — all still hold and
  must keep holding.
- **#1316, #1317 and #1318 are NOT re-done.** They consume `--juli-run-*` tokens by name,
  so they inherit the new ground without a component edit. This is the scoping contract
  paying for itself, and it is the strongest available argument for keeping that contract
  intact in whatever comes next.
- **The In-Progress run ledger moves to light with the run view**, because it carries the
  same `data-juli-surface="run"` attribute. It therefore stops being a dark panel embedded
  in the light Decisions page — a second instance of the same visual clash, fixed for free
  by a decision aimed at the first.
- **`PUI-DESIGN.md` §6 is amended in the same change as this ADR.** Left unamended, the
  next executor reads the design authority, finds "deeper neutral", and rebuilds the dark
  ground — the failure this ADR exists to prevent. The amendment is appended and dated
  rather than silently rewritten, matching ADR-076's own amendment convention.
- **A future liquid-glass pass has a stated, tested cost**: redefine
  `--juli-run-<layer>-fill` and `--juli-run-<layer>-blur`, and nothing else. If that ever
  stops being true, the token-only-theming test fails and says so, rather than the cost
  being discovered halfway through the pass.
- **The four semantic `-text` variants are new surface-scoped tokens, not app-wide ones.**
  The app-wide values remain exactly as `colors_and_type.css` defines them. Whether the
  rest of the product has the same as-text contrast problem is a real question this ADR
  deliberately does not answer or expand into.

## Evidence

Verified 2026-09-10 against the deployed release `42ff1fff` (BUILD_ID
`wrRHRTxMFU-bjjgChjlqx`, confirmed as the release the serving process loaded) and against
`origin/main`:

| Claim | How verified |
|---|---|
| The live-edge accent never paints | Deployed stylesheet `/_next/static/chunks/2t33rn5_83hlz.css`: `.juli-run-stepper-node--active` at byte 8420, `.run-stepper__node{` at byte 69932 — equal specificity, later wins. `#ff5fa8` absent from the owner's measured computed styles. |
| `#6D9BFF` is `--juli-run-info` | `packages/theme/run-surface-tokens.css`, `--juli-run-info: #6d9bff`; six consuming rules in `apps/demo/src/app/globals.css`, four of them non-status. |
| Every contrast figure in decision 3 | WCAG 2.x relative-luminance computation over the sRGB values, independently reproduced by the coordinating session to two decimal places. |
| `--juli-radius-medium` is a phantom token | Used 13 times in `apps/demo/src/app/globals.css`; declared 0 times anywhere in `apps/` or `packages/`; absent from the deployed stylesheet. Closed by the consumer slice, recorded here as evidence the surface drifted from its own token contract. |
| The run ledger shares the surface attribute | `apps/demo/src/components/in-progress-panel.tsx` composes `RUN_SURFACE_PANEL_CLASS_NAMES.panel` at three call sites. |
