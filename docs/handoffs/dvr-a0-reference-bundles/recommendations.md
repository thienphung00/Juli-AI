# Decisions / Recommendations — card list and five-stage review (DVR-A0)

> **IA law:** [ADR-023](../../adr/023-four-destination-analytics-ownership.md) — Decisions sub-tab **Recommendations only** (In Progress out of scope). Human gate preserved: Approve, Reject, Expand per `docs/product/design/README.md`.

## Target implementation (DVR-A4 list, DVR-A5 review)

### List presentation (DVR-A4)

- Ranked recommendation cards: **signal + one concise reason** (benefit-led Vietnamese).
- Actions: `decisions.approve`, `decisions.reject`, `decisions.expand`.
- List → detail routing + `highlight` query behavior.
- Strip backend jargon, confidence/FBS badges from rendered UI (DVR-A1 guard foundation).

### Five-stage review (DVR-A5)

Navigate **Why → Analytics → Inputs → Preview → Approve** with Vietnamese stage headings; Analytics stage links to inspectable evidence; Approve opens existing gate → In Progress.

Primary paths: `recommendations-panel.tsx`, `recommendation-review.tsx`, `packages/ui/src/recommendation-card.tsx`.

## Layout patterns to adopt (adapted, not cloned)

### Recommendation card list

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Klaviyo — Reviews overview | [Klaviyo Reviews](https://mobbin.com/screens/85bea3ee-f9d6-4734-bc6d-429723dacb32) | Vertical card stack: rating/status badge, metadata row, body copy, primary/secondary actions aligned right | “Publish/Reject” review semantics; product thumbnail; English copy |
| ClickUp — Timesheet approvals | [ClickUp Approvals](https://mobbin.com/screens/72d64728-a1bb-4767-929c-fe34a6907c80) | Tab filter row (“To review”); table row → **adapt to card row** with inline Approve/Reject affordances | Multi-column HR table density; timesheet-specific fields |
| Navan — Policy test transactions | [Navan policy preview](https://mobbin.com/screens/e77648b3-82f6-4db8-9b83-99c281da6ce4) | Status badges (approved vs flagged) with icon + color + text; inline explanation sentence for flagged state | Expense policy copy; orange/purple Navan palette as primary |

### Detail / approval drawer (review flow chrome)

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Airwallex — Spend request drawer | [Airwallex approval drawer](https://mobbin.com/screens/f163ee8f-79d1-4dc5-a626-68c25a971bca) | Right-side or full-width review panel: title, status pill, metadata grid, comment area, **sticky footer** Approve/Reject | Multi-currency finance fields; purple Airwallex buttons verbatim |
| Acctual — Approvals settings | [Acctual Approvals](https://mobbin.com/screens/c2d21189-032b-4032-a1fa-52668c365236) | Rule clarity pattern — one-line “if/then” readability for **Why** stage | Settings admin layout; approval rule editing |

## Open Design reference

| Artifact | Path | What to borrow |
|----------|------|----------------|
| ClarityCard | `DESIGN.md` §6 (`ds-juli-is-an-app-design-system`) | Recommendation decision card — signal, impact, reasoning structure |
| RealEstimatedBar | Same | Expected business impact: real vs estimated segments |
| Voice & brand | `DESIGN.md` §8 | “Đề xuất”, “Phê duyệt”; outcome-framed impact; never autonomous “Juli did X” |
| Five-step flow | ADR-023 retains ADR-014 decision-detail flow | Stage names map to seller Vietnamese in DVR-A5 — not internal `tool_name` labels |

## ADR-015 token mapping

| Element | Token / utility | Notes |
|---------|-----------------|-------|
| Card surface | `bg-card`, `--shadow-sm`, `--radius` | List cards match Home/Analytics chrome |
| Primary approve | `var(--primary)` fill | Not Mobbin black or Airwallex purple |
| Reject / destructive | `outline` + `text-destructive` or muted secondary | Avoid color-only reject |
| Pending / attention | `var(--warning)` tint + text label | Pair badge with Vietnamese status copy |
| Approved / positive | `var(--success)` + label | |
| Expand / info | `text-foreground` link style | Not “AI purple” gradient |
| Impact bar | Real segment `var(--success)`; estimated segment muted + pattern | RealEstimatedBar contract |
| Juli reasoning block | `var(--info)` accent | Contextual assistance only |
| Focus | 3px primary ring on Approve/Reject/Expand | |

## Copy keys (authority: dictionary.md + design-context.md)

| UI element | Dictionary key | VI (reference only) |
|------------|----------------|---------------------|
| Sub-tab | `decisions.tab.recommendations` | Đề xuất |
| Card concept | `decisions.recommendation` | Đề xuất — never “AI Action Card” |
| Approve | `decisions.approve` | Phê duyệt |
| Reject | `decisions.reject` | Từ chối |
| Expand | `decisions.expand` | Mở rộng |
| Address form | design-context.md | “bạn” — informal-respectful |

Five-stage headings (DVR-A5): draft Vietnamese per design-context; stage slugs stay English in code (`why`, `analytics`, `inputs`, `preview`, `approve`).

## Five-stage review — section guidance

| Stage | Layout intent | Reference synthesis |
|-------|---------------|---------------------|
| **Why** | One-screen problem + expected outcome; ClarityCard hero | Navan flagged/approved clarity (one sentence problem + consequence) |
| **Analytics** | Embedded evidence links / mini charts; read-only | GA4 + Navattic KPI link pattern — deep-link to Analytics destination |
| **Inputs** | Prefilled editable seller fields | Airwallex metadata grid density, reduced to form fields |
| **Preview** | Summarized action before commit | Airwallex drawer summary block |
| **Approve** | Primary gate CTA + confirm | Klaviyo primary button weight; existing Demo approval modal contract |

## Anti-patterns

- “Độ tin cậy: Cao/…” or FBS executable badges in UI (removed in DVR-A1).
- Backend strings: webhooks, endpoints, feature IDs, tool names.
- Mobbin English review copy (“Publish”, “Pending your approval”) as seller strings.
- In Progress tab/panel changes — explicitly out of scope.

## Downstream notes

- **DVR-A4** blocked on #584; consume this bundle for list layout before five-stage work.
- **DVR-A5** blocked on #587; stage navigation tests in `workflow-*-review-approve-in-progress.test.tsx`.
- Preserve Decision envelope / fixture / #534 read paths — no new ranking engine.
