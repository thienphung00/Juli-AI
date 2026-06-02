Exploration Summary
1. /Users/macos/Downloads/figma_design/ — Design assets (91 files)
This is not a folder of static Figma exports (.fig, PNG mockups). It is a Figma Make / code bundle for the Juli AI App: a runnable React + Vite prototype with design docs and a full shadcn-style UI kit.

By category
Category	Files	Summary
Project config
package.json, pnpm-workspace.yaml, vite.config.ts, postcss.config.mjs, index.html
Vite 6, React 18, pnpm workspace
Design documentation
DESIGN_SYSTEM.md, ATTRIBUTIONS.md, README.md, default_shadcn_theme.css
Mobile-first TikTok Shop seller OS; pink primary #ff006e; dark default; Inter typography; 4px grid
Imported guides
src/imports/00_design_system_index.md … 05_responsive_design_guide.md, juli-ai-design-system.md
Color, typography, components, tone, responsive specs
Styles
src/styles/index.css, tailwind.css, theme.css, fonts.css
Tailwind v4 + theme tokens
App shell
src/main.tsx, src/app/App.tsx
Multi-tab mobile app with mock Vietnamese data
Feature screens
OperationsScreen, LivestreamOpsScreen, MarketResearchScreen, AIAssistantScreen, AIScreen
Ops, livestream, market research, AI flows
Domain components
~20 files: TabBar, LivestreamCard, AISummaryHero, TrendingProductCard, UrgentAlert, BottomSheet, SwipeableCards, etc.
Product-specific UI
shadcn/ui primitives
~45 files under src/app/components/ui/
Radix-based: button, card, dialog, sheet, tabs, chart, sidebar, etc.
Figma helper
src/app/components/figma/ImageWithFallback.tsx
Image fallback for exported assets
No raster/vector asset files (.png, .svg, .jpg) were found; visuals use gradients, emojis, and CSS.

Tech in the design bundle
Framework: React 18 + Vite 6
Styling: Tailwind CSS 4 (@tailwindcss/vite)
Components: Radix UI + shadcn-style ui/* (also MUI in package.json but primary pattern is Radix/shadcn)
Motion: motion (Framer Motion successor)
Icons: lucide-react
Charts: recharts
Routing: react-router 7
2. Architecture overview (docs/architecture/map.md)
Juli-AI is a Python/FastAPI backend with Supabase (Postgres + Auth), validation → ETL ingest, and two clients: Next.js web and native SwiftUI iOS.

Core modules (Tier 1)
Module	Role
src/integrations/tiktok
TikTok Shop Partner API (auth, signing, rate limits, resources)
src/services/webhook
Webhook receiver → ETL handoff
src/data
SQLAlchemy models, repos, Alembic
src/auth
Supabase phone-OTP, JWT, TikTok OAuth
src/api
Versioned FastAPI REST (/v1/*)
src/etl
ETL consumer, dedup, DLQ
Feature modules (Tier 2)
src/services/polling — sync workers
src/intelligence/scoring — livestream scoring, sentiment
src/intelligence/forecasting — inventory forecasting
src/recommendations — rule-based product pushes
src/alerts — rules + FCM (Zalo OA shipped)
web — Next.js dashboard
ios — SwiftUI app
Data flow
TikTok API → webhook/polling → ETL → Postgres (Supabase) ← intelligence/recommendations/alerts ← API ← web + ios

Key decisions
Python/FastAPI only (no Node backend)
Supabase for DB + auth
TikTok Shop Official API only in MVP (no scraping)
Planned infra: Railway / Vercel / GitHub Actions (not in repo yet)
3. Top-level /Users/macos/Juli-AI/
Path	Purpose
src/
Python backend (api, auth, data, etl, integrations, services, intelligence, alerts, recommendations)
web/
Next.js web dashboard
ios/
SwiftUI iOS app
tests/
Python unit tests
docs/
Architecture, ADRs, CI, TikTok API docs, handoffs
alembic/
DB migrations
scripts/
CI, validation
artifacts/
Review/validation JSON
.cursor/
Skills, rules
.github/
CI workflows
issues.md, done.md
Work tracking
requirements.txt, alembic.ini
Python deps / migrations
There is no root-level frontend/, app/, or components/ — frontends live in web/ and ios/ only.

4. /Users/macos/Juli-AI/docs/ structure (31 files)
docs/
├── architecture/
│   ├── map.md
│   └── data-sources.md
├── decisions/
│   ├── README.md
│   ├── 001-keep-python-fastapi.md
│   ├── 002-supabase-backend-service.md
│   ├── 003-ai-native-cicd-policy.md
│   ├── 004-etl-kafka-consumer.md
│   └── 005-alerts-module.md
├── ci/
│   ├── quick-reference.md
│   ├── implementation-guide.md
│   └── troubleshooting.md
├── features/
│   └── README.md
├── handoffs/
│   ├── _bootstrap.md
│   ├── parallel-status.md
│   ├── tiktok-mvp-issues-01.md
│   ├── tiktok-mvp-ship-01.md
│   └── tiktok-mvp-ship-02.md
├── tiktok_api/          # 13 API/integration docs
└── tiktok-shop-execution-plan.md
5. Current issues & done items
issues.md (work queue)
Implement now (parallel):

Issue	Slice
#46
iOS: push notifications + live alerts
#47
Web: alerts config + recommendations feed
Blocked on Figma variables (polish after token import; logic can start earlier):

#41 — Web: auth + homepage + orders
#45 — Web: products, inventory, livestreams, creators
#42 — iOS: auth + daily value loop shell
Recently shipped: #40, #43, #32, #36, #38, #39, #44 (and related PRs).

Backend-only done (no Figma revisit): #24–#40, #43–#44 unless new UI is added.

done.md
This file is a Definition of Done checklist for issue #40 (Zalo OA alerts adapter), not a global “completed features” list. It records:

Pytest mapping, review artifact PASS, ruff/mypy, 217 tests
Validation artifact at artifacts/validation/validation-issue-40.json
src/alerts/MODULE.md updated
Frontend N/A for that issue
For the full MVP issue registry, see docs/handoffs/tiktok-mvp-issues-01.md (24 slices #24–#47; most backend/API work Done).

6. Frontend stack & where code lives
Web — /Users/macos/Juli-AI/web/
Aspect	Choice
Framework
Next.js 14 (App Router)
Language
TypeScript
Styling
Tailwind CSS 3.4
Component library
Custom React components (no shadcn/Radix in package.json)
Testing
Jest + Testing Library
Auth pattern
Phone-OTP via API layer (no direct Supabase client in browser)
Layout:

web/src/app/ — routes: /, /login, /orders, /products, /inventory, /livestreams, /creators
web/src/components/ — HomePage, OrdersPage, LoginForm, NavBar, domain pages
web/src/lib/ — api-client, auth-context, format, use-auth-guard
iOS — /Users/macos/Juli-AI/ios/
Aspect	Choice
Framework
SwiftUI (native)
Package
Swift Package Manager (Package.swift)
Structure
App/ views, Sources/JuliKit/ services & view models
Auth
Supabase phone-OTP, JWT in Keychain
Push
Deferred to #46
Design reference (separate repo folder)
/Users/macos/Downloads/figma_design/ is the rich UI prototype (shadcn + motion) to align with production web/ and ios/ after Figma design tokens are imported.

Python src/
Backend only — not frontend despite the src/ name.

Quick reference
Question	Answer
Figma folder contents?
Runnable React/Vite prototype + markdown design system; no .fig/image assets
Architecture?
FastAPI + Supabase + ETL ingest + TikTok integration; web + iOS clients
Frontend locations?
web/ (Next.js), ios/ (SwiftUI)
Web stack?
Next 14, TS, Tailwind 3, custom components
Figma prototype stack?
Vite, React, Tailwind 4, Radix/shadcn UI, motion
What to build next?
#46 (iOS alerts), #47 (web alerts + recommendations); Figma token pass for #41/#45/#42 polish



#UI-only mode

cd /Users/macos/Juli-AI/web && NEXT_PUBLIC_UI_ONLY=1 npm run dev




# Terminal 1 — API with Supabase
export SUPABASE_URL=...
export SUPABASE_ANON_KEY=...
export SUPABASE_JWT_SECRET=...
uvicorn src.api.app:create_app --factory --host 0.0.0.0 --port 8000
# Terminal 2 — web (no UI_ONLY)
cd web && npm run dev