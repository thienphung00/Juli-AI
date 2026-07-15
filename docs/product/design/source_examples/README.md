# source_examples/

> **Non-authoritative historical evidence.** The files in this folder are
> preserved unchanged for provenance. They may contain retired navigation,
> Home, or action patterns and cannot override the root design authorities,
> `Screens/`, `Flows/`, `Components/`, previews, or the current UI kit.

Verbatim original component source from `apps/dashboard/src` in
`/Users/macos/Juli-AI-v2`, preserved as a record of the implementation inspected
when this package was created. Do not copy product behavior from these files
without reconciling it against the current design hierarchy.

| File | Original path | What it demonstrates |
|---|---|---|
| `button.tsx` | `apps/dashboard/src/components/ui/button.tsx` | Historical shared `Button` primitive |
| `NavBar.tsx` | `apps/dashboard/src/components/NavBar.tsx` | Historical navigation evidence; its tab model is retired |
| `SellerHomeShell.tsx` | `apps/dashboard/src/components/seller-home/SellerHomeShell.tsx` | Historical Home/loading evidence; not the current two-launcher composition |
| `HomeAiRecommendationCard.tsx` | `apps/dashboard/src/components/home/HomeAiRecommendationCard.tsx` | Historical action row; current cards require Phê duyệt/Từ chối/Mở rộng |
| `ReportMetricChart.tsx` | `apps/dashboard/src/components/home/todays-report/ReportMetricChart.tsx` | Historical metric implementation; current KPI/report ownership is Analytics |
| `InProgressDecisionCard.tsx` | `apps/dashboard/src/components/decisions/InProgressDecisionCard.tsx` | Historical lifecycle-state evidence for Đang thực hiện |

These files import from the source repo's own module aliases (`@/lib/...`,
`@/components/...`) and are kept as-is for reference and provenance — they
are **not** meant to run standalone. The runnable, browser-ready current
demonstration lives in `ui_kits/app/` (plain JSX + `colors_and_type.css`, no
build step required). It intentionally does not reproduce retired behavior.

See `context/local-code/Juli-AI-v2.md` for the full evidence note on how
these files were located and why no other files (logos, fonts, build
assets) exist in the source repo to preserve.
