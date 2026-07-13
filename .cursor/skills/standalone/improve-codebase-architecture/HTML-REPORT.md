# HTML report scaffold

Self-contained architecture review report. Write to `$TMPDIR/architecture-review-<timestamp>.html`
(or `%TEMP%` on Windows). **Do not commit** to the repo.

## Document shell

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Architecture Review — {area or date}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
  </script>
  <style>
    /* Editorial diagram helpers — use when Mermaid is too rigid */
    .depth-bar { height: 8px; border-radius: 4px; transition: width 0.3s; }
    .shallow { background: linear-gradient(90deg, #fca5a5 0%, #fecaca 100%); }
    .deep    { background: linear-gradient(90deg, #86efac 0%, #bbf7d0 100%); }
    .seam    { border-left: 3px dashed #6366f1; padding-left: 1rem; }
    .card    { break-inside: avoid; }
  </style>
</head>
<body class="bg-slate-50 text-slate-900 antialiased">
  <!-- content -->
</body>
</html>
```

## Page layout

```
┌─────────────────────────────────────────────────────────┐
│ Header: title, date, area reviewed, CONTEXT.md terms used │
├─────────────────────────────────────────────────────────┤
│ Summary strip: N candidates · top pick named upfront      │
├─────────────────────────────────────────────────────────┤
│ Candidate card 1                                          │
│ Candidate card 2                                          │
│ …                                                         │
├─────────────────────────────────────────────────────────┤
│ Top recommendation (expanded rationale)                 │
└─────────────────────────────────────────────────────────┘
```

Use `max-w-5xl mx-auto px-6 py-10` on the main container.

## Candidate card template

```html
<article class="card bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
  <header class="flex items-start justify-between gap-4 mb-4">
    <h2 class="text-xl font-semibold">{Candidate title — domain term from CONTEXT.md}</h2>
    <span class="shrink-0 px-3 py-1 rounded-full text-sm font-medium
      bg-emerald-100 text-emerald-800">{Strong|Worth exploring|Speculative}</span>
  </header>

  <!-- Optional ADR conflict -->
  <div class="mb-4 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-sm">
    ⚠ Contradicts <strong>ADR-NNN</strong> — worth reopening because …
  </div>

  <dl class="grid gap-3 text-sm mb-6">
    <div><dt class="font-medium text-slate-500">Files</dt><dd class="font-mono text-xs">…</dd></div>
    <div><dt class="font-medium text-slate-500">Problem</dt><dd>…</dd></div>
    <div><dt class="font-medium text-slate-500">Solution</dt><dd>…</dd></div>
    <div><dt class="font-medium text-slate-500">Benefits</dt><dd>locality · leverage · tests …</dd></div>
  </dl>

  <div class="grid md:grid-cols-2 gap-4">
    <figure>
      <figcaption class="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Before</figcaption>
      <!-- diagram -->
    </figure>
    <figure>
      <figcaption class="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">After</figcaption>
      <!-- diagram -->
    </figure>
  </div>
</article>
```

### Recommendation strength badges

| Strength | Tailwind classes |
|----------|------------------|
| Strong | `bg-emerald-100 text-emerald-800` |
| Worth exploring | `bg-sky-100 text-sky-800` |
| Speculative | `bg-slate-100 text-slate-600` |

## Diagram patterns

### When to use Mermaid

Use for graph-shaped relationships: call graphs, import dependencies, sequences.

```html
<pre class="mermaid">
graph LR
  subgraph before["Before — shallow"]
    A[Caller] --> B[Thin wrapper]
    B --> C[Helper]
    B --> D[Helper]
    C --> E[(DB adapter)]
    D --> E
  end
</pre>
```

Sequence for call-site wiring bugs:

```html
<pre class="mermaid">
sequenceDiagram
  participant R as Router
  participant S as Shallow module
  participant H as Extracted pure fn
  R->>S: orchestrate
  S->>H: compute (tested)
  Note over S: bug lives here — untested wiring
</pre>
```

### When to use hand-built CSS/SVG

Use for editorial visuals Mermaid cannot express well:

- **Depth bars** — interface width vs implementation depth (`.depth-bar.shallow` vs `.deep`)
- **Mass diagrams** — box size proportional to complexity behind the seam
- **Cross-sections** — stacked layers showing what leaks through the interface

Example depth comparison:

```html
<div class="space-y-2 p-4 bg-slate-100 rounded-lg">
  <div class="flex items-center gap-2">
    <span class="w-24 text-xs">Interface</span>
    <div class="depth-bar shallow" style="width: 85%"></div>
  </div>
  <div class="flex items-center gap-2">
    <span class="w-24 text-xs">Hidden</span>
    <div class="depth-bar shallow" style="width: 15%"></div>
  </div>
  <p class="text-xs text-slate-500 mt-2">Shallow — interface ≈ implementation</p>
</div>
```

Label seams with `.seam` and indigo dashed borders.

## Top recommendation section

```html
<section class="mt-12 p-6 rounded-xl bg-indigo-50 border border-indigo-200">
  <h2 class="text-lg font-semibold text-indigo-900 mb-2">Top recommendation</h2>
  <p class="text-indigo-800"><strong>{Candidate name}</strong> — {2–3 sentences: leverage,
  test surface win, locality gain, low ADR risk}</p>
</section>
```

## Quality checklist

Before opening the file:

- [ ] Every candidate uses CONTEXT.md domain terms in titles and prose
- [ ] Architecture terms match codebase-design vocabulary exactly
- [ ] Each card has before/after visuals (not prose-only)
- [ ] ADR conflicts are rare, explicit, and justified
- [ ] No proposed interfaces yet — deepening direction only
- [ ] File is self-contained (CDN only, no repo asset links)
- [ ] Absolute path communicated to the user after `open` / `xdg-open` / `start`
