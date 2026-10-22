# Log

Append-only. Newest at the bottom. Format: `## YYYY-MM-DD — who` then bullets.

> Entries before 2026-10-12 (P0–P17, 2026-10-05 to 2026-10-10) are in [`archive/LOG-pre-2026-10-12.md`](archive/LOG-pre-2026-10-12.md) (moved verbatim, P53 / D62).

## 2026-10-14 — orchestrator (Claude Opus) — P32 opened (D42)

- Shopee rejected the ISV profile ("unable to identify the actual service via Test URL").
  Grill with the owner → D42; ACs 32.1–32.11; P32-A (reviewer access, Opus) and P32-B
  (Shopee copy, Sonnet) dispatched in parallel from this commit; P32-C after them.
- Noted: the decisions were first recorded on `main` as ADR-109 (#2134) and GitHub issues
  #2135–#2139 before D2/D4 were noticed; `main`'s ADR-109 collides with this branch's ADR-109
  and is renumbered at merge-back.
- Live demo check: Google + email-OTP sign-in work after hydration (the SSR HTML shows the
  "chưa sẵn sàng" fallback); a new account lands on the P13 sample — the reviewer never saw a
  connected shop.

## 2026-10-14 — P32-A agent (Claude Opus) + orchestrator — reviewer access (AC-32.1–32.8)

- Branch `fasttrack/p32a-reviewer-access` (5e3c1410..ce38297b + this docs commit): contract,
  migration `090_reviewer_accounts`, reviewer claim + gate bound in `get_current_user`
  (allowlist by matched endpoint), Fujiwa pin via alias id + view-as read scope, response mask,
  `POST /v1/reviewer/decisions/{id}/simulate`, ops audit, provisioning CLI, demo password mode on
  `/auth/email`, banner, simulated Duyệt → Thực thi, e2e.
- The agent was cut off twice by network errors (ENOTFOUND); the orchestrator finished: reviewer
  unit tests 27 passed; `fasttrack/check.sh --since 0e80c18b` (docker PG16): migrations PASS at
  090, isolation 12 passed, gitleaks PASS, ruff PASS (44 files), pytest 543 passed / 1 failed —
  the failure is pre-existing (DEBT, fails on the base too).
- Owner steps: `REVIEWER_SHOP_ID` (+ optional `REVIEWER_MASK_TERMS`) in the API env; after deploy
  run the provisioning CLI on the VPS (contract §8).

## 2026-10-14 — P32-B agent (Claude Sonnet) — Shopee status copy (AC-32.9)

- Landing hero: new line "TikTok Shop · Shopee (đang tích hợp qua Shopee Open Platform)" under
  the unchanged TikTok badge. `/privacy`: removed the "in development" sentence (VN + EN), added
  section 4A (VN + EN: data, purpose, retention mirror, Shopee Open Platform Data Protection
  Policy, write-back only after approval, effective when a Shopee shop is connected); dated
  14/10/2026. `/terms`: Shopee paragraph in section 4 (VN + English note), "TikTok Shop hoặc
  Shopee" in the lawful-use clause. Tests extended; privacy wording avoids a second "never
  buyer data" match so `privacy-staff-access` still pins exactly the D25.6 sentence.
- Gates (Node 20.20.2): landing lint, type-check, vitest 63/63, `next build` OK. Under Node 26
  the localStorage tests fail (pre-existing, environment only).
- Branch not merged, not deployed. (Orchestrator correction: `fasttrack-deploy.yml` does build and
  ship the landing artifact since 2026-10-08 — DEBT repaid; the README sentence saying landing SHAs
  are refused is stale and is fixed in the P32 integration commit.)

## 2026-10-15 — orchestrator (Claude Opus) — P32 integrated

- Merged `fasttrack/p32a-reviewer-access` (d28161bd) and `fasttrack/p32b-shopee-copy` (3a582b9f)
  into `fasttrack/optimize-product` (owner approved in the P33 grill); fasttrack doc conflicts
  resolved by keeping both sides. Repaid the p10a time bomb (card surfaced now in the test);
  README landing-lane sentence corrected (landing ships since 2026-10-08).
- `fasttrack/check.sh --since 0e80c18b` (docker PG16): 5/5 PASS twice (migrations at 090,
  isolation 12, gitleaks, ruff 44 files, pytest 544); one earlier run hit a flaky isolation seed
  (DEBT). Not deployed — owner tags.

## 2026-10-15 — P33-A agent (Claude Opus) — technical SEO foundation (AC-33.1–33.4)

- Branch `fasttrack/p33a-seo-foundation` (875fb83b..HEAD, pushed; not merged, not deployed).
- **Helpers** `apps/landing/src/lib/seo/` (API + how-to in its README): route registry split by
  owner (`routes/core.ts`, `product.ts`, `capabilities.ts` (P33-C), `blog.ts` (P33-D)) feeding
  `sitemap.ts` with lastmod; `buildMetadata(path, opts?)` (absolute title, description, absolute
  self canonical, OG vi_VN 1200×630 + Twitter); `<JsonLd data>` + builders (Organization with
  legal name / taxID / PostalAddress / ContactPoint lienhe@app-juli.com, WebSite — both on every
  page from the layout — BreadcrumbList, SoftwareApplication + Offer 500000 VND, FAQPage,
  Article, VideoObject). No sameAs, no hreflang. `src/lib/media.ts` (`LOGO_WORDMARK`,
  `HERO_VIDEO`, `HERO_VIDEO_SCHEMA`), `<Picture>` (AVIF/WebP + width/height), `SiteLogo`,
  `scripts/media.py` (optimize / brand: OG card, favicon + icons, logo WebP, poster AVIF/WebP).
  Home canonical is the bare origin (Next strips the slash).
- **Pages**: home, about, contact, privacy, terms migrated; `/product` content moved verbatim to
  `/san-pham` (Breadcrumb + SoftwareApplication + FAQPage for its rendered FAQ); `/product` 301
  (`RENAMED_PATHS`, `statusCode: 301`). Nav, about, 404 link `/san-pham`.
- **Demo/ops noindex**: X-Robots-Tag from next.config headers() + middleware on every host,
  layout robots meta, `app/robots.ts` Allow: / (no sitemap). `@juli/tiktok-events/pixel-id`
  subpath added so the landing consent banner no longer bundles the pixel snippet.
- **PageSpeed**: mockup contrast fixed with landing-local `color-mix` tokens (theme `tokens.css`
  is byte-pinned by #1314, so not touched); logo 50 KB PNG → 6 KB WebP with width/height;
  poster → WebP; favicon/icon/apple-icon; pixel tracking via next/dynamic after consent;
  explicit modern browserslist; cache headers for `/media` (immutable), `/og`, `/videos`.
  `experimental.inlineCss` measured and dropped (TBT ×3). Lighthouse A/B numbers in AC-33.4:
  A11y and BP 1.00, page 282 → 229 KB, Perf/LCP target not demonstrated on this loaded host.
- **Check for B/C/D**: `pnpm --filter @juli/landing build && pnpm --filter @juli/landing check:seo`
  (one h1, no skipped level, title/description/canonical = registry and unique, OG/Twitter,
  JSON-LD parses, Org/WebSite everywhere, Breadcrumb on inner pages, FAQ visible, no sameAs,
  no hreflang, not noindex).
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 9 files 75 passed,
  `next build` OK, `check:seo` 7/7; tiktok-events vitest 89 passed; demo lint 0 errors (7
  pre-existing warnings), type-check clean, vitest 149 files 1903 passed / 5 failed in one run
  under load avg ~25 (timeouts + `no-shop-sample` race; passes 3/3 alone and on the base; DEBT),
  `pnpm build:demo --force` OK (example Supabase env); nginx/landing/demo packaging pytest 160
  passed; `fasttrack/check.sh --since e1c6d68f` (docker PG16): 5/5 PASS.
- **Owner steps** (after deploy): (1) Cloudflare → demo.app-juli.com: keep the managed
  robots.txt / AI Crawl Control from adding any `Disallow` for search crawlers (today it only
  prepends content-signal comments; origin now serves `User-Agent: * / Allow: /`); check
  `curl -sI https://demo.app-juli.com/ | grep -i x-robots` shows `noindex, nofollow` (Cloudflare
  must not strip it). (2) Cloudflare Browser Cache TTL "Respect existing headers" for
  app-juli.com (today `/videos/*.jpg` shows `max-age=14400`, a CF override of Next's
  `max-age=0`; with the new longer origin TTLs CF keeps the origin value). (3) Search Console:
  submit `https://app-juli.com/sitemap.xml`; for demo.app-juli.com use Removals only if old URLs
  linger after the noindex is crawled. (4) No nginx change needed.
- Next: P33-B / C / D branch from this branch's head.

## 2026-10-15 — P33-B agent (Claude Opus) — homepage + `/san-pham` overview (AC-33.5, AC-33.6)

- Branch `fasttrack/p33b-homepage` from P33-A f55809fd (2f16f2eb..HEAD, pushed; not merged, not
  deployed).
- **Homepage** (`app/page.tsx`, `components/home/`): H1 "Juli AI — trợ lý AI vận hành cho nhà bán
  TikTok Shop: phân tích, đề xuất, thực thi sau khi bạn duyệt, đo GMV"; marketplace strip (TikTok
  Shop live via Open API · Shopee "đang tích hợp qua Shopee Open Platform", never live), problem,
  Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường, three capability blocks linking
  `/san-pham/{phan-tich-shop,de-xuat-va-thuc-thi,do-luong-gmv}`, data safety, audiences,
  transparency (measurement method, sample-data label, company + MST + address), "từ 500K/tháng
  · dùng thử 3 tháng", 7-question FAQ + FAQPage, final CTA. CTAs: "Dùng thử 3 tháng" (LOGIN_URL)
  + "Xem demo" (DEMO_URL); all five still tracked by the pixel.
- **Hero video**: new poster `public/media/home-demo-poster-v1-{640,1280}.{avif,webp}` (video frame
  t=19 s, GMV formula, no figure — the old card said "+1–3% GMV"); `<video preload="none">`
  mounted only on click; VideoObject.
- **Claims**: "+1–3% GMV mỗi tháng" and "~1,7 giờ/ngày" had no source beyond CONTEXT.md's
  2026-10-09 hero framing → dropped (D43.3). Also dropped: "ROI cao", the comparison table, and
  copy promising things Juli does not do (tạo đơn nhập, đồng bộ tồn kho, tạo mã giảm giá on
  `/san-pham`, alerts via Zalo). Scope now per D13 / D24.5. The video still shows figures →
  captioned "minh hoạ" + DEBT.
- **`/san-pham`** rewritten (~1,680 words): what Juli is, the loop, capabilities, does / does
  not do, integrations, data control, audiences, pricing (`#bang-gia`), FAQ, CTA; breadcrumb
  (visible + JSON-LD), SoftwareApplication + Offer, FAQPage. Registry titles/descriptions for `/`
  and `/san-pham` updated.
- **Header/footer**: header Sản phẩm · Blog · Giới thiệu · Liên hệ + CSS-only mobile menu;
  footer columns Sản phẩm (overview, 3 capability pages, Kết nối TikTok Shop) / Công ty / Pháp lý,
  © company name, no social links. `SITE_PAGES` gained `/blog`; `PRODUCT_PAGES`,
  `FOOTER_PRODUCT_LINKS` in `lib/site.ts`.
- Deleted the old hero/steps/comparison/features/mockup/trial components and their CSS
  (`lp-hero*`, `lp-steps*`, `lp-comparison*`, `lp-features*`, `lp-mockup*`, `lp-curiosity*`);
  new classes `lp-home-*` in `globals.css` (replaces that block). `lp-page-*` untouched for C/D.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 9 files 79 passed, `next
  build` OK, `check:seo` 7/7; no horizontal overflow at 390 px (Playwright) on `/`, `/san-pham`,
  `/about`; `fasttrack/check.sh --since f55809fd`: 5/5 PASS. Lighthouse not run (loaded host).
- **Integration note**: the new links 404 until P33-C/D merge; merge B with C and D.
- **Owner questions**: re-cut or replace the hero video (figures + a discount run Juli does not
  do); confirm "Dùng thử 3 tháng" is free (landing said so; /terms §5 is silent); add an in-app
  disconnect.

## 2026-10-15 — P33-B agent (Claude Opus) — owner's D43 additions (trial, disconnect, video, poster)

- Recorded **D43 additions** in DECISIONS (video stays; free 3-month trial via `/dang-ky` (P33-F);
  no disconnect button, the team disconnects on request; keep old poster files).
- **Landing** (2df45c3e, 7c7a6b22): `SIGNUP_URL` = `/dang-ky` (env `NEXT_PUBLIC_SIGNUP_URL`),
  `TRIAL_CTA_LABEL` "Dùng thử miễn phí 3 tháng" on home hero / pricing / final and `/san-pham`
  hero / pricing card / final; `TikTokTracking` now also fires StartDemo for clicks to
  `SIGNUP_URL` (content_name = testid). `/terms` §5: "Tài khoản mới được dùng thử miễn phí 3
  tháng kể từ ngày đăng ký, không cần thẻ thanh toán. Sau thời gian dùng thử, phí dịch vụ Juli là
  500.000đ/tháng." (dated 15/10/2026; **owner's legal review**). Homepage / FAQ / `/san-pham`
  disconnect copy: contact Juli by email or `/contact`, the Juli team disconnects. `/san-pham`
  FAQ +2 (trial, disconnect).
- **Demo** (2e37f3c0): `DemoLanding` at `/?dang-ky=dung-thu` forces the doors and the sign-in
  door reads "Đăng ký dùng thử miễn phí 3 tháng" (eyebrow "Tài khoản mới"; body + existing-account
  line); buttons and the P32-A partner door unchanged. "Không cần thẻ thanh toán" verified: no
  payment integration (Ops "Thanh toán · tự động, sắp có" is disabled; terms granted by contract).
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 81/81, build OK, `check:seo`
  7/7; demo lint 0 errors (7 pre-existing warnings), type-check clean, vitest 1909/1912 in the full
  run at load avg ~35 (3 load flakes in `quyet-dinh-p10`, `ops-pages`; 70/70 in isolation with
  `demo-landing`), `pnpm build:demo --force` OK (example Supabase env); `fasttrack/check.sh
  --since f55809fd` 5/5 PASS.
- `/dang-ky` 404s until P33-F integrates (DEBT); `check:seo` does not check links, so no allow-list.
## 2026-10-15 — P33-C capability pages (agent: Claude Opus, branch `fasttrack/p33c-capabilities`)
- **Pages** (Vietnamese, D43.1/D43.4): `/san-pham/phan-tich-shop`, `/san-pham/de-xuat-va-thuc-thi`,
  `/san-pham/do-luong-gmv` (parent `/san-pham`, SoftwareApplication + Offer) and
  `/ket-noi/tiktok-shop` (parent home, no SoftwareApplication). Shared frame
  `src/components/product/capability-page.tsx` (+ CSS module, tokens only): breadcrumb, one H1,
  ToC, H2 sections each with one `<Picture>` + "Dữ liệu mẫu" caption, FAQ rendered = FAQPage,
  related links, "Dùng thử 3 tháng" (LOGIN_URL) / "Xem demo" (DEMO_URL). Routes in
  `routes/capabilities.ts`.
- **Screenshots**: 24 crops (`public/media/cap-*-v1-{640,1280}.{avif,webp}`,
  `components/product/screens.ts`) from the demo's signed-out sample "Cửa hàng Mẫu Hoa Mai"
  (Phân tích, Quyết định: Đề xuất / Đang thực hiện / Đo lường, reject / undo dialogs, confirm step)
  plus connect-shop and the P17 onboarding strip rendered with mocked API responses. The sales-demo
  stills were not used (marketing frames with promised uplift numbers).
- **Accuracy**: facts from D13/D14/D22/D24/D26/D29–D32/D39/D41, ADR-106/108, `/privacy`, and code
  (scope list, revert rules, card limits in `decision_emission.py`, onboarding labels). Left out
  on purpose: product attributes as an executed field, exact OAuth scope names, a seller
  disconnect button, daily email / Zalo reports, cross-shop learned effects or any result number,
  Liên kết in Phân tích, time estimates beyond what the app shows.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 91 passed (new
  `capability-pages.test.tsx` 16), build OK, `check:seo` 11/11; `check.sh --since f55809fd` 5/5.
- Next: P33 integration merges B/C/D; owner confirms the real-shop write wording (DEBT).
## 2026-10-15 — P33-D agent (Claude Opus) — blog + three pillar drafts (AC-33.8)
- Branch `fasttrack/p33d-blog` from P33-A f55809fd. Commits 7ef53a7a (infra), dad5460c (drafts),
  efb19ca7 (READMEs) + this docs commit.
- **Blog architecture**: posts are typed TS — metadata in `apps/landing/src/content/blog/posts.ts`
  (one `status` field per post), bodies in `content/blog/bodies/<slug>.ts` as a small Markdown
  subset parsed and rendered on the server (`src/components/blog/markdown.tsx`; no MDX, no new
  dependency, no client JS for content). `/blog` index + `/blog/[slug]` (SSG,
  `dynamicParams = false`), blog CSS in `src/app/blog/blog.css` (kept out of `globals.css` to
  avoid conflicts with P33-B/C). Routes derived from `posts.ts` in `src/lib/seo/routes/blog.ts`.
- **Draft mechanism** (touches P33-A helpers, small): `SiteRoute.noindex`; `metadataForRoute`
  adds robots `noindex, follow`; `sitemapEntries()` drops noindex routes; `check:seo` asserts a
  noindex route IS noindex and that no indexable page links one. A published post renders links
  to drafts as plain text and hides them from "Bài viết liên quan". Drafts are listed on `/blog`
  only under `next dev`.
- **Drafts** (Vietnamese, H1 → H2 → H3, sources section, FAQ): metrics 4,882 words, product card
  4,579, tools 3,700 (space-separated tokens). TikTok facts from Academy VN pages cited by title;
  method from ADR-106/108; worked examples labelled "số giả định"; no customer data (Fujiwa
  numbers deliberately not used). Tool facts from vendors' own sites, checked 2026-10-15 via a
  Sonnet research sub-agent (WebFetch summaries); no third-party prices quoted.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 98 passed (blog 23),
  `next build` OK, `check:seo` 11/11 (also 11/11 with one post temporarily flipped to published:
  it entered the sitemap, its links to drafts were unlinked); `fasttrack/check.sh --since
  f55809fd`: 5/5 PASS.
- **Owner**: approve each post by flipping `status` to `"published"` (README in
  `apps/landing/src/content/blog/`); re-check the tool facts flagged in DEBT before publishing
  post 3. After integration, P33-B's header/footer link `/blog`; P33-C's four pages make the
  posts' product links resolve (the blog test allow-lists them until then).
## 2026-10-15 — orchestrator (Claude Opus) — P33-E Search Console scripts
- Read the Search Console API guides (overview, limits, prereqs, authorizing, performance, batch,
  search analytics, all-your-data) and reference (searchanalytics.query, sitemaps, sites,
  urlInspection.index.inspect + UrlInspectionResult, errors). Key facts: OAuth 2.0 only;
  Removals is UI-only (no API), Indexing API is JobPosting / livestream only; URL Inspection
  2,000 / day / site and reports BLOCKED_BY_META_TAG vs BLOCKED_BY_HTTP_HEADER; Search Analytics
  final after 2-3 days, 25k rows / page, page×query grouping is the most expensive.
- `scripts/seo/` written (see AC-33.10). Pitfall found: `RobotFileParser.read()` sends
  `Python-urllib`, Cloudflare answers 403 and the parser turns that into "disallow all" — the
  live check fetches robots.txt with its own UA.
- Baseline (production, before P33-A): 10 / 14 URLs failing.
- 2026-10-15 follow-up: the OAuth token now also asks `openid email` so `gsc_sitemaps --sites`
  names the Google account (an account without the property silently got `{}`). Owner moved the
  property to the company account: `thien.phung@app-juli.com` is siteOwner of
  `sc-domain:app-juli.com` (a Domain property also covers demo. / ops.; no separate property).
- First real run: sitemap not submitted under this account; URL Inspection — `/`, `/privacy`,
  `/terms` indexed; `/product`, `/about`, `/contact` unknown to Google; **demo `/`, `/decisions`,
  `/analytics` indexed** (crawled 2026-08-20..10-02); ops unknown (Access). Search Analytics: ~1
  click / 5 impressions a week, data through 2026-10-10.
## 2026-10-15 — P33-F agent (Claude Opus) — free-trial sign-up (AC-33.11)
- **Branch** `fasttrack/p33f-trial-signup`, cut from P33-A `f55809fd`; siblings B/C/D untouched.
- **Landing**: `/dang-ky` (registered, indexable; one H1, value list, form) and
  `/dang-ky/cam-on` (registered `noindex: true`, out of the sitemap). To register a noindex route
  the branch takes **P33-D's noindex plumbing verbatim** (`git checkout fasttrack/p33d-blog --` on
  types.ts, metadata.ts, lib/seo/sitemap.ts, app/sitemap.ts, lib/seo/index.ts, seo.test.tsx,
  built-site.check.ts — byte-identical, so the integration merge of those files is clean). New
  registry file `routes/signup.ts`. Form: `components/signup/*` (CSS module, no globals.css edit:
  P33-B rewrote it). No-JS: `POST /dang-ky/gui` → 303 to the thank-you page or
  `/dang-ky#loi-…` (`:target` notice). JS: fetch + inline Vietnamese errors (validate.ts twins the
  API rules). The relay forwards `X-Real-IP` as `X-Juli-Client-Ip` with `TRIAL_SIGNUP_RELAY_KEY`,
  refuses foreign `Origin`. CompleteRegistration fires on the thank-you page only when the form set
  a sessionStorage flag AND analytics consent is granted (lazy import of the pixel package).
  `/privacy` VN §2 + EN §2 gain a "Đăng ký dùng thử" paragraph (what, why, 12-month retention,
  deletion on request in 30 days); effective date 15/10/2026.
- **Backend**: migration `091_trial_signups` (ops_only; deferred 074 re-parented, pins moved),
  `services/trial_signups.py`, public `POST /v1/trial-signups` (threat-model allowlist + surface
  inventory regenerated), `GET/PATCH /v1/ops/trial-signups` (Vận hành+, audited, NOT masked —
  route class keeps the 503 on a missing juli_ops grant). Rate limits are counted from the table.
- **Ops UI** (`apps/demo`): `/ops/dang-ky-dung-thu`, nav item after Thời hạn (ops-d27 nav
  assertion updated), audit sentence "Đăng ký dùng thử: Mới → Đã liên hệ".
- **Docs**: D43 additions P33-F (PROPOSED: Vận hành-only + unmasked, 12-month retention, relay
  key), contract p16-ops §10, runbook env rows, api/frontend env templates, DEBT section.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 107 passed, build OK
  (`/dang-ky` static, `/dang-ky/gui` dynamic), `check:seo` 9/9 (cam-on asserted noindex); demo lint
  0 errors (7 pre-existing warnings), type-check clean, vitest 150 files 1914 passed after the nav
  assertion update, build OK (example Supabase env); backend `test_trial_signups.py` 38 passed,
  PG16 `test_trial_signups_two_tenant.py` + `test_ops_console_db.py` 31 passed;
  `fasttrack/check.sh --since f55809fd` 5/5 PASS. Smoke: `next start` + fake API — no-JS post 303
  → `/dang-ky/cam-on`, invalid → `/dang-ky#loi-du-lieu`, relay key + client IP forwarded.
- **Full backend unit suite** (SQLite, no DB): after fixing the invariants this branch tripped
  (route-auth allowlist, users.phone reviewed list, reviewer sweep `{signup_id}`, import
  boundaries, ratchet suppression/exports) the remaining failures are all on the base f55809fd
  too: `test_agent_workflow_task_wiring` (7), `test_cross_tenant_probe` (1, needs a DB URL),
  `test_destructive_migration_isolation` (fasttrack-deploy.yml), `test_import_boundaries` (6
  grandfathered ops.py deep imports), `test_ratchets` (branch-wide baseline drift),
  `test_test_quality` (corpus count drift). Not touched here.
- **Owner**: set `TRIAL_SIGNUP_NOTIFY_TO`, `TRIAL_SIGNUP_IP_SALT`, `TRIAL_SIGNUP_RELAY_KEY` in
  `juli/api/production`, the same relay key in `juli/frontend/production`, and `OPS_SMTP_*` if not
  yet set; confirm the PROPOSED items. No nginx change.
- Next: integration with P33-B/C/D (expect doc-file conflicts in ACCEPTANCE/PROGRESS/LOG/DEBT/
  DECISIONS only), then deploy.

## 2026-10-15 — orchestrator (Claude Opus) — P33 integrated (A–F)

- Merged `fasttrack/p33a-seo-foundation`, `p33b-homepage`, `p33c-capabilities`, `p33d-blog`,
  `p33e-gsc-monitor`, `p33f-trial-signup` into `fasttrack/optimize-product` (owner: "deploy website
  ngay"); fasttrack doc conflicts resolved by union (ticked rows win). Integration fixes 8e0f66ee:
  blog test no longer allow-lists the P33-C pages; `/ket-noi/tiktok-shop` disconnect copy = contact
  Juli (owner decision 3).
- Gates (Node 20.20.2): landing lint / type-check / vitest 152 / build / check:seo PASS; demo lint /
  type-check / build PASS, vitest 1917 / 1918 (one load-sensitive test, passes alone — DEBT);
  `check.sh --since 7486edf1` 5/5 (migrations at `091_trial_signups`, pytest 398).
- Owner decision 2026-10-15: deploy now; real-shop writes (P5) must ship before real customers are
  onboarded (the trial form routes every new seller through the team).

## 2026-10-15 — P32-D agent (Claude Opus) — reviewer on the sample shop (D42 amendment)

- Owner decision 2026-10-15 amends D42.3: the Shopee rejection was about the product page and the
  trial sign-up, not the data, so the partner reviewer sees the sample shop ("Cửa hàng Mẫu Hoa Mai")
  instead of Fujiwa; `REVIEWER_SHOP_ID` stays unset in production. Branch
  `fasttrack/p32d-reviewer-sample` from f3c84b55.
- Backend: the gate no longer answers 503 when the pin is unset. `ReviewerContext.shop_id` /
  `alias_id` may be None: `/v1/reviewer/me` → `shop: null`, `/v1/shops` → `[]`,
  `enter_reviewer_shop` → 403 `shop` (every shop-scoped route, `simulate` included). Allowlist,
  write barrier, account-state checks (expired / revoked / unknown → 403) unchanged; refused-write
  audit rows carry `shop_id = NULL`. Pin set → unchanged behaviour, unchanged tests.
- Demo: `shop: null` → sign-in stores no active shop and `sample: true` in the reviewer record →
  P13's no-shop door on every page (no shop request), banner `reviewer.banner_sample` (dictionary),
  no-shop connect strip hidden as before. `SampleQuyetDinh` opens the reviewer's simulation dialog
  (split out of `ReviewerSimulation` as `simulation-dialog.tsx`, so the sample module graph stays
  request-free) over `lib/reviewer/sample-simulation.ts`, an in-memory port of the API simulation.
  A stored stale shop is cleared (and the page reloaded) if `/me` later says `shop: null`.
- Tests: backend `test_no_pin_reviewer_gets_sample_mode`, `test_no_pin_still_refuses_expired_and_revoked`
  (replace the old 503 test); the every-route no-write sweep is parametrised over both modes.
  Demo `reviewer-sample-mode.test.tsx` (real `DemoShell` + `DecisionsPageClient`: banner, no strip,
  simulated execute, the only request is `GET /v1/reviewer/me`).
- Gates (Node 20.20.2): demo lint 0 errors (7 pre-existing warnings), type-check clean, vitest
  151 files / 1923 passed, build OK (example Supabase env); reviewer pytest 32 passed (PG
  integration included via check.sh); `check.sh --since f3c84b55` 5/5 PASS.
- Owner: nothing to set for the sample-shop reviewer (leave `REVIEWER_SHOP_ID` unset); still
  provision `shopee-review@app-juli.com` with the CLI after deploy (contract §8.3). DEBT: no
  Playwright e2e for sample mode.

## 2026-10-15 — P32-E agent (Claude Opus) — every feature simulated for the reviewer (D42 amendment 2)

- Owner decision 2026-10-15 (D42 amendment 2): Shopee wants "all features enabled for Shopee
  testing"; the sample-shop reviewer had only Duyệt. Branch `fasttrack/p32e-reviewer-all-features`
  from 9d6352b3 (deployed).
- Demo only, no backend change: `DemoShell` wraps only the pinned reviewer in the read-only
  provider. Sample mode runs every write on `lib/reviewer/sample-store.ts` (the P11 in-memory store,
  one per tab, shared by Quyết định and `/settings`): Từ chối, Duyệt → Thực thi → "Theo dõi lượt
  chạy (mô phỏng) ›" into the sample run (consent edits, photo, Seller Center, content drafts,
  Hoàn tác), Đo lường day-7 / day-14 "tua nhanh" (`simulateMeasurement`), Quy tắc (P14-F fields
  editable too), "Phân tích video" (file never read: canned P15 analysis). `SimulatedLabel`
  prints "Mô phỏng · không gửi tới TikTok" / "Mô phỏng · không lưu" for the sample reviewer only;
  the banner gets "Đặt lại dữ liệu mẫu". Connect / invites / ops stay hidden.
- Tests: `reviewer-all-features.test.tsx` (full session through the real shell — the only request
  is `GET /v1/reviewer/me`; labels absent for the signed-out sample; pinned reviewer unchanged);
  `reviewer-sample-mode.test.tsx` updated (Từ chối enabled).
- Gates (Node 20.20.2): `pnpm install --frozen-lockfile` OK; demo lint 0 errors (7 pre-existing
  warnings), type-check clean, vitest 152 files / 1926 passed (a later re-run: 1925 / 1926, the
  load-sensitive `ops-pages.test.tsx` timeout — passes 3 / 3 alone, DEBT); `build:demo --force` OK
  (example Supabase env); `check.sh --since 9d6352b3` 5/5 PASS. Landing untouched. Docs: DECISIONS D42 amendment
  2, contract header + §4 + §6, dictionary `reviewer.*`, MODULE.md, Services Information steps 6–9,
  ACCEPTANCE AC-32.12, PROGRESS P32-E, DEBT.
- Next: orchestrator merges, deploys, resubmits to Shopee with the updated Services Information.


## 2026-10-15 — P34-A agent (Claude Opus) — UI foundation for the public redesign (D44, AC-34.1)

- Branch `fasttrack/p34a-ui-foundation` from 64f7f913. Commits 3380f3cf … (see `git log 64f7f913..`).
- **Font**: Be Vietnam Pro 400/500/600/700 self-hosted with `next/font/local` (`apps/landing/src/app/fonts.ts`);
  one woff2 per weight (~30 KB) holding Google's Latin + Vietnamese unicode ranges, subset with
  fonttools from the upstream OFL TTFs (licence `src/app/fonts/OFL.txt`). No build-time fetch, so
  `build-release-artifact.sh` / `fasttrack-deploy.yml` need nothing new. `display: swap` +
  metric-matched Arial fallback (no CLS). `--juli-font-sans` is re-pointed to it in the landing, so
  the `@juli/ui` buttons and `html` use it too. The landing used to name Inter and never load it.
- **Tokens**: `apps/landing/src/styles/tokens.css` (`--lp-*`: colour incl. status pairs, dark band and
  blog category tints; responsive type scale D44.1; 4 px spacing + section rhythm; containers 1200/720;
  radii 10–24; frame/hero/float shadows). The only landing file allowed raw colours
  (`design-tokens.test.ts` allowlists it). Contrast measured: every text pair ≥ 4.5:1 (list in the
  file header); `--lp-pink` is accent-only (2.75:1). `packages/theme/tokens.css` untouched.
- **Components** `apps/landing/src/components/ui/` (barrel `index.ts`, styles `ui.css`, docs `README.md`
  with props, tokens and a recipe per mockup): SiteHeader (active state, `<details>` mobile menu,
  `signup` variant), SiteFooter, LinkButton/Button/TextLink, Section/Container/Eyebrow/Heading/
  SectionIntro/Card/CheckList, Shot/ShotFrame (chrome bar, backdrop, "Dữ liệu mẫu", mobile crop via
  `<picture media>` with its own width/height, top crop), FeatureRow, StatusPill, StepList
  (`LOOP_STEPS`), FunnelDiagram, FaqList (optional FAQPage JSON-LD), TocNav + `.ui-toc-layout`,
  Breadcrumb, Icon (12 line icons), BirdGlyph/BrandMark. `Picture` gained `mobileVariants`.
- **Assets** (`scripts/media.py glyph`, `mobile-crops`): bird glyph 64/96 AVIF+WebP; 18 mobile crops
  `cap-*-m-v1-*` (+ `*_MOBILE` in `components/product/screens.ts`), eyeballed at 390. Six shots with
  large text need none.
- **Migration**: every page now renders `SiteHeader`/`SiteFooter` (`/dang-ky` uses the signup
  header); old `landing-header.tsx`, `site-footer.tsx`, `site-logo.tsx`, `LOGO_WORDMARK` and the
  `lp-header*`/`lp-footer*`/`lp-logo` CSS removed (globals.css 1,077 → 844 lines). Header CTA changed
  per mockup: `header-demo-cta` → `header-login-link` (Demo) + `header-trial-cta` (/dang-ky); tests
  (cta, tracking: 7 tracked CTAs, sections, info, legal) updated. Page bodies untouched (B–E).
- **Gates** (Node 20.20.2): `pnpm install --frozen-lockfile` OK; landing lint 0 problems, type-check
  clean, vitest 13 files / 178 passed, `next build` OK (all pages static), `check:seo` 17/17;
  Playwright on the production build: `/`, `/san-pham`, `/dang-ky` at 1440 and 390, no horizontal
  overflow, computed font Be Vietnam Pro; header menu opened at 390; a throwaway preview page of every
  component at both widths (not committed). Screenshots: `fasttrack/design/p34/evidence/p34a/`.
  `check.sh --since 64f7f913` 5/5 PASS.
- For B–E: read `apps/landing/src/components/ui/README.md`. Next: B–E build pages on this branch's
  merge; orchestrator merges P34-A first.

## 2026-10-15 — P34-B agent (Claude Opus) — homepage to the D44 mockups (AC-34.2)

- Branch `fasttrack/p34b-home` from `fasttrack/p34a-ui-foundation` @ c95231e0 (see `git log c95231e0..`).
- **Built** (`app/page.tsx`, `components/home/{home-sections.tsx,home.module.css,hero-video.tsx,home-content.ts}`),
  section by section from `Main.dc.html` with the P34-A components: hero (badge eyebrow, H1, lead,
  `hero-trial-cta` → `SIGNUP_URL`, "Xem video 1 phút", note, `ShotFrame` pair `cap-dx-the` 7:5 +
  floating `cap-pt-pheu`, bird + dashed flight path) · marketplace strip (`StatusPill` live /
  integrating) · `StepList` loop · 3 `FeatureRow`s (cap-pt-luong + xep-hang stacked, cap-dx-the 3:2
  reversed, cap-dl-tang-them; mobile crops where they exist) · 4 data-safety `Card`s with `Icon` ·
  audiences · transparency card + company `dl` · dark pricing band (on-dark CTAs + 500.000đ card) ·
  FAQ split with `FaqList` (FAQPage JSON-LD only from the page) · header/footer as before.
  HomeMobile: hero shot on its backdrop with "Dữ liệu mẫu", no flourish/float; strip as a bordered
  card; stacked full-width CTAs; StepList rows.
- **Video** (D43.6 kept): "Xem video 1 phút" is a client `<button>` opening a modal `<dialog>`; the
  `<video preload="none" autoplay controls>` mounts on click and unmounts on close; the caption "Số
  liệu trong video là minh hoạ" sits under it. VideoObject schema unchanged.
- **Deviations from the mockup, on purpose**: (1) "Kết nối chính thức" card says sellers authorise on
  TikTok Shop's page, not "Partner Center" (that is the developer console; the old test forbids it).
  (2) Cap2 gets the D13/D24.5 bullets (Juli executes title/description/attributes; cover only from
  the seller's photo; price + promotions by the seller; video/LIVE scripted). (3) FAQ keeps the six
  sourced `HOME_FAQ` items + "Juli đo hiệu quả…" (7, not the mockup's 6 shortened questions).
  (4) Hero keeps the consent line (Điều khoản / Chính sách, `hero-consent-note`, TikTok review) and
  turns "Demo dùng dữ liệu mẫu" into a "Xem demo" link (`hero-demo-cta`). (5) Safety lead adds "not
  sold" + the privacy link (the dropped "Không bán dữ liệu" card). (6) Audiences keep the sourced
  longer bodies. (7) The old "GMV giảm, nhưng hụt ở đâu?" problem section and final CTA band are
  gone (not in the mockup; the dark band is the final CTA).
- **Tests changed intentionally**: `sections.test.tsx` (new H1 + H2 order, landmarks, StatusPill
  status, screenshots alt "(dữ liệu mẫu)" + sized + LCP priority, D13 strings, no `%`, company `dl`
  with mailto, FAQ question + answer shown, exactly one FAQPage, video dialog open/close),
  `cta.test.tsx` (2 trial CTAs; price stated as 500.000đ/tháng, no "500K", no table),
  `tiktok-tracking.test.tsx` (6 tracked CTAs). Old home-only `lp-home-*` CSS removed from
  `globals.css` (26 rules); rules `/san-pham` still uses stay.
- **Gates** (Node 20.20.2): `pnpm install --frozen-lockfile` OK; landing lint 0, type-check clean,
  vitest 13 files / 179 passed, `next build` OK, `check:seo` 17/17. Playwright on the production
  build: `/` at 1440 (6,664 px tall) and 390, `scrollWidth == clientWidth` at both, every image
  loaded; dialog opened at 1440. Screenshots `fasttrack/design/p34/evidence/p34b/home-{1440,390}-{top,full}.webp`,
  `home-1440-video.webp`.
  `PYTHON=… fasttrack/check.sh --since c95231e0` 5/5 PASS (migrations, isolation 12 passed, gitleaks,
  ruff and pytest n/a — no Python changed).
- Next: orchestrator merges P34-A, then this branch; owner to confirm the "500.000đ" price wording (DEBT).
## 2026-10-15 — P34-C agent (Claude Opus) — product pages to the approved mockup (D44, AC-34.3)
- Branch `fasttrack/p34c-product-pages` from `fasttrack/p34a-ui-foundation` @ c95231e0 (see
  `git log c95231e0..`). Owned files only: `app/san-pham/**`, `app/ket-noi/**`, `components/product/**`.
- **Template** (`components/product/capability-page.tsx`, `capability.module.css`, tokens only):
  breadcrumb (full registry trail incl. "Trang chủ") · split hero (eyebrow + H1 `page` | `ui-lead` +
  `LinkButton` ×2) · hero `Shot` (chrome, `joined`, `padding="lg"`, `priority`, "Dữ liệu mẫu · Cửa hàng
  Mẫu Hoa Mai") · `.ui-toc-layout` with `TocNav` + `<article>`: each `CapSection` = H2 `article` +
  opening paragraphs + one `Shot` (alt "… (dữ liệu mẫu)", caption "Dữ liệu mẫu · …", `mobileVariants`)
  placed before the first H3 + the rest · FAQ `FaqList` (one source: the page's `FAQ` const → visible
  list and `faqPageSchema`) · next/see-also cards (first "Tiếp theo") · one dark band (`Section
  tone="dark" spacing="compact"`). `heroShot`, `heroChrome`, `heroCaption`, `ctaTitle` are new props.
- **Diagrams** (`components/product/diagrams.tsx`, markup, real list text): `StreamGrid` (5 streams,
  group + where Juli shows each), `ProcessDiagram` `flow` / `timeline`. Phân tích: `StreamGrid` in
  "Năm luồng" + `FunnelDiagram highlight="ctor"` replacing the old formula box (formula text kept in
  its caption). Đề xuất: flow Duyệt (bạn, pink) → Thực thi → Hoàn tác in "Duyệt hoặc từ chối".
  Đo lường: timeline Trước khi áp dụng → Ngày 7 → Ngày 14 in "Trước khi áp dụng". No numbers added.
- **Pages**: hero shots — Phân tích luồng + phễu (as the mockup), Đề xuất xác nhận (cropped 16:10),
  Đo lường mục tiêu + tăng thêm, Kết nối the connect screen only ("lighter"; the second shot showed a
  different sample shop). `/san-pham` rebuilt on `components/ui`: hero + Quyết định shot, "Juli AI là
  gì" (reading column), loop `StepList` (long P33-B bodies, Duyệt = "03 · bạn"), 3 capability cards
  (shot cropped 2.4:1 + eyebrow + CheckList + `TextLink`), scope cards, integrations with `StatusPill`
  (TikTok Shop live, Shopee integrating), data safety CheckList, audiences, pricing `Card
  tone="highlight"`, two-column FAQ, dark CTA band. All test ids kept (`product-*`, `cap-*`) plus
  `cap-final-trial-cta`, `cap-final-demo-cta`, `product-final-demo-cta`, `product-contact-cta`.
- **Deviations from the mockup**: breadcrumb shows "Trang chủ /" first (matches BreadcrumbList);
  capability CTAs are `md` size (mockup 15 px buttons); the dark band adds the price line and a "Xem
  demo" button; the five-stream labels are `<p>`s, not `<h3>` (keeps the outline to the article's own
  H3s); FAQ first item open; the next/see-also block has 4 cards (2×2) instead of 2.
- **Copy changes (words kept otherwise)**: capability trial CTA "Dùng thử 3 tháng" → LOGIN_URL became
  `TRIAL_CTA_LABEL` "Dùng thử miễn phí 3 tháng" → `SIGNUP_URL` (D43 additions 2, mockup). `/san-pham`
  corrections to match the capability pages / D14 / D34: loop "Phân tích" names the five streams (was
  three); loop "Đo lường" and FAQ "kém hiệu quả" now say Juli *asks* whether to revert when a guarded
  metric leaves its band at day 7 (was "Juli đề xuất hoàn tác ngay"); the "Đo lường GMV tăng thêm"
  card says the comparison with unchanged products is being tested (was stated as done). Kết nối:
  "trang Liên hệ" is now a link to `/contact` (D43 additions 3).
- **Tests** (intentional updates): `capability-pages.test.tsx` — FAQ read from `#cau-hoi summary`;
  the shot's caption checked on its own `figure.ui-shot` (a section may also hold a diagram figure);
  CTAs by test id (trial → SIGNUP_URL, demo → DEMO_URL); new: breadcrumb + chrome hero + TOC targets
  exist + ≥ 3 mobile `<source media>` + one dark band; the three diagrams. `info-pages.test.tsx` — new
  `/san-pham` test: links to all 4 product pages, 5-step loop with Duyệt marked, StatusPill live =
  TikTok Shop / integrating = Shopee, Shopee wording, FAQ = FAQPage, one dark band.
  vitest 13 files / 186 passed, `next build` OK, `check:seo` 17/17; Playwright on `next start`, 5 pages
  at 1440 and 390, no horizontal overflow, looked at section by section (hero, diagrams at both widths,
  cards, FAQ, dark band): `fasttrack/design/p34/evidence/p34c/*.webp` (full page; the TOC and header
  are forced static for the capture). `check.sh --since c95231e0` 5/5 PASS. DEBT: 5 items (P34-C).
## 2026-10-15 — P34-D agent (Claude Opus) — blog redesign + covers (D44, AC-34.4)
- Branch `fasttrack/p34d-blog` from P34-A c95231e0. Commits 7b7ef53e (covers + meta), the page
  rebuild, 751103eb (fixes, README, evidence) + this docs commit.
- **Covers**: `apps/landing/scripts/blog-covers.mjs` renders an HTML template with Playwright at
  400×225 CSS px × DSF 3 → 1200×675 (so the 3 px outline reads as 3 px on a ~370 px card), encodes
  AVIF/WebP 600/1200 through `media.py optimize`, and renders the same template at 1200×630 as the
  OG PNG. Motifs from Blog.dc.html (bars / product card / tiles) + a checklist for "Hướng dẫn";
  colours parsed from `tokens.css`; existing files are skipped (immutable cache, bump `-vN`).
  Covers for the 3 posts; OG wired through `buildMetadata` options and the Article JSON-LD image.
- **Index**: "Blog Juli" H1 + lead + pills (toggle buttons, `aria-pressed`, polite live count;
  mockup used `role=tab` without panels), featured card (2:1 crop anchored at the bottom), 3-up
  grid (`auto-fill`, so 2 cards stay card-sized). Cards: title link stretched over the card,
  cover `alt=""`. Drafts appear (badge "Bản nháp") only under `next dev`.
- **Post**: breadcrumb, draft note, category · minutes, title 32→48, standfirst, meta, cover,
  `TocNav title="Mục lục"` (H2s + FAQ), prose 720 px 17→18 / 30 px with styled H2/H3, lists
  (restored markers Tailwind preflight strips), callouts, focusable scrollable tables (`role=region`,
  "Bảng n"), `FaqList` (page-level `faqPageSchema` kept), sources, related `PostCard`s (h3), dark
  CTA band (`blog-cta-trial` → SIGNUP_URL, `blog-cta-demo` → DEMO_URL; both tracked by the listener).
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 13 files / 186 passed (blog 31),
  build OK, `check:seo` 17/17; Playwright `/blog` (dev, prod-empty, filter) + the metrics post at
  1440/390, no overflow, font Be Vietnam Pro → `fasttrack/design/p34/evidence/p34d/`;
  `check.sh --since c95231e0` 5/5 PASS. Deviations and follow-ups in DEBT (P34-D).
## 2026-10-15 — P34-E agent (Claude Opus) — legal, about, contact, sign-up to the D44 mockups (AC-34.5)
Branch `fasttrack/p34e-legal-signup` from `fasttrack/p34a-ui-foundation` @ c95231e0 (not merged).
- **Legal template** (`app/privacy/legal-template.tsx`, `legal.module.css`), used by /privacy and
  /terms: header block (muted "Pháp lý", H1 44 px, "Cập nhật lần cuối: … · Có hiệu lực từ …"),
  VN/EN switch on /privacy only (two anchor links, "English" → `#english`, the jump the old
  "English version ↓" link does — kept too; /terms has no English version, so no switch);
  "Tóm tắt dễ hiểu" card (privacy 5 bullets, terms 4, each restating a numbered section, with
  "Tóm tắt này không thay thế nội dung đầy đủ bên dưới."); 720 px column at 17/30; numbered H2s
  (muted number) with ids `muc-*` / `dieu-*`, existing anchors kept (`du-lieu-nguoi-dung-google`,
  `dang-ky-dung-thu`, `shopee-data`, `english`, `google-user-data`); `TocNav variant="rule"` on the
  right, `<details>` on mobile; closing block with company, MST, address, email. **No legal sentence
  changed**: the rewrite was scripted (heading text moved into a prop, classes swapped) and
  `git diff -w` shows markup only; the English part only changed class names. Bullets restored on
  legal lists (Tailwind preflight had removed them).
- **/about**: bird mark, H1, lead, mission split, 4 principle `Card`s on alt, company card (bird +
  name + the 6 facts as a `dl`), dark CTA (Demo, /contact). Facts unchanged.
- **/contact**: icon cards (Email `mail`, Address `shield-check`), 3 topic cards — "Hỗ trợ tài
  khoản" now says disconnecting = email the Juli team (D43 additions 3) — dark Demo CTA.
- **/dang-ky** (`Signup.dc.html`): eyebrow "Miễn phí 3 tháng · không cần thẻ thanh toán", H1
  "Đăng ký dùng thử Juli" (route title unchanged), 2-col grid ≥ 640 px (phone | email), role
  tiles (2 px ink when checked via `:has`), consent, full-width dark submit (`buttonClassName`),
  "Muốn tự kết nối ngay? Tạo tài khoản và kết nối shop →" (→ `SELF_CONNECT_URL`,
  `signup-self-connect-link`), aside "Sau khi bạn đăng ký" (3 ink-circle steps, `NEXT_STEPS`) +
  `ShotFrame` cap-kn-ket-noi. Form logic untouched: field names, POST `/dang-ky/gui`, no-JS
  `:target` notices, inline errors + focus, honeypot, consent links; Pixel CompleteRegistration
  untouched. P33-F's value list (`SIGNUP_VALUES`) removed — the aside replaces it.
- **/dang-ky/cam-on**: bird, eyebrow, H1, lead, "Tiếp theo" card with the same 3 steps, "Tự kết nối
  shop ngay" (`self-connect-cta`) + "Về trang chủ"; still noindex, out of the sitemap.
- **Deviations from the mockups**: the optional "Ghi chú" textarea and the field hints stay (form
  behaviour; mockup has neither, uses placeholders); role label stays "Đội vận hành sàn" (mockup
  "Đội vận hành"); the summary bullets are worded from the policy rather than the mockup's (the
  mockup's "Juli không biết mật khẩu shop" is not stated in the policy); the English notice block
  stays at the top of /privacy (Google verification); TOC adds "English version" and the contact
  block; the aside shot is the mobile crop.
- **Tests** (intentional changes): `legal-pages` Shopee check asserts the 4A H2 (the TOC repeats the
  label) + 4 new template tests (summary + disclaimer, dates, company block, every TOC link resolves,
  numbered H2 ids, VN/EN switch, deep links); `info-pages` +2 (about company card + bird + CTAs,
  contact icons + disconnect copy); `signup` value-list check → aside steps / shot alt / self-connect
  link / real submit button, + thank-you bird + steps. All earlier guarantees kept.
- **Gates** (Node 20.20.2): landing lint 0, type-check clean, vitest 13 files / 185 passed, build
  OK, `check:seo` 17/17; Playwright on `next start`: 6 pages at 1440 and 390, horizontal overflow 0
  everywhere, screenshots looked at, `fasttrack/design/p34/evidence/p34e/` (privacy full pages cut
  to the first 6000 px: WebP height limit); `check.sh --since c95231e0` 5/5 PASS.
- DEBT: signup header wraps at 390 (shared header), template location, leftover `lp-page-*` /
  `.lp-legal__contact-link`, no map-pin icon, aside crop.
## 2026-10-15 — P34-F agent (Claude Opus) — demo sign-in / sign-up screen (D44.5, AC-34.6)
- Branch `fasttrack/p34f-auth-screen` from 64f7f913 (pushed, not merged). Demo only; `apps/landing` untouched.
- **No shell when signed out.** `DemoShell` renders bare on `/auth/email`, and on `/` whenever the
  visitor is signed out and not in the sample demo (and while that is still resolving). The entry read
  (sessionStorage "replay", `?entry=door`, `?dang-ky=dung-thu`) moved from `DemoLanding` into
  `components/landing-entry.tsx`, shared by the shell and the landing. The sample demo and signed-in
  pages keep the shell.
- **`components/auth/auth-screen.tsx`** follows `Auth.dc.html` / `AuthMobile.dc.html`. Logo top-left, a 400 px
  column, footer (Tài khoản đối tác · Điều khoản · Chính sách bảo mật · ©), and a right panel at
  ≥1024 px (the cap-dx-the shot in AVIF/WebP at 640/1186 under `apps/demo/public/auth/`, captioned
  "Dữ liệu mẫu", plus 3 proof lines). "Tiếp tục với Google" is the only ink button. Under it: the
  "hoặc dùng email" rule, the email field, an outline "Gửi mã đăng nhập" with a loading state, and the
  consent line ("Bằng việc tiếp tục…"). Below the column: "Xem thử với dữ liệu mẫu…" and the trial ↔
  sign-in switch (copy only, URL updated in place).
- **OTP view:** 6 boxes (`otp-code-input.tsx`: one-time-code on box 1, numeric). A paste or autofill
  fills every box and auto-submits; Backspace and the arrow keys move between boxes. The view shows
  the masked email, "← Đổi email", and the resend countdown. Errors are icon + `role="alert"`; a
  wrong/expired code adds "Gửi mã mới" once the 60 s floor passes. The email OTP state machine is
  now `auth/use-email-otp.ts`, and `email-sign-in.tsx` is removed. GoTrue calls, cooldowns,
  errors and session storage are unchanged.
- **Partner:** `PartnerSignIn` is now just the form (with the dark submit; errors unchanged) inside the
  partner view on `/auth/email` (footer link, `#doi-tac`, the shell's denial). From `/` the footer
  link navigates there, because the landing's module graph stays free of `/v1/*`.
- **Style:** `app/auth-screen.css`, scoped to `.auth-screen`. Be Vietnam Pro comes from the root
  layout's existing `next/font/google` variable (latin + vietnamese). Ink buttons are 18.9:1, with
  44 px targets and focus rings, and `lang="vi"` is kept. The old landing / email / partner CSS is
  deleted from `globals.css`.
- **Copy:** `lib/auth-screen-copy.ts` + `lib/trial-signup-copy.ts`. In `dictionary.md`: new
  `auth.screen` and `auth.consent`; `auth.trial_signup(.body)` rewritten; `demo.try`,
  `auth.google`, `auth.email` and `auth.password` updated. A test checks that every exported
  string is in the dictionary.
- **Gates (Node 20.20.2):** `pnpm install --frozen-lockfile` OK. Demo lint has 0 errors and the 7
  pre-existing warnings; type-check is clean; vitest is 153 files / 1944 passed. `build:demo --force`
  (example Supabase env) is OK. Playwright against the local build: auth, landing-doors,
  locale-and-assistance, replay journey, tiktok-ad-visitor, static-asset-render and manual-refresh all
  pass. The full suite was 197 passed / 11 failed; after the two specs were fixed, only ops.spec's 5
  pre-existing failures remain (DEBT). `check.sh --since 64f7f913` is 5/5 PASS.
- **Tests updated on purpose** (they pinned the old copy or the shell on a signed-out `/`):
  demo-landing, email-sign-in (rewritten against the auth screen), reviewer-mode,
  reviewer-sample-mode, home, no-shop-sample, demo-shell ("/" left the full-shell list); e2e
  landing-doors, email-sign-in, demo-navigation (`SAMPLE_ENTRY`), replay-run-journey,
  tiktok-ad-visitor, locale-and-assistance, static-asset-render, manual-refresh.
- **Screenshots** (local build, 1440 + 390): `/private/tmp/claude-501/-Users-macos-Juli-AI-v2/5dd670f3-89e7-4e6b-adf6-912db2866737/scratchpad/p34f/shots/{signin,trial,otp,otp-error,partner}-{1440,390}.png`.
- **Next:** in P34 integration, align the font loading with P34-A's choice (DEBT). The owner can
  review the darker input borders (DEBT).

## 2026-10-15 — orchestrator (Claude Opus) — P34 integrated (A–F)

- Merged `fasttrack/p34b-home`, `p34c-product-pages`, `p34d-blog`, `p34e-legal-signup` (all on
  P34-A c95231e0) and `p34f-auth-screen` into `fasttrack/optimize-product`; only fasttrack doc
  conflicts (union-resolved), no code conflicts.
- Integration fixes: signup header keeps logo + "Đăng nhập" on one line at 390 (prefix hidden
  < 480 px); `.ui-card > p` no longer greys an `Eyebrow`; dead `.lp-breadcrumb` removed; cookie
  banner on the new buttons/tokens (its "Đồng ý" was white on light pink).
- Gates (Node 20.20.2): landing lint / type-check / vitest 202 / build / check:seo 17; demo lint /
  type-check / vitest 1944 / build. Screenshots of /, /san-pham/phan-tich-shop, /privacy (1440),
  /dang-ky (390): no horizontal overflow.
- Open for the owner: hero H1 length (5 lines at 1440), price wording "500.000đ/tháng" vs D43
  "từ 500K", sample figures inside the hero screenshot; 3 blog posts still drafts.
- P34 deploy run 38733326029 stopped at `check.sh` (CI scope since 0739f4da):
  `test_issue_397_demo_workspace_contract::test_theme_and_shared_home_primitives_are_consumed_by_demo`
  pinned `@juli/ui` on the home surface; P34-F's auth screen (D44.5) dropped that import. The test
  now asserts the demo app still consumes `@juli/ui` (it does: Quyết định, Cài đặt, panels).
  Local `check.sh --since 0739f4da` (CI scope): 5/5, pytest 206 files / 2990 passed. Lesson:
  run the integration `check.sh` with the last deploy tag as `--since`, not the phase base.
- P34 deployed (run 38831471506, b936bf56). `seo_live_check` 20/20. Live Lighthouse mobile (local
  CLI; PSI API quota exhausted): home perf 71 / LCP 5.1 s, /san-pham 75 / 4.9 s, a11y 96 — the
  home price card was grey on dark (1.93:1): the P34 integration rule `.ui-card > p:not(.ui-eyebrow)`
  (0,2,1) outranked `.priceCard > .price` (0,2,0), shrinking the price too. Now
  `.ui-card > :where(p:not(.ui-eyebrow))` (0,1,0) + a dark-card body colour.
- LCP on mobile is the H1 (render delay 85–89 %), not the hero shot. Local `next start` A/B, 3 runs
  each: baseline 3.5 s → `preload: false` on fonts 2.9 s but FCP +0.7 s (rejected) → drop the
  700 face (wordmark only, now 600) + no priority on the hero shots 2.5 s, perf 96–98 home /
  97 /san-pham, a11y 100. An eager (not high) hero shot put it back to 3.4 s, so the hero shots
  lazy-load; desktop stays 98–100 (Lighthouse flags `lcp-lazy-loaded` there, accepted).
  Local Node 26 needs `NODE_OPTIONS=--no-experimental-webstorage` for vitest (CI pins Node 20).

## 2026-10-16 — P35 agent (Claude Opus) — product polish (D46, AC-35.x)

- Branch `fasttrack/p35-product-polish` from `8c03c6a5` (worktree `~/juli-fasttrack-p35`), not
  merged, not deployed. Commits `3b80d45e..` (see `git log 8c03c6a5..`).
- **Header dropdown** (D46.1): `ProductMenu` in `components/ui/header-nav.tsx`, items from
  `PRODUCT_MENU` (`lib/site.ts`): Tổng quan sản phẩm "Juli làm gì, cách làm và bảng giá" · Phân
  tích shop "GMV theo luồng truy cập và phễu" · Đề xuất và thực thi "Thẻ đề xuất, thực thi khi bạn
  duyệt" · Đo lường GMV "Đo kết quả ngày 7 và ngày 14". Click / keyboard only (no hover-open).
  New icons `grid`, `chart`, `bulb`, `send`, `target`.
- **/san-pham** (D46.2, D46.3, D46.5a): two-column hero (copy | `CAP_DX_LUOT_CHAY_MOBILE` run crop,
  lazy), H1 44 px at ≥ 960 px; loop = `StepList variant="stepper"`. Loop facts follow the P34-C
  corrections, not the stale reference text in the P35 brief: five traffic sources (not three);
  at day 7 Juli *asks* whether to revert when a metric leaves the band you allow (not "đề xuất hoàn
  tác ngay"); the comparison with similar unchanged products is not claimed in the loop (it is
  "đang thử nghiệm" on the measurement card). The dropped long text is on the capability pages
  (lever per metric, TikTok re-review and rejection reasons: `/san-pham/de-xuat-va-thuc-thi`; rejection
  reasons: de-xuat FAQ / do-luong).
- **Em dashes** (D46.4): 6 visible strings had one (OG alt, VideoObject name, about company row,
  de-xuat quote, two signup messages; the backend mirrors of the signup messages changed too).
  Built-site scan: 0 outside `/privacy` (21) and `/terms` (1).
- **Home** (D46.5b, D46.6): H1 "Trợ lý AI vận hành TMĐT: tìm chỗ cải thiện GMV." (3 lines at 1440);
  "Sàn Juli kết nối" is a `<p>` label; heading guard in vitest + `check:seo`.
- **Positioning** (D46.7), before → after:

  | Where | Before | After |
  | --- | --- | --- |
  | `/` title | Trợ lý AI vận hành cho nhà bán TikTok Shop \| Juli AI | Trợ lý AI vận hành TMĐT cho nhà bán TikTok Shop \| Juli AI |
  | `/` description | Juli AI phân tích TikTok Shop theo Lượt hiển thị, CTR, CTOR, AOV, đề xuất việc cần làm, thực thi khi bạn duyệt và đo GMV tăng thêm. Dùng thử 3 tháng. | Trợ lý AI cho nhà bán TMĐT, hiện kết nối TikTok Shop: đọc CTR, CTOR, AOV, đề xuất việc cần làm, thực thi khi bạn duyệt, đo GMV tăng thêm. |
  | `/san-pham` title | Phần mềm AI vận hành TikTok Shop: tính năng, giá \| Juli AI | Phần mềm AI vận hành TMĐT cho nhà bán TikTok Shop \| Juli AI |
  | `/san-pham` description | Juli AI phân tích GMV TikTok Shop theo Thẻ sản phẩm, Video, LIVE, đề xuất và thực thi khi bạn duyệt, đo kết quả ngày 7 và 14. Từ 500.000đ/tháng. | Phần mềm AI cho nhà bán TMĐT: phân tích GMV TikTok Shop theo Thẻ sản phẩm, Video, LIVE, thực thi khi bạn duyệt, đo ngày 7, 14. Từ 500.000đ/tháng. |
  | `/san-pham` H1 | Juli AI: phần mềm AI vận hành TikTok Shop, từ phân tích đến đo GMV tăng thêm | Juli AI: phần mềm AI vận hành TMĐT, từ phân tích đến đo GMV tăng thêm |
  | `/san-pham` intro | … phát triển cho nhà bán TikTok Shop tại Việt Nam. | … phát triển cho nhà bán TMĐT tại Việt Nam; hiện Juli kết nối TikTok Shop và đang tích hợp Shopee. |
  | `/san-pham` "Juli AI là gì" | Người bán TikTok Shop có rất nhiều số liệu … Mỗi sản phẩm có Lượt hiển thị … | Nhà bán TMĐT có rất nhiều số liệu … Trên TikTok Shop, mỗi sản phẩm có Lượt hiển thị … |
  | `/san-pham` "Dành cho ai" | Juli dành cho nhà bán TikTok Shop nhỏ và vừa … | Juli dành cho nhà bán TMĐT nhỏ và vừa … |
  | `/about` lead | … giúp người bán hàng trên TikTok Shop tăng trưởng ổn định … AI. | … giúp nhà bán TMĐT tăng trưởng ổn định … AI. Hiện Juli kết nối TikTok Shop và đang tích hợp Shopee. |
  | `/about` company row | Juli AI, trợ lý tăng trưởng cho người bán TikTok Shop | Juli AI, trợ lý tăng trưởng cho nhà bán TMĐT |
  | Footer tagline | Trợ lý AI vận hành cho nhà bán TikTok Shop. | Trợ lý AI vận hành cho nhà bán TMĐT. |
  | OG alt / image | Juli AI, trợ lý AI tăng trưởng cho người bán TikTok Shop (image "…cho người bán TikTok Shop") | Juli AI, trợ lý AI vận hành cho nhà bán TMĐT (`juli-ai-default-v2.png`: "Trợ lý AI vận hành cho nhà bán TMĐT", "Hiện kết nối TikTok Shop · Shopee đang tích hợp") |
  | VideoObject name | Juli AI, trợ lý tăng trưởng cho người bán TikTok Shop | Juli AI, trợ lý tăng trưởng cho nhà bán TMĐT |
  | `/blog` title | Blog kiến thức bán hàng TikTok Shop \| Juli AI | Blog kiến thức TMĐT và TikTok Shop \| Juli AI |
  | `/blog` description | Bài viết chuyên sâu cho nhà bán TikTok Shop: … chọn công cụ phù hợp. | Bài viết chuyên sâu cho nhà bán TMĐT, bắt đầu từ TikTok Shop: … chọn công cụ. |
  | `/blog` lead | Hướng dẫn đọc chỉ số, tối ưu thẻ sản phẩm và vận hành TikTok Shop, viết từ … TikTok. | Kiến thức vận hành shop TMĐT, bắt đầu từ TikTok Shop: cách đọc chỉ số, tối ưu thẻ sản phẩm, viết từ … TikTok. |
  | `/dang-ky` description | Đăng ký dùng thử Juli AI miễn phí 3 tháng cho TikTok Shop: … kết nối shop. | Đăng ký dùng thử Juli AI miễn phí 3 tháng: … kết nối TikTok Shop. |

  Unchanged on purpose: home hero lead (names no platform; badge + strip state TikTok Shop live,
  Shopee integrating), TikTok-specific facts, capability page titles, cookie text, blog bodies.
  Now disagreeing, left for the owner: `/terms` §2 "Juli AI là trợ lý giúp người bán TikTok Shop
  tăng trưởng và tối ưu vận hành" (contract + md + site); `dictionary.md` `landing.footer.tagline`.
- **Gates (local Node 26, vitest with `--no-experimental-webstorage`)**: landing lint 0,
  type-check clean, vitest 14 files / 225 passed, build OK, `check:seo` 17/17;
  `check.sh --since 8c03c6a5` (PYTHON = juli/.venv) 5/5 PASS (pytest 2 files / 52 passed).
- **Lighthouse mobile (local `next start`)**: `/san-pham` 98 / 97 / 98, LCP 2.49 / 2.57 / 2.49 s,
  a11y 100 (LCP = the intro paragraph). **`/` regressed with the new H1**: LCP element is now the
  hero shot (the 3-line H1 is smaller than its visible part); 5 runs LCP 2.58 / 3.29 / 3.21 / 3.20 /
  3.28 s, perf 93–97, a11y 100. Same build with the old H1: 2.57 / 2.79 / 2.49 / 2.56 / 3.29 s, LCP
  element the H1. `priority` on the shot: 2.80 / 3.44 / 3.86 / 3.69 / 2.81 s (worse, reverted).
  Open for the owner: accept, or shrink / move the mobile hero shot so the H1 stays the LCP.
- Screenshots: `~/juli-fasttrack-p35/.p35-logs/shots/` (san-pham hero / loop / full 1440 + 390,
  dropdown-open-1440, mobile-menu-open-390, home-hero 1440 + 390, dang-ky-header 1440 + 390); no
  horizontal overflow on /, /san-pham, /san-pham/phan-tich-shop, /dang-ky, /about at 1440 and 390.
- P35 merged into the integration branch (b7d0e9a9). Its decision renumbered D45 → D46: D45 was
  taken by the simulator grill (efe3105d) committed here in parallel. Gates on the merge: landing
  lint / type-check / vitest 226 / build / check:seo PASS; `check.sh --since b936bf56` 5/5. The
  P35 agent's final gate run and the terms 2.1 edit were blocked by the permission classifier;
  gates now done here, terms 2.1 (D46.8) waits for the owner. AC-35.5 stays open: home mobile LCP
  median 2.60 s on a loaded host (H1 is the LCP element again); re-measure live after deploy.

## 2026-10-16 — P36 agent (Claude Opus) — simulator research priorities into Ops (D45.1–D45.4, D45.6, D45.8)

- Branch `fasttrack/p35-sim-ops` (worktree `~/juli-fasttrack-p35-sim-ops`; the branch name was
  kept, the phase number is **P36** because P35 = product polish). `fasttrack/optimize-product`
  merged in first (`35513e08`) for D45.7 / D45.8. Not merged, not deployed. Resumed from an
  interrupted agent's uncommitted work: the 13 test edits and the deferred 074 edit are the usual
  "074 follows the head" re-parenting onto `092_card_group_design` (checked: no other fasttrack
  branch has a 092; revision id 21 chars; single head).
- **Built:** migration 092 (`card_groups.design` JSON); Ops "Tạo nhóm thử nghiệm" with lever
  "Quy cách mới" and an optional order-volume stratified draw (D45.8: 3 + 3 → 2 + 1 per stratum);
  AOV and items per order on every verdict, CTR guard (> 15 % drop warns, even if AOV rose);
  pre-period rule by group size (D45.6); drift floor + traffic needed under each group (D45.4);
  one-line "lý do chọn thử nghiệm" (D45.3, manual). Tunables `group_two_window_min` (15),
  `group_guard_ctr_drop` (15), `group_drift_sigma` (0.15). Details: DECISIONS D45 item 10.
- **Scope decision:** a card-drawn group's primary verdict feeds the seller's "Kết quả nhóm", so it
  keeps the P31 rule; the D45.6 reading is stored beside it (`verdict.ops_rule`) and shown in Ops
  only. Ops groups and the new metrics use D45.6. Card groups switched off → only Ops groups are
  measured.
- **Power check** (`juli-sim-pilot/v03/power_p31.py`, 500 reps, CTR only; before =
  `20261013-191329-p31-power` at the flat 15 % gate, after = `20261016-111445-p31-power`, same
  seeds). Real false alarm (two-sided, δ = 0) and power for "tăng" at +22 / +40 / +65 %:

  | Design | False alarm before → after | +22 % | +40 % | +65 % | "Đang đo" |
  |---|---|---|---|---|---|
  | 4+2 · 14d | 7.2 → 7.0 % | 14 → 13 % | 27 → 21 % | 46 → 39 % | 0 → 0 % |
  | 5+3 · 14d | 4.2 → 5.8 % | 7 → 4 % | 13 → 6 % | 15 → 13 % | 0 → 0 % |
  | 5+5 · 14d | 4.4 → 4.4 % | 11 → 7 % | 19 → 12 % | 33 → 25 % | 20 → 13 % |
  | 4+6 · 14d | 5.4 → 6.4 % | 11 → 7 % | 24 → 19 % | 38 → 30 % | 26 → 20 % |
  | 17+9 · 14d | 8.6 → 8.0 % | 29 → 27 % | 55 → 56 % | 79 → 79 % | 9 → 9 % |
  | 4+2 · 28d | 7.8 → 6.8 % | 20 → 12 % | 35 → 25 % | 56 → 47 % | 0 → 0 % |
  | 5+3 · 28d | 4.6 → 3.2 % | 7 → 3 % | 15 → 9 % | 25 → 14 % | 0 → 0 % |
  | 5+5 · 28d | 5.4 → 5.0 % | 15 → 9 % | 26 → 15 % | 47 → 33 % | 18 → 13 % |
  | 4+6 · 28d | 8.0 → 6.8 % | 15 → 10 % | 34 → 23 % | 50 → 39 % | 21 → 19 % |
  | 17+9 · 28d | 9.6 → 9.2 % | 30 → 33 % | 64 → 67 % | 82 → 83 % | 12 → 12 % |

  False alarms stay < 15 % everywhere (max 9.2 %). **In this simulator the plain change (θ = 1)
  costs small groups power** (4+2 at +40 %: 27 → 21 % / 35 → 25 %), the opposite of research run
  `20261015-212942` §4a (which compared with a different ANCOVA); the two windows add a little at
  17+9 (+1 to +3 points, not the research's 58 → 70 %). The simulator has no days −42..−29, so
  its 17+9 replay runs one window (DEBT). CTOR / AOV power is not simulated by `power_p31.py`.
  Owner decision suggested: keep θ = 1 below 15 (as D45.6 says) or set it back to the P31 θ.
- Gates: see the hand-back (full `fasttrack/check.sh`, `test_chi_so_docs_vocabulary.py`, demo
  vitest / tsc / eslint on the Ops files).

- D46.8 terms 2.1 (owner, 2026-10-16): /terms shows "Phiên bản 2.1 · Cập nhật lần cuối: 16/10/2026";
  §2 "người bán TMĐT … (hiện kết nối TikTok Shop, Shopee đang tích hợp)" (site without the
  "tên gọi khác JustLiveAI" alias, owner's call); §3 sign-in "với Google hoặc bằng email với mã xác
  thực" as in the md. md `~/Downloads/b2b_document/md/01_Dieu_khoan_dich_vu_v2.md` → 2.1 / 16/10/2026
  with the same §2 sentence (alias kept); backup in `_luu_tru/…bak-2026-10-16`. Not synced (owner
  informed): the site /terms is a 10-section text that never carried md v2.0's §5 contract, §6
  VAT/auto-renew/invoices, §7 acceptance, §10 data, §11 confidentiality, §13 liability cap, §15
  governing law; the md lacks the site's 3-month trial and Shopee paragraph; the Ory contract cites
  "phiên bản 2.0 (ngày 14/10/2026)". /privacy also differs from its md (~20 blocks).
  Landing gates: lint / type-check / vitest 227 / build / check:seo PASS.
- Deployed 2026-10-16: runs 38850894312 (e869e06a) and 38850938826 (980735ec), both success.
  Live: `seo_live_check` 20/20; heading audit 12/12 public routes OK (one H1, no skipped level);
  /terms shows "Phiên bản 2.1"; home H1/title carry the TMĐT copy. PageSpeed Insights mobile
  (Google's servers, 12:07–12:09 GMT+7): home perf 84 · a11y/BP/SEO 100 · FCP 2.3 s · LCP 3.4 s ·
  TBT 200 ms · CLS 0.006; /san-pham perf 88 · a11y/BP/SEO 100 (was 71 / 75 live before
  8c03c6a5). AC-34.7 / AC-35.5 stay open: ≥ 95 / LCP < 2.5 s not met live. The gap is now FCP
  (2.3 s: TTFB + render-blocking CSS ~150 ms), not the LCP element; next lever is server/edge
  caching of the HTML (Cloudflare) rather than more page changes. Local CLI Lighthouse on this
  host is unusable while load is 15–48.
- Owner (2026-10-16): home H1 keeps the old tail → "Trợ lý AI vận hành TMĐT: tìm chỗ cải thiện GMV,
  đề xuất cách sửa, đo kết quả." (was "…TikTok Shop: tìm chỗ GMV hụt, đề xuất cách sửa, đo kết
  quả." before D46.5). Landing gates PASS.
- Owner (2026-10-16): final home H1 "Trợ lý AI vận hành TMĐT: tìm chỗ cải thiện GMV, đề xuất chiến
  lược, đo kết quả." (f7337452).
- Google result (owner screenshot 2026-10-16) still shows the pre-redesign title/snippet and a generic
  globe icon: URL Inspection says last crawl 2026-10-08. Favicon/meta/JSON-LD are correct live
  (favicon.ico 48×48, icon.png 192, Organization logo 512). WebSite JSON-LD now `url` with the
  trailing slash + `alternateName: "Juli"` (site-name signal). Owner to "Request indexing" for / in
  Search Console (UI-only; the API cannot).

## 2026-10-16 — P36 agent (Claude Opus) — D47.1: small groups back on the P31 θ

- `fasttrack/optimize-product` (D47) merged in (`e08f00ee`). `group_stats.adjust_changes`: below
  15 measured products the fitted P31 θ (one window) again; from 15 the two pre-period windows.
  Applies to the primary, the extra metrics (AOV, items per order), the CTR guard and the
  false-alarm replay. The original P31 verdict test fixtures are restored.
- Power check re-run (`juli-sim-pilot/v03/results/20261016-123329-p31-power`, 500 reps, CTR, same
  seeds, 15 % gate). Columns: P31 (`20261013-191329`) / D45.6 θ = 1 (`20261016-111445`) / D47.1:

  | Design | False alarm | +22 % | +40 % | +65 % | "Đang đo" |
  |---|---|---|---|---|---|
  | 4+2 · 14d | 7.2 / 7.0 / 7.2 % | 14 / 13 / 14 % | 27 / 21 / 27 % | 46 / 39 / 46 % | 0 / 0 / 0 % |
  | 5+3 · 14d | 4.2 / 5.8 / 4.2 % | 7 / 4 / 7 % | 13 / 6 / 13 % | 15 / 13 / 15 % | 0 / 0 / 0 % |
  | 5+5 · 14d | 4.4 / 4.4 / 4.4 % | 11 / 7 / 11 % | 19 / 12 / 19 % | 33 / 25 / 33 % | 20 / 13 / 20 % |
  | 4+6 · 14d | 5.4 / 6.4 / 5.4 % | 11 / 7 / 11 % | 24 / 19 / 24 % | 38 / 30 / 38 % | 26 / 20 / 26 % |
  | 17+9 · 14d | 8.6 / 8.0 / 8.0 % | 29 / 27 / 27 % | 55 / 56 / 56 % | 79 / 79 / 79 % | 9 / 9 / 9 % |
  | 4+2 · 28d | 7.8 / 6.8 / 7.8 % | 20 / 12 / 20 % | 35 / 25 / 35 % | 56 / 47 / 56 % | 0 / 0 / 0 % |
  | 5+3 · 28d | 4.6 / 3.2 / 4.6 % | 7 / 3 / 7 % | 15 / 9 / 15 % | 25 / 14 / 25 % | 0 / 0 / 0 % |
  | 5+5 · 28d | 5.4 / 5.0 / 5.4 % | 15 / 9 / 15 % | 26 / 15 / 26 % | 47 / 33 / 47 % | 18 / 13 / 18 % |
  | 4+6 · 28d | 8.0 / 6.8 / 8.0 % | 15 / 10 / 15 % | 34 / 23 / 34 % | 50 / 39 / 50 % | 21 / 19 / 21 % |
  | 17+9 · 28d | 9.6 / 9.2 / 9.2 % | 30 / 33 / 33 % | 64 / 67 / 67 % | 82 / 83 / 83 % | 12 / 12 / 12 % |

  Every small design is back to the P31 numbers exactly; 17+9 keeps the two-window gain
  (+1 to +3 points at +22 / +40 %); false alarms ≤ 9.2 % everywhere.
- **Open contradiction:** research run `20261015-212942` §4a found the fitted θ *worse* for 4+2
  (SE 0.17 → 0.26) while this simulator finds θ = 1 worse. Both readings are kept; re-check on the
  first real D34 groups (the Ops "Cách tính" line and `verdict.adjustment` record the rule used).
## 2026-10-16 — P37 agent (Claude Opus) — demo sample mirrors the real card lifecycle (D47.2, D47.3)
- Branch `fasttrack/demo-lifecycle` (worktree `~/juli-fasttrack-demo-lifecycle`) from
  `fasttrack/optimize-product` 91e7f450, merged 5b1a85f5 (D47.3 rewrite: reviewer stays on the sample
  shop; pinned Fujiwa `ReviewerSimulation` NOT changed). Phase number P37 (P35 polish, P36 sim-ops taken).
- Code (demo only, no backend change): `lib/quyet-dinh/sample-clients.ts` keeps a desk status per card
  (as `ActionCard.status`) and derives the seller status like `card_view._status`; runs start
  `queued`; close-card paths (Từ chối, declined consent, Không thực hiện, Hoàn tác at start) →
  "Đã từ chối" + 7-day cooldown; failed / cancelled / timed-out → "Chờ duyệt"; 7 days untouched →
  "Hết hạn"; Seller Center and content runs (no recorded write) stay "Đang thực hiện". Seams
  `advanceTime` / `failRun`. One tab-wide store (`lib/reviewer/sample-store.ts`) for signed out, no
  shop and the sample reviewer; "Làm mới Demo" resets it. `QdClients.subscribeDecisions` (sample only)
  re-reads cards + runs in `QuyetDinhView`; Phân tích reads `fetchDeskDecisions`. Trang chủ shows no
  cards (signed in or sample) — nothing to follow there (the brief's "static SAMPLE_CARDS on home" was
  not the case).
- Divergences from the brief's findings, verified in code: the revert closes the card at its START
  (`demo_run_changes.start_revert` → `close_card`), not on completion; "Không thực hiện" on a wait
  is `cancelled` / `cancelled_by_seller` (was `completed` in the sample); the real backend reactivates
  a card only on `failed` (DEBT P37).
- Tests: `src/__tests__/sample-card-lifecycle.test.ts` (21, one per D47.2 transition),
  `src/components/__tests__/sample-lifecycle-views.test.tsx` (6, UI + Phân tích on the shared store),
  `reviewer-all-features.test.tsx` +1 (reviewer store: running → failed → Chờ duyệt → Hết hạn, the
  only request still `GET /v1/reviewer/me`). `phan-tich.test.tsx` "Xem 4 đề xuất" → 3 (the applied
  TN-021 is off the desk, as in the real list); one `sample-quyet-dinh` assertion now waits (flaked
  under host load). Demo vitest 155 files / 1972 passed; `tsc` clean; eslint 0 errors (7
  pre-existing warnings elsewhere); `replay-module-graph.test.ts` PASS.
- `check.sh` (default `--since origin/main`, Docker unresponsive on this host so CHECK_DATABASE_URL =
  a throwaway local DB, dropped after): migrations / isolation / gitleaks / ruff PASS; pytest 206
  files 2988 passed, **2 failed**, both outside this branch (no Python diff): 
  `test_reaper_two_tenant.py::test_each_run_is_reaped_by_its_own_workflows_policy_as_juli_app` fails
  deterministically on a fresh DB on the base too (pre-existing, for the orchestrator);
  `test_shop_ingestion.py::TestHistoryPhase::test_is_resumable…` timed out at 30 s under load 30 and
  passes alone.
- Reviewer sign-in (D47.3, investigated, nothing changed): D42.2 already gives team-created email +
  password accounts. Demo: auth screen footer "Tài khoản đối tác" → `/auth/email#doi-tac`
  (`PartnerSignIn`, Supabase password grant, then `GET /v1/reviewer/me`); expired / revoked /
  non-trial users are signed out with the reason. Tests `password-sign-in.test.ts`,
  `reviewer-mode.test.tsx`, `reviewer-sample-mode.test.tsx` PASS (31). Owner creates the account with
  `python -m juli_backend.services.reviewer.cli create --email shopee-review@app-juli.com --platform
  shopee --by <you>@app-juli.com [--days 30]` (env DATABASE_URL, SUPABASE_URL,
  SUPABASE_SERVICE_ROLE_KEY; password printed once); `renew [--rotate-password]`, `revoke`, `show`.
- Merge note: `fasttrack/p35-sim-ops` was merged into the integration branch meanwhile (52441f8e);
  merged `fasttrack/optimize-product` back into this branch, DEBT.md / LOG.md append-only conflicts
  resolved by keeping both sides. No code overlap (that branch is Ops + backend). Post-merge demo
  gates re-run below.
- Post-merge (5da55516): demo `tsc` clean, eslint 0 errors, vitest 156 files / 1977 passed.

## 2026-10-16 — P38 agent (Claude Opus) — D47.5: cancelled / timed-out runs reactivate the card

- Branch `fasttrack/run-reactivate` from `fasttrack/optimize-product` 175e85ef (phase P38: P35–P37
  taken); `fasttrack/optimize-product` (6cfd2851, with P37 `fasttrack/demo-lifecycle`) merged in
  before the docs. Backend only; `apps/demo` untouched.
- New `services/agent/card_reactivation.py::reactivate_card_for_ended_run` — the one writer of
  `approved` → `active` (`approved_at` cleared) for `failed` / `cancelled` / `timed_out`. Callers:
  `runner/conversation_store.py::persist` (replaces the FAILED-only block), the crash handler in
  `workers/tasks/agent_workflow.py` (replaces its inline copy) and `workers/tasks/reaper.py`'s sink
  (new). Idempotent, card must be the run's own shop, `surfaced_at` kept.
- Every path a run ends `cancelled` / `timed_out` (and how it behaves now):
  - seller `POST /v1/agent-runs/{id}/cancel` and Ops shop disconnect (`cancel_requested`) → runner
    checkpoint `cancelled_by_seller` → `cancelled` → card active;
  - wall clock / iteration cap (runner) → `timed_out` → card active;
  - reaper consent lapse `confirmation_expired` → `cancelled` → card active;
  - reaper `external_wait_expired` (photo 3 d, promotion, content waits) → `timed_out` → card active;
  - reaper `worker_lost` → `failed` → card active (did not reactivate before; now "like failed");
  - "Không thực hiện" while a lever flow waits (`lever_flows.end_wait_by_seller` →
    `cancelled_by_seller`): unchanged — the route's `close_card` dismisses (7-day cooldown);
  - "Không thực hiện" at the consent step (run ends `completed` / `confirmation_declined`), Từ chối,
    Hoàn tác (its revert run carries the same card): unchanged, dismissed. The helper only moves an
    `approved` card, so it cannot undo a dismissal (tested: decline, then the reaper lapses the
    consent → still dismissed; revert run cancelled → still dismissed).
- Emission budget: a reactivated card is `active` with its old `surfaced_at`, so it counts toward
  the open limit / cells again and expires 7 days after first surfacing (tested with
  `apply_emission_budget`). Cooldown: `approved_at` cleared, as for failed.
- Tests: `tests/unit/test_card_reactivation.py` (16: runner cancelled / timed_out ×2 / failed,
  completed + waiting keep approved, idempotent double transition, other shop's card untouched,
  reaper consent lapse / external wait / worker_lost, 7-day expiry, declined consent, lever-flow
  decline, revert, one-helper AST guard); `tests/integration/test_reaper_two_tenant.py` +1 (two
  tenants as `juli_app` under RLS, cross-tenant card link not followed). The #1305 test class
  docstring said CANCELLED / TIMED_OUT do not revert (no test asserted it); corrected.
- Gates: Docker Desktop hung (`docker info` no answer) → throwaway Homebrew Postgres 16 in UTC
  (`TZ=UTC`, `timezone='UTC'`, port 55438, trust, `/tmp`), removed after. `CHECK_DATABASE_URL=…
  fasttrack/check.sh --since fasttrack-deploy-20261016T0625Z` (= 6cfd2851, the deploy scope)
  **5/5 PASS** (migrations to 092, isolation 12, gitleaks, ruff 6 files, pytest 11 files / 104).
  `test_reaper_two_tenant.py` alone on that DB: 5 passed. mypy clean on the 4 source files.
  Pre-existing, not touched: `test_import_boundaries` strict-baseline (8 grandfathered deep
  imports in ops / workers files) and `test_agent_workflow_task_wiring` (7 fail without a DB on
  the base too).
- Full backend unit suite (SQLite, no DB, this worktree): 7456 passed, 43 failed, 3 errors. All
  pre-existing / environmental: 27 `test_agent_events_contract` (no `packages/contracts/
  node_modules` in a fresh worktree), 7 `test_agent_workflow_task_wiring`, `test_import_boundaries`,
  `test_ratchets` (30 s timeout on base too), `test_test_quality` ×3, `test_cross_tenant_probe`,
  `test_destructive_migration_isolation`, `test_three_tier_ci_contract`, `test_trial_signups`,
  `test_quality_reconcile` errors ×3 — the same files fail on `fasttrack/optimize-product`
  (6f92934c: 9 failed + 3 errors over those files with node_modules present).

## 2026-10-16 — P39 agent (Claude Opus) — search-intent priorities on the pages (D48 1–4, D48 additions 1, 2, 4)

Branch `fasttrack/p39-search-intent` (from 226fdbc5; merged `fasttrack/optimize-product` at 6f92934c
for the D48 additions). Landing only; no blog, /privacy, /terms body, demo or Python change.
- D48.1 `/san-pham` (dd95c145): title "Phần mềm AI phân tích, vận hành TMĐT TikTok Shop | Juli AI"
  (60-char limit with the suffix forced dropping "và" / "cho nhà bán"; DEBT), meta "Phần mềm AI phân
  tích và vận hành cho nhà bán TMĐT: …". H1 unchanged.
- D48.2 home (826c13af): first FAQ "GMV là gì, tăng GMV TikTok Shop bằng cách nào?" (8 items, in
  FAQPage via HOME_FAQ); home meta "đọc" → "phân tích" (c73e489a). Title / H1 unchanged.
- D48.2–3 `/san-pham/phan-tich-shop` (3d8118ea, c73e489a): title "Phân tích GMV TikTok Shop theo 5
  luồng truy cập", meta "Tăng GMV TikTok Shop từ đúng chỗ nghẽn: …", H2 "Tăng GMV từ chỉ số nghẽn: …",
  FAQ "Vì sao shop TikTok không ra đơn?" (first item; Lượt hiển thị, CTR, CTOR, AOV).
- D48.4 `/san-pham/de-xuat-va-thuc-thi` (523dfa54, c73e489a): title "Tối ưu sản phẩm TikTok Shop: đề
  xuất và thực thi", meta names only tiêu đề, mô tả; first H2 "Tối ưu sản phẩm TikTok Shop bằng thẻ đề
  xuất: …".
- `/terms` meta: "kết nối (hiện TikTok Shop, Shopee đang tích hợp)". lastModified 2026-10-16 on /,
  /san-pham, /san-pham/phan-tich-shop, /san-pham/de-xuat-va-thuc-thi (/terms already was).
- Additions 1 (005d643b): the H3 "Tiêu đề và mô tả: Juli cập nhật sau khi bạn xác nhận" under "Phần
  nào Juli làm, phần nào bạn làm" became "AI viết tiêu đề và mô tả, chỉ áp dụng khi bạn duyệt" + a day
  7 / 14 paragraph. An H3, not a new H2: every content H2 needs its own screenshot (D43.4, test) and
  all eight Đề xuất shots are already used.
- Additions 2 (89491255): `softwareApplicationSchema` removed; `/san-pham` emits `Service`
  (`#service`, provider Organization, Offer 500000 VND/tháng, areaServed VN); the three capability
  pages emit `WebPage` (`isPartOf` WebSite, `about` `#service`, `primaryImageOfPage`). No rating or
  review anywhere; seo.test, capability-pages.test and `check:seo` assert it.
- Additions 4 (873bf675): `/llms.txt` (static route) built by `llmsTxt(SITE_ROUTES)`: TMĐT-first
  summary, "Hiện kết nối TikTok Shop, Shopee đang tích hợp", price, company, then every indexable
  route grouped (noindex drafts / cam-on excluded). `llms-txt.test.ts` + `check:seo` compare.
- Gates (Node 26, vitest `NODE_OPTIONS=--no-experimental-webstorage`): lint 0, tsc clean, vitest 15
  files / 230 passed (with `--testTimeout=30000`; at the default 5 s 1–3 render tests timed out
  under host load 30, pass alone), build OK (`○ /llms.txt`), `check:seo` 18 passed.
- `check.sh` (Docker unresponsive: `docker info` hung, so CHECK_DATABASE_URL = throwaway local DB,
  dropped after): migrations PASS (head 092), gitleaks PASS, ruff PASS; isolation FAIL (12 fixture
  timeouts > 30 s) and pytest FAIL (32 timeouts then INTERNALERROR), host load ~30 from other agents'
  pytest runs. Isolation re-run alone on a fresh migrated throwaway DB with `--timeout=600`: 12
  passed. This branch has no Python diff vs `fasttrack/optimize-product`. Environmental.
- Next: owner review of the wording (esp. the /san-pham title), merge, deploy; GMV Max stays blog-only.

## 2026-10-16 — P40 agent (Claude Opus) — partner sign-in entry at the top of the auth screen (D47.6)
- Branch `fasttrack/partner-top` from `fasttrack/optimize-product` 12e692a1. Demo only. Phase P40
  (P38 = run-reactivate, P39 = search-intent are taken).
- `components/auth/auth-screen.tsx`: the entry view (plain and trial share it) opens with one link
  above the h1, an outline pill "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác →" (muted lead,
  pink action, arrow `aria-hidden`; hairline border, no fill, so Google stays the only filled
  control). Same href and click handler as the footer link, which stays: in-page `#doi-tac` on
  `/auth/email`, else `/auth/email#doi-tac`. Not shown in the OTP or partner views. Keyboard order:
  logo → partner entry → Google → email. Copy `AUTH_PARTNER_TOP_LEAD` / `AUTH_PARTNER_TOP_ACTION`
  (`lib/auth-screen-copy.ts`, `dictionary.md` `auth.screen` / `auth.password`), CSS
  `.auth-partner-top` (`app/auth-screen.css`).
- Tests: `demo-landing` (+1 D47.6 test: href, before the h1, before Google, in `main`, not ink,
  footer kept; trial test checks the entry too; "keyboard order" now includes it),
  `auth-email-page` (+1: in-page `#doi-tac`, click opens the partner view, focus on its heading),
  `reviewer-mode` (+1: the reviewer reaches the password form from the top entry), e2e
  `landing-doors` (+2: in viewport without scrolling and above the h1 on `/` and the trial variant,
  no horizontal scroll; click → `/auth/email#doi-tac`).
- Docs: `shopee-isv-services-information.md` step 1 gives `https://demo.app-juli.com/auth/email#doi-tac`
  and the top link; `apps/demo/MODULE.md`; D47 implementation note (P40); PROGRESS.
- Gates (Node 20.20.2; Node 26 breaks jsdom `localStorage` in vitest, so not used): `pnpm install
  --frozen-lockfile` OK. Demo vitest 156 files / 1983 passed; `tsc` clean; eslint 0 errors (7
  pre-existing warnings elsewhere). `build:demo --force` (placeholder Supabase env) OK; Playwright
  `landing-doors.spec.ts` on the local build 22/22 (desktop 960 + mobile 390).
- `check.sh` (default `--since origin/main`; Docker unresponsive, so CHECK_DATABASE_URL = a
  throwaway local Postgres 16 in UTC, dropped after): migrations / isolation / gitleaks / ruff PASS;
  pytest 207 files 3003 passed, 9 failed + 1 error, all pytest timeouts under host load ~35 (no
  Python diff on this branch); the 11 tests rerun alone all pass.
- Screenshots (local build, 2x): `/tmp/partner-top-shots/{signin,trial,auth-email}-{1440,390}.png`.
  At 390 px the pill wraps to two lines (lead / action), still above the heading.

## 2026-10-16 — P39-B agent (Claude Opus) — three Vietnamese blog drafts (D48 additions 6)

- Branch `fasttrack/p39b-blog` from `fasttrack/optimize-product` at 6f92934c. Not pushed, not merged.
- c5772320: covers `gmv-la-gi-v1` (metrics, bars, accent 0), `khong-ra-don-v1` (guide, checklist,
  accent 0), `doanh-thu-giam-v1` (metrics, bars, accent 3) added to `scripts/blog-covers.mjs`
  `COVERS` and rendered (`PYTHON=<main checkout>/juli/.venv/bin/python`; this worktree has no
  `juli/.venv`).
- 1988f93d: three posts, all `status: "draft"`, appended to `posts.ts` (featured post unchanged),
  bodies in `bodies/` + `bodies/index.ts`:
  - `gmv-la-gi-tiktok-shop` "GMV là gì? Cách tính và cách tăng GMV TikTok Shop" (4,524 words);
  - `tiktok-shop-khong-ra-don` "TikTok Shop không ra đơn: đọc phễu để tìm nguyên nhân" (4,078);
  - `doanh-thu-tiktok-shop-giam` "Doanh thu TikTok Shop giảm: checklist tìm nguyên nhân theo
    từng luồng" (3,709).
  Facts from TikTok Academy VN (header comment + `sources` in each): "Lưu lượng truy cập sản
  phẩm" (17/06/2026), "Tài Chính cho Người Mới Bắt Đầu…" (knowledge_id 825773561448193,
  01/12/2023: balance after all fees, "Quyết toán", (D+6)+1, accrual), "Quản lý Sản phẩm"
  (10008556, 27/08/2026: Trực tuyến / Đã vô hiệu hóa / Đã tạm ngưng / Bản nháp), plus the pages
  the existing drafts already cite. New pages fetched read-only with WebFetch on 16/10/2026. No
  fee rates quoted. Every number is a labelled "Ví dụ giả định". Ads only as "check CTR / CTOR
  before raising the budget; Juli does not run ads" (D48.5). Shopee only as "đang tích hợp". No
  "—" in body, meta or built HTML of the three pages. One soft `/dang-ky` CTA at the end of each.
- Gates (landing): lint PASS (eslint 0 problems); `tsc --noEmit` clean; vitest **under Node 20**
  14 files / 242 passed; build PASS (6 blog pages prerendered, new drafts `noindex, follow`);
  `check:seo` 1 file / 20 passed. Under the host's default Node 26.8.1 vitest fails 48 tests in
  cookie-consent / signup / tracking (`TypeError: Cannot read properties of undefined (reading
  'clear')`, jsdom localStorage) plus one 5 s timeout, none in blog code; repo engines say
  `>=20` and nvm has v20.20.2, so the gates were run on 20. A first Node 20 run had one
  `info-pages` timeout under host load; it passes alone and on the next full run.
- `fasttrack/check.sh` (Node 20): migrations FAIL "no throwaway database" and isolation FAIL "no
  migrated database" (known local limitation: `docker info` hung on this host, killed after ~10
  min so the script fell through); gitleaks PASS; ruff PASS (480 files); pytest 207 files: 7
  failed, 2857 passed, 150 skipped. All 7 in `tests/unit/test_agent_workflow_task_wiring.py`
  with `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL` (check.sh pins the DB URL
  empty when there is no throwaway DB); this branch has no Python diff.
- Next: owner reviews the three drafts (`pnpm --filter @juli/landing dev`, `/blog`) and flips
  `status` per README. A published post may link these slugs only once they are published too.

## 2026-10-16 — P41 agent (Claude Opus) — D47.7: short simulation copy, no backend internals

- Owner request 2026-10-16 (live demo, reviewer sample shop): the simulated Thực thi showed
  `PUT /product/202309/products/{product_id} (update_product_listing)`, a long "Với seller thật: …"
  paragraph and a second disclaimer; the run said `Có mã: "Mô tả quá ngắn"`; MN-015's keyword step
  said "son lì, đỏ ruby"; the queue said "Trong hàng đợi" next to "Xác nhận một lần — Đang chờ bạn";
  the page label repeated a long list. D47 item 7 added; implementation note in DECISIONS.
- Root cause of the queue mismatch: `runPhase` returned "queued" from the polled list row before
  looking at the events (the sample store starts runs `queued` and the list was read once). Fixed in
  `run-model.ts` (events win) and the sample store re-reads the list when a run's status moves.
- Sweep (apps/demo/src, seller- and reviewer-visible, ops excluded): endpoint / method / operation
  only in the dialog's request line (removed); model name + "JSON schema" in content runs (sample and
  backend `MODEL_STEP_RESULT`); "Có mã" / "mã chẩn đoán" (sample, backend tool summary, card "Xem
  thêm", grouping line); "công thức D22" in the quick-scan tooltip; "(lỗi {status})" in three error
  lines; "API" in three Quy tắc helps; canned-text mismatches (MN-015 keywords; video rules read
  "Không có từ cấm" vs two sample banned terms; promotion / photo "Sau" cells said "Juli soạn nội
  dung"; content cards got the Seller Center note). Left: legacy unlinked routes, LIVE caps vs sample
  rules (DEBT P41). All other `/v1/` hits are fetch call sites, not text.
- Verified in the real UI: `next dev` (before: base checkout on :3151, after: this branch on :3152),
  reviewer sample session via local storage (no backend; `/v1/reviewer/me` fails → record kept),
  Duyệt → Thực thi → Theo dõi on MN-015. Before: request line, two disclaimers, "Có mã", "son lì",
  "Trong hàng đợi" on both chips. After: Mục/Trước/Sau + one line, "Mô tả quá ngắn", "mặt nạ đất sét,
  se khít lỗ chân lông", "Đang chờ bạn" on header and queue. Screenshots in /tmp/simcopy-screens.
- Gates (Node 20.20.2; Node 26 breaks jsdom localStorage): demo vitest 157 files / 1982 passed
  (`--maxWorkers=4`; an unthrottled run under load 32 had 34 timeouts, all 17 files re-run alone
  passed 268/268); `tsc` clean; eslint 0 errors (7 pre-existing warnings); `replay-module-graph` and
  `reviewer-all-features` PASS. After merging `fasttrack/optimize-product` (P38, P39; DEBT /
  DECISIONS append conflicts kept both): `check.sh` (Docker hung > 10 s → throwaway Homebrew
  Postgres 16 in UTC as CHECK_DATABASE_URL, dropped after) migrations / isolation (12) / gitleaks /
  ruff (484 files) PASS, pytest 209 files 3045 passed, 2 skipped. `check.sh: OK`.

## 2026-10-16 — P42 agent (Claude Opus) — legal pages: data rights + processing layers (branch `fasttrack/legal-data`)
- Scope (owner, mid-task): live site only — `/terms` and `/privacy` (VI + EN). The md sources in
  `~/Downloads/b2b_document/md/` and the Ory contract were NOT touched (no backup, no clause file).
  Commercial terms (3-month trial, 500.000đ) unchanged. Deletion / disconnect promises unchanged.
- 6ef17dbf: `/terms` 2.2 (16/10/2026) new §8 "Dữ liệu của bạn" (8.1 ownership, 8.2 seller warrants
  the right to let Juli process shop + buyer data, 8.3 seller = controller / Juli = processor with
  commitments a–g incl. 72 h notice and no buyer identifiers to the AI provider, 8.4 third-party
  content in uploads + buyer reviews de-identified, 8.5 third-party secrets + market data, 8.6 the
  md's fine-tune clause verbatim, 8.7 per-shop suggestions, 8.8 pointer to Privacy §7); old §8–10 →
  §9–11. `/privacy` 2.1 (16/10/2026, version now shown): §1 controller split; §4 "Nội dung bạn tự cung
  cấp" + "Đánh giá của người mua và dữ liệu thị trường"; §6 purpose limit + fine-tune + per-shop; §7
  one processor list, "Dữ liệu gửi cho nhà cung cấp AI (OpenAI)", "Chuyển dữ liệu ra nước ngoài"
  (counsel marker is a JSX comment, not rendered); §8 72 h incident notice. EN mirrors all of it.
  Sitemap lastmod /privacy → 2026-10-16. New `legal-data-layers.test.tsx` (8 tests).
- Evidence for the processor list: OpenAI only LLM (`agent/llm/openai_adapter.py` `"store": False`;
  no other LLM host in backend/src); vision = product photos (`agent/vision.py`) + keyframes and
  listing images, ASR = audio slices (`content_analysis/openai_media.py`, "never the uploaded file");
  uploads on VPS disk, deleted at end, hourly sweep > 24 h (`content_analysis/storage.py`,
  `celery_app.py` content-analysis-sweep); no `buyer` provenance origin (`agent/sanitize/provenance.py`).
  Supabase (auth + DB); Cloudflare proxied DNS for app/api + Access for ops (`docs/runbooks/vps-wiring-
  runbook.md`, D25.1); AWS Secrets Manager us-east-2 (runbooks); Google Workspace `smtp.gmail.com`
  (`docs/runbooks/ops-console-runbook.md`, `services/ops/mailer.py`); Zalo OA / FCM adapters exist but
  nothing imports `services/alerts` → "(dự kiến)"; Viettel-CA has no code → "(dự kiến)"; FastMoss has
  no backend client (manual/agent look-ups, D24.5/15) → market-data source, not a processor; TikTok
  Pixel/Events API (`components/tiktok-tracking.tsx`, consent-gated). Ads: only the Business OAuth
  callback, awaiting TikTok approval — no ad data read, so the site lists none. Buyer review text is
  not ingested (only review counts) → the review sentences are conditional ("Nếu Juli sử dụng…").
- Not verifiable in the repo (owner): who sends Supabase email OTPs (Google Workspace as custom SMTP?);
  OpenAI org data-sharing setting is off; VPS provider name and Supabase region; Viettel-CA contract;
  counsel on the cross-border legal basis (marker in `privacy/page.tsx`).
- Contradiction for the owner: D24.8 plans SFT on seller-edited final text per category; the
  fine-tune clause (md, contract §5.4, now the site) allows only anonymised structural data with no
  titles / scripts / content. Text left restrictive.
- Gates (Node 26, `NODE_OPTIONS=--no-experimental-webstorage`): lint 0, tsc 0, vitest 16 files / 238
  passed, build OK, `check:seo` 18 passed. `check.sh --since fasttrack/optimize-product` (Docker
  unresponsive → throwaway local Postgres 16, UTC, dropped after): migrations PASS (head 092),
  isolation PASS (12), gitleaks PASS, ruff PASS (no Python), pytest PASS (none touched) → OK.
- Next: owner review of wording, merge `--no-ff`, deploy; then decide md/contract sync (md ToS is 2.1,
  Privacy 2.0; contract §8.3 cites v2.0 14/10/2026).

## 2026-10-16 — P39-C agent (Claude Opus) — inline images in the three P39-B drafts (D48 additions 7)

- Branch `fasttrack/p39c-blog-images` (from `fasttrack/optimize-product` 464c18fa). Not merged, not pushed.
- **Figure syntax**: a body line `{{hinh:<id>}}`, parsed by `components/blog/markdown.tsx` into a
  `figure` block (malformed `{{…}}` throws; not counted as a word); `<id>` is a key of
  `content/blog/figures.ts` (`BLOG_FIGURES`, type `BlogFigure` in `types.ts`); unknown id throws at
  render. Renderer `components/blog/figure.tsx`: `<figure>` + visible `<figcaption>` (14 px, body
  colour), AVIF/WebP with width/height, a phone `<source>` below 640 px, always `loading="lazy"`,
  never `priority`. Screenshots go through the product pages' `Shot` (backdrop + frame, caption
  "Dữ liệu mẫu · …"); diagrams sit in a hairline frame. Article JSON-LD `image` stays the cover
  (existing pattern); OG cover unchanged.
- **Diagrams**: new `scripts/blog-diagrams.mjs` (Playwright, tokens from `tokens.css`, Be Vietnam
  Pro inlined from `src/app/fonts`, `media.py optimize`): each diagram in a 720 px desktop layout
  (720/1440 w) and its own 360 px phone layout (540/1080 w), so text reads at 13–17 px on both.
  Ten diagrams, every one with numbers carries the "Ví dụ giả định" pill. Screenshots reuse
  `cap-pt-luong`, `cap-pt-pheu`, `cap-pt-xep-hang`, `cap-dl-tang-them` and their mobile crops.
  `cap-pt-nghen` was rejected (shows Lượt hiển thị for Tab cửa hàng, which the posts say TikTok does
  not split) and `cap-dx-the` too (an "—" in the new title and the old "mã chẩn đoán" wording).
- Figures (5 per post): GMV là gì: gmv-pheu, nam-luong, buoc-yeu-nhat, dl-tang-them, pt-luong;
  không ra đơn: ba-buoc-nghen, truoc-gio-sau-gio, quang-cao-ab, checklist-khong-ra-don, pt-xep-hang;
  doanh thu giảm: so-sanh-hai-ky, giam-theo-luong, pt-pheu, pt-xep-hang-doanh-thu, quy-trinh-30-phut.
  New files: 80 (10 diagrams × 2 layouts × 2 widths × 2 formats), 2,400 KB on disk; a reader
  downloads one AVIF per figure (≈ 14 KB desktop / 35 KB phone per diagram).
- Tests: `blog.test.tsx` +21 (each figure's files exist and the WebP header matches the declared
  width/height, Vietnamese alt and caption, no "—", screenshot caption "Dữ liệu mẫu · ", numbers →
  "ví dụ giả định"; each draft has 3–5 figures and stays draft; rendered figures lazy, sized,
  captioned, with a phone source; only the cover is eager; JSON-LD unchanged; parser cases).
  `check:seo` gains: on `/blog/*` every image sized, at most one eager, no eager inline figure.
- Gates (Node 20.20.2): lint 0, `tsc --noEmit` 0, vitest 16 files / 274 passed (one run under load
  from a parallel build had 2 timeouts; two reruns clean), build OK, `check:seo` 21 passed. Viewed
  the built posts (`next start`) at 390 and 1440 px: phone layouts served below 640 px, desktop
  720 w at 1440, captions 14 px, no horizontal overflow. `check.sh`: migrations / isolation FAIL
  (no throwaway database; `docker info` hung and was killed), gitleaks PASS, ruff PASS, pytest 7
  failed / 2889 passed (`test_agent_workflow_task_wiring.py`, SQLAlchemy URL parse: the known local
  limitation; no Python touched).
- Next: owner reviews the figures with the drafts (`pnpm dev`, `/blog/<slug>`), merge `--no-ff`.

## 2026-10-16 — P39-D agent (Claude Opus) — three more figures each in two P39-B drafts (D48 additions 8)

- Branch `fasttrack/p39d-more-figures` (from `fasttrack/optimize-product` e20e5394). Not merged, not pushed.
- **Không ra đơn** (5 → 8): `truoc-khi-doc-pheu` (diagram, H2 "Trước khi đọc phễu": four product
  statuses, only Trực tuyến sells, then stock per variant and shop operations), `doc-pheu-o-dau`
  (diagram, H2 "Đọc phễu ở đâu": the Seller Center path in words, no TikTok UI, plus the three
  reading rules; the 50 / 20 floors are labelled as Juli's rule, not TikTok's), `luong-noi-dung`
  (diagram, H2 "Luồng nội dung": Video / LIVE / Liên kết symptom and checks).
- **Doanh thu giảm** (5 → 8): `pt-video` (screenshot `cap-dl-tin-cay` + mobile crop, the Video block
  on the sample shop, placed after the Video checklist it matches: Lượt hiển thị +2,0 %, CTR −4,8 %),
  `kiem-tra-theo-chi-so` (diagram, H2 "theo từng chỉ số": four metrics, four cause groups),
  `ngoai-pheu` (diagram, H2 "Nguyên nhân nằm ngoài phễu": GMV vs tiền về, four causes).
- None of the five diagrams shows hypothetical data, so none carries the "Ví dụ giả định" pill;
  thresholds and day windows are rules from the post text. 40 new files, 1,756 KB on disk; a reader
  downloads one AVIF per figure. Existing diagram files untouched (script skipped them; CSS added
  under a `P39-D` block and new classes only, so the old diagrams re-render identically).
- `blog.test.tsx` figure bound 3–5 → 3–8.
- Gates (Node 26 with `--no-experimental-webstorage`): lint 0, `tsc --noEmit` 0, vitest 16 files /
  280 passed, build OK, `check:seo` 21 passed. `next start` at 390 and 1440 px: 8 figures per post,
  phone files below 640 px, desktop 720 w at 1440, no horizontal overflow; shots of the six new figures
  in the session scratchpad `shots-p39d/`. `check.sh`: migrations / isolation FAIL (no throwaway
  database), gitleaks PASS, ruff PASS, pytest 7 failed / 2889 passed (`test_agent_workflow_task_wiring.py`,
  the known local limitation; no Python touched).
- Next: owner reviews the new figures with the drafts, merge `--no-ff`.

## 2026-10-16 — P43 free GMV calculator `/cong-cu/tinh-gmv` (D49.1) — P43 agent (Claude Opus 5.5)

- Branch `fasttrack/p43-gmv-calculator` from `fasttrack/optimize-product` e20e5394. Commits 6d595c27
  (route `routes/tools.ts`, `webPageSchema()`, llms.txt section "Công cụ miễn phí", token
  `--lp-error-text` #b42318, 6.6:1), e172df7d (page + calculator + tests), 014b4e69 (links).
- Page: title "Công cụ tính GMV TikTok Shop miễn phí | Juli AI" (47), description 149 chars, H1 =
  title without suffix; H2s "Tính GMV của bạn", "Cách đọc kết quả", "Câu hỏi thường gặp", "Muốn biết
  GMV hụt ở luồng nào, sản phẩm nào?" (one soft CTA → `/dang-ky`, secondary button). JSON-LD
  WebPage + BreadcrumbList (Trang chủ → Công cụ tính GMV) + FAQPage (6 questions); no
  WebApplication / SoftwareApplication / rating. In the sitemap and `/llms.txt`.
- Calculator (`components/gmv-calculator/`, client): mode Tỷ lệ (Lượt hiển thị, CTR %, CTOR %, AOV ₫)
  or Số đếm (Lượt hiển thị, Lượt nhấp, Đơn hàng SKU, GMV or AOV; rates derived). VN number parsing
  ("50.000", "3,5", "1.234,5", "₫", "%"; a lone "3.5" reads as 3,5, "1.500" as 1.500). Vietnamese
  errors next to each field (`aria-invalid` + `aria-describedby`), focus to the first; empty state
  shows no result; "Thử ví dụ giả định" fills the post's 50.000 × 3 % × 4 % × 180.000 ₫ and labels it.
  Output: GMV in an `aria-live` region, funnel table, "+X % on each step" table (all four rows equal,
  default 10 %, editable), "Bước nào yếu nhất?" says plainly that one period cannot call a CTR low
  (no benchmark exists), then four step questions with where-to-look; a zero step is named as the
  blocker; a "Thử một thay đổi cụ thể" what-if (pick a metric, new value). No fetch, no storage, no
  new tracking (the CTA keeps the site's consent-gated listener). Privacy line under the H1.
- Links: footer "Sản phẩm" column (`FREE_TOOLS`), home FAQ column, `/san-pham/phan-tich-shop` funnel
  section. Not in the header dropdown (D46.1 lists four product pages). The "GMV là gì" post is a
  draft, so its links (title + four "Tăng …" anchors) render only once published (DEBT).
- Gates (Node 26 + `--no-experimental-webstorage`): lint 0, `tsc --noEmit` 0, vitest 17 files / 329
  passed (+55: `gmv-calculator.test.tsx`, heading outline +1), build OK (`/cong-cu/tinh-gmv` static),
  `check:seo` 22 passed. Playwright on `next start`: no horizontal overflow at 360 / 390 / 1440, zero
  network requests after calculating. Screenshots in the P43 scratchpad `shots-p43/`
  (tinh-gmv-{390,1440}-{empty,example}.png). `check.sh`: migrations / isolation FAIL (no throwaway
  DB; `docker info` hung and was killed), gitleaks PASS, ruff PASS, pytest 7 failed / 2889 passed
  (`test_agent_workflow_task_wiring.py`, known local limitation; no Python touched).
- Next: owner review, merge `--no-ff`. Note: 6d595c27 on its own fails the registry test (route
  without page); the branch tip is green.

## 2026-10-16 — P44 agent (Claude Opus) — three tools listicles naming competitors (D49.2)

- Branch `fasttrack/p44-tools-listicles` (from `fasttrack/optimize-product` e20e5394). Not merged, not pushed.
- **Posts (all `status: "draft"`, category `tools`, Vietnamese only)**:
  a. `phan-mem-quan-ly-ban-hang-da-kenh-2026`: BigSeller, Haravan, KiotViet, MISA eShop, Nhanh.vn,
     Pancake POS, Sapo (alphabetical). MISA eShop added to the owner's six: Google VN autocomplete
     "phần mềm quản lý bán hàng đa kênh misa eshop" and MISA pages lead the SERP for "phần mềm
     quản lý bán hàng tiktok shop" (this session's competitor research). No Juli in the body.
  b. `cong-cu-phan-tich-tiktok-shop-2026`: La bàn dữ liệu (TikTok Academy 10008597, 10015238),
     market research FastMoss, Kalodata, Metric; own-shop group: Juli once ("sản phẩm của chúng
     tôi", no superlatives), plus reports of multichannel software. Left out with reason in the
     post: EchoTik and Shoplus (no Vietnam on their public pages), Kalowave (Kalodata's operator,
     per Kalodata's FAQ, not a tool).
  c. `cong-cu-ai-tao-anh-video-san-pham-tiktok-shop`: Canva, CapCut, Higgsfield, Photoroom, Pippit
     ("do CapCut cung cấp"), TikTok Symphony Creative Studio (VN help article). Kling left out (plan
     page rendered no text). No Juli in the body.
  Each: selection criteria up front, a comparison table (who for, main functions, platforms, free
  tier as published), every tool section ends "Thông tin kiểm tra ngày 16/10/2026 trên trang chính
  thức của …", prices only as published (plan, currency, period; promos noted), no scores / stars /
  winner / rating schema, no "—", header comment lists sources. 3,3xx–3,6xx words each.
- Vendor pages read with curl text dumps and Chrome page text (read-only, no sign-up or log-in).
  Unreadable prices stated as such: MISA eShop (Báo giá only), Pancake POS (no table found),
  Kalodata (/pricing redirects to log-in).
- **Hub** `cong-cu-cho-nha-ban-tiktok-shop-2026`: one line each in sections 2, 3 and the AI section
  linking a, b, c; `updatedAt` 2026-10-16; still draft.
- **Covers**: `da-kenh-2026-v1`, `phan-tich-2026-v1`, `ai-anh-video-v1` (tiles, accents 0 / 2 / 5).
- **Test change** (`blog.test.tsx`): posts a and c (D49.2 "no Juli") are exempt from "links every
  product page"; instead they must link the hub, link no `/san-pham*` or `/ket-noi*`, and never
  contain "Juli". New per-post check: no "—" in body, title, seoTitle, description, excerpt, cover alt.
- Gates (Node 20.20.2): lint 0, `tsc --noEmit` 0, vitest 16 files / 298 passed, build OK,
  `check:seo` 24 passed. `check.sh`: migrations / isolation FAIL (no throwaway DB; `docker info`
  hung and was killed), gitleaks PASS, ruff PASS, pytest 7 failed / 2889 passed
  (`test_agent_workflow_task_wiring.py`, SQLAlchemy URL parse: known local limitation; no Python touched).
- Next: owner reviews the three drafts (`pnpm dev`, `/blog/<slug>`), re-checks prices before
  publishing (several are promotional), merge `--no-ff`.

## 2026-10-17 — orchestrator (Claude Opus) — D50 keyword map; batch 1 published

- Two Sonnet research agents read the Semrush SEO blog (keyword strategy, brand / AI search);
  notes kept outside the repo. Wrote `fasttrack/keyword-map.md` and D50.
- Owner approved publishing `gmv-la-gi-tiktok-shop` and `chi-so-tiktok-shop-ctr-ctor-aov`:
  status → published, publishedAt / updatedAt 2026-10-17. `blog.test.tsx` now follows each
  post's status instead of assuming the first post and the P39-B posts are drafts.
- Gates (apps/landing, NODE_OPTIONS=--no-experimental-webstorage): vitest 17 files / 359
  passed, build OK, check:seo 25 passed. Not deployed yet.

## 2026-10-17 — P45 agent (Claude Opus) — EB-shrunk group lift in Ops (D52)

- Branch `fasttrack/eb-lift` (worktree `/Users/macos/juli-fasttrack-eb-lift`), from 4f8d4b38.
  D52 added first (owner, 2026-10-17; Azevedo et al. 2019 winner's-curse guard).
- **Maths** (`group_stats.py` step 7, pure): `log_lift_of` reads `y = ln(1 + diff / (100 + m_c))`
  and `se` from the stored 90 % interval mapped the same way; `shrink_lift` gives
  `w·y + (1 − w)·μ`, `w = τ² / (τ² + se²)`, var `w·se² + (1 − w)²·var μ`, a 90 % interval in %;
  `estimate_prior` per lever × metric × channel: leave-one-out, a shop's groups combined by
  inverse variance, DerSimonian–Laird from `group_eb_min_groups` (3) draws, else N(0, 0.15²).
- **Stored**: `build_verdict` adds `primary.eb` (default prior; the pipeline runs in the shop's
  scope), so `metrics.*.primary.eb` and `ops_rule.primary.eb` come with it.
- **Cross-shop, Ops only**: migration `093_ops_group_lift_draws` adds `ops_group_lift_draws()`
  (SECURITY DEFINER, EXECUTE to `juli_ops` only; primary + `metrics` comparisons, no product rows).
  `GET /v1/ops/shops/{id}/groups` reads it inside the `ops_role` block `_shop` already opens (one
  statement more), then `apply_pooled_eb` re-shrinks every comparison in the response; only μ, τ, n
  leave it. The deferred phone cleanup re-parented onto 093 (12 test pins moved).
- **Ops UI** (`ops-card-groups.tsx`): "Lift đã co (EB): +x % [lo; hi] · lift thô +y % · theo n nhóm
  cùng loại / mức mặc định" under each result, tooltip "Điều chỉnh theo các nhóm cùng loại để tránh
  tin nhầm kết quả may mắn"; two new tunables in Cài đặt shop. Label, strength and the seller
  sentence untouched.
- **Docs**: MODULE.md, `docs/chi-so/ops-huong-dan-chi-so.md` §5.4, DEBT (SE optimistic for tiny
  groups; pooled prior not stored; per-shop tunables).
- Gates: `tests/unit/test_p45_eb_lift.py` 19 passed; p30 / p31 / p36 group suites + chi-so vocabulary
  passed; `test_ops_console_db.py` on Postgres 19 passed (juli_app refused on the new function; a
  tenant scope sees only its own groups; `ops_role` reads both). Demo (Node 26): vitest
  `src/components/ops` + `src/lib/ops` 14 files / 111 passed, `tsc --noEmit` 0, eslint 0 (needed
  `pnpm install --offline` for apps/demo + packages). mypy clean on the 4 source files.
  `check.sh --since fasttrack/optimize-product` on a throwaway Homebrew Postgres 16 in UTC
  (port 55445, removed after): **5/5 PASS** (migrations to 093, isolation 12, gitleaks, ruff 20
  files, pytest 26 files / 564 passed). Pre-existing, not touched: `test_import_boundaries`
  strict-baseline (same 7 edges on the base).
- Next: owner merges `--no-ff`, pushes, tags a deploy (the deploy runs migration 093).

## 2026-10-17 — P46-A agent (Claude Opus) — blog rules in code (D56 G1/G2, G5, G6)

- Branch `fasttrack/p46a-blog-rules` (worktree `/Users/macos/juli-fasttrack-p46a`), from fef8bfc7.
- **G1/G2** `apps/landing/src/content/blog/competitors.ts`: three rings with names + domains
  (direct: Sapo, Shopee "Tối ưu sản phẩm bởi AI" (no domain), Atosa, FastMoss, Kalodata, Metric;
  adjacent: Preny, Fchat, Botcake, AhaChat, Smax, Hana, Bizfly Chat, Harasocial, Pancake Inbox;
  not-competing: CapCut, Canva, Photoroom, Higgsfield, Pippit, KiotViet, Nhanh.vn, BigSeller,
  Haravan, MISA eShop, Pancake POS). `BlogSource` is now linked (`url`) or unlinked
  (`checkedAt`); the 36 vendor sources of the 4 tools posts use `vendor(title, checkedAt)` and
  render as text "Sapo (kiểm tra 15/10/2026)"; the post page also unlinks any registry href.
  Body: "Harasocial" dropped from the đa kênh post (adjacent ring). Pancake split by product
  (Inbox adjacent, POS not competing; same domains, both unlinked). Tools drafts `updatedAt`
  2026-10-17. Adjacent domains other than the listed vendors' were not verified (only used
  to block links).
- **G5** `format` on every post (pillar: gmv, chi-so, the-san-pham; pain: khong-ra-don,
  doanh-thu-giam; comparison: hub + 3 tools). Floors pillar / comparison 3,000, pain 1,500,
  news 800; caps pain 3,000 / news 2,000 hard for post-D56 posts only (the two pain posts are
  4,078 / 3,709 words, written to the old floor); ≥ 5 H2 (news ≥ 3); FAQ 3–5 for new pain /
  news posts; figures 0–8 per post. Tests: no registry link in body / sources, no direct name
  outside category tools, no adjacent name anywhere. README "Writing a post" = D56 standard.
- **G6** `scripts/seo/gsc_blog.py`, appended by `gsc_report.build` as section 8 (no launchd
  change): `/blog/*`, `/cong-cu/*` + every published post, 7 / 28 days, new queries, flags
  (≥ 100 impr & CTR < 1 %; position 11–20; query on ≥ 2 URLs; ≥ 56 days and `updatedAt`
  before the mark). Dates from `posts.ts` by regex (`JULI_BLOG_POSTS_TS` overrides).
- Gates: landing lint 0, `tsc --noEmit` 0, vitest 390 passed (`--maxWorkers=4`; full
  parallelism times out one random render test at 5 s, a different one each run, passes
  alone), build OK, `check:seo` 25 passed; pytest `test_gsc_blog.py` + `test_seo_scripts.py`
  27 passed; ruff clean. `check.sh --since fasttrack/optimize-product`: gitleaks, ruff,
  pytest PASS; migrations / isolation FAIL (no DB, `docker info` hung and was killed; known).
- Note for P46-B: the internal-link test still asks every non-listicle post (news too) to
  link `/san-pham` and the four product pages.
- Next: owner merges; P46-B writers use `format` and `vendor()`.

## 2026-10-17 — P46-B2 writer (Claude Opus 5.5): week-1 posts 3 and 4 (drafts)

- Branch `fasttrack/p46b2-week1-hienthi-thue` from `fasttrack/optimize-product` 848bb989.
  Commits ad494ff7 (6 diagrams desktop + phone, 2 covers), 6d214ca8 (test: news posts link
  `/san-pham` + one relevant page; README), 003469b1 (both drafts, figures, keyword-map rows).
- `/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi` (pain, 2,478 words, 5 figures incl. the
  `cap-dx-xac-nhan` screen, FAQ 5): bị ẩn (trạng thái per "Quản lý Sản phẩm" 27/08/2026) vs ít
  người thấy (Lượt hiển thị by five flows, read with CTR), day 7 / 14. No claim on how TikTok
  distributes impressions.
- `/blog/thue-ban-hang-tiktok-shop` (news, 1,202 words, 2 figures, FAQ 4, "Cập nhật ngày
  17/10/2026"): read from the official scans myself: NĐ 252/2026 Art. 43–46, 74; NĐ 68/2026
  Art. 3, 4, 11–13, 19; **NĐ 141/2026 (29/04/2026, in force 01/01/2026) changed every
  "500 triệu đồng" in NĐ 68 to "01 tỷ đồng"**, so the current threshold is 1 tỷ, not the
  500 triệu the brief had; Luật 09/2026/QH16 (threshold set by the Government); Luật 109/2025
  Art. 7.3.b (TNCN 0,5% for goods, on the part above the threshold), Luật 48/2024 Art. 12.2.b1
  (GTGT 1% for goods, checked in 12/VBHN-VPQH). NĐ 252 itself gives no rate. Not covered (not
  read): NĐ 174 / NQ 204 VAT reduction detail, Seller Center tax screens, chứng từ khấu trừ.
- Gates: lint 0, tsc 0, vitest 417 passed (`--maxWorkers=4`), build OK, check:seo 27 passed;
  both posts rendered at 390 / 1440 px, one H1, no horizontal overflow, figures loaded.
- Next: owner reviews and approves; re-check the tax post whenever NĐ 252 / NĐ 68 / the laws
  change (G6).
## 2026-10-17 — P46-B1 writer (Opus): week-1 posts 1–2, video and LIVE drafts

- Branch `fasttrack/p46b1-week1-video-live` (worktree `/Users/macos/juli-fasttrack-p46b1`), from 848bb989.
- Drafts (`format: "pain"`, category `guide`): `/blog/video-tiktok-nhieu-view-khong-ra-don`
  (main "video tiktok nhiều view không ra đơn", 2,462 words, 11 H2, 5 FAQ, 5 figures) and
  `/blog/live-tiktok-shop-khong-ra-don` (main "live tiktok shop không ra đơn", 2,443 words,
  11 H2, 5 FAQ, 5 figures). Neither reuses "tiktok shop không ra đơn"; both link it and each other.
- Sources re-opened 2026-10-17 in Chrome (TikTok Academy VN, cited with title + link): Tinh chỉnh
  GMV (4851723979097858), Lưu lượng truy cập sản phẩm (10015238), Hướng dẫn sử dụng La bàn Dữ liệu
  (6837786452313858), Phân Tích Hiệu Suất Video cho Nhà Sáng Tạo (6837828965697281), Phân tích dữ
  liệu LIVE của bạn (6837840206563073), Cẩm nang lưu lượng LIVE (512121839519504), Hiệu Suất LIVE
  (5477287655884545). Not claimed: how TikTok distributes views / LIVE impressions ("bóp" FAQ
  answers with the Academy's own "Chất lượng nội dung" check only); category preferences in the
  LIVE viewer profile (Academy: Indonesia / UK only).
- Figures: 8 new diagrams (`video-view-den-don`, `video-trieu-chung`, `video-truc-tiep-gian-tiep`,
  `video-sua-va-do`, `live-pheu`, `live-ba-goc-do`, `live-gpm`, `live-trong-sau`; "Ví dụ giả định"
  where numbers appear) + 2 screenshots reused after opening them: `cap-dl-tin-cay` (Video block,
  CTR down; id `video-ctr-du-lieu-mau`) and `cap-pt-luong` (tabs, LIVE under Nội dung; id
  `live-luong-du-lieu-mau`). Covers `video-view-v1`, `live-it-don-v1` (guide checklist, accents 1, 2).
- Juli copy follows /san-pham/* and D27: Juli drafts a video script / LIVE host script and basket
  order, the seller films or goes live; title / description written only after approval; no ads,
  no chat replies.
- `keyword-map.md`: two rows (Draft), competition Medium with SERP / autocomplete evidence.
- Gates: landing lint 0, `tsc --noEmit` 0, vitest 420 passed (`--maxWorkers=4`), build OK,
  `check:seo` 27 passed. Rendered both posts at 390 / 1440 px (1 H1, 5 figures each, all images
  loaded, no horizontal overflow, no "—"): screenshots in the session scratchpad `shots-p46b1/`.
  `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations / isolation
  FAIL (no DB, `docker info` hung and was killed; known).
- Next: owner reviews and merges; posts 3–4 of week 1.

## 2026-10-17 — P46-C2 writer (Claude Opus 5.5): week-2 posts 7 and 8 (drafts)

- Branch `fasttrack/p46c2-week2-huy-phi` from `fasttrack/optimize-product` 0e54c67b.
  Commits 5dd4fd9e (6 diagrams desktop + phone, covers `hoan-hang-v1` metrics/bars accent 1,
  `phi-san-2026-v1` guide/tiles accent 1), dbf0771a (both drafts, figures, keyword-map rows).
- `/blog/ty-le-hoan-hang-tiktok-shop` (pain, 2,473 words, 5 figures incl. a `cap-dx-xac-nhan`
  screen, FAQ 5): hủy đơn vs giao không thành công vs trả hàng / hoàn tiền; SFCR, SFRR, review
  window, who pays return shipping, fees not refunded. All facts from Vietnamese Học viện pages
  re-read 2026-10-17. Resolved: seller review window is "1 ngày theo lịch" ("Trả hàng và Hoàn
  tiền" 15/10/2026 and "Quản lý yêu cầu trả hàng" 04/11/2025; the 2024 FAQ's "ngày làm việc" is
  superseded). Left out: SFCR OVL tier thresholds (Vietnamese page starts at 10%, the brief's
  English multi-country read said 15%). Juli part limited to GMV reading (GMV incl. cancelled /
  refunded per TikTok) and title / description proposals written after approval; no claim on
  returns, disputes or logistics.
- `/blog/phi-san-tiktok-shop-2026` (news, 1,314 words, 2 figures, FAQ 4, "Cập nhật ngày
  17/10/2026"): fee stack from the dated fee pages; the two commission PDFs compared row by row
  (1,945 shared level-3 rows: 0 standard changes, 41 Mall decreases, all Sách). Real fee dates
  are in text and tables, not in figure alt; only the worked example figure carries "Ví dụ giả
  định". Main keyword switched to "phí sàn tiktok shop 2026" (autocomplete; the plan's term had
  none).
- Gates: lint 0, tsc 0, vitest 444 passed (`--maxWorkers=4`), build OK, check:seo 29 passed;
  both posts rendered at 390 / 1440 px (one H1, no horizontal overflow, all figures loaded).
- Next: owner reviews and approves; re-check post 8 after 20/10 and 21/10/2026 and whenever a
  fee page changes (G6).
## 2026-10-18 — P46-C1 writer (Opus): week-2 posts 5–6, CTOR and AOV drafts

- Branch `fasttrack/p46c1-week2-ctor-aov` (worktree `/Users/macos/juli-fasttrack-p46c1`), from 20cc1429.
- Drafts (`format: "pain"`, category `metrics`, because the guide checklist covers have no free accent):
  `/blog/khach-xem-nhung-khong-mua-tiktok-shop` (main "khách xem nhưng không mua tiktok shop",
  2,476 words, 11 H2, 4 FAQ, 5 figures; scope only the step after the click: CTOR by source,
  add-to-cart vs checkout, vouchers, shipping, indirect GMV) and
  `/blog/tang-gia-tri-don-hang-trung-binh-tiktok-shop` (main "tăng giá trị đơn hàng trung bình
  tiktok shop", the brief's variant; 2,485 words, 11 H2, 4 FAQ, 6 figures). Each says in its intro
  how it differs from `chi-so-tiktok-shop-ctr-ctor-aov` and `tiktok-shop-khong-ra-don`, links them,
  the week-1 posts (video, LIVE, lượt hiển thị) and each other. No H2 copies those posts' H2s.
- Sources re-opened 2026-10-17 (curl + text extraction, TikTok Academy VN, cited by title + link +
  page date): Lưu lượng truy cập sản phẩm (17/06/2026), Tinh chỉnh GMV (11/05/2026), Voucher Thông
  Thường (13/06/2025), Mua Sỉ Giá Hời (09/12/2025), Ưu Đãi Theo Gói (16/04/2024), Quà Tặng Khi Mua
  Hàng (05/01/2026), Chiết Khấu Phí Vận Chuyển (24/01/2025), Cách Tính Khuyến Mãi Cộng Dồn
  (29/10/2025), Phí Xử Lý Đơn Hàng (11/10/2025), Chẩn đoán giá (24/07/2026), Chẩn Đoán Thẻ Sản Phẩm 4
  (15/12/2023), Tiêu đề, mô tả, hình ảnh và video về sản phẩm (23/04/2026). Not used: any CTOR / AOV
  benchmark (none official), third-party "mua 2 giảm 5 %, freeship 499K" recipes.
- Figures: 7 new diagrams (`sau-cu-nhap`, `ctor-hai-luong`, `ctor-trieu-chung`, `aov-hai-shop`,
  `aov-phi-co-dinh`, `aov-cong-cu`, `aov-cong-don`) + 4 Dữ liệu mẫu screenshots opened before use
  (`cap-pt-xep-hang`, `cap-dl-tang-them`, `cap-pt-pheu`, `cap-pt-khuyen-mai`). Covers
  `khach-xem-khong-mua-v1` (metrics checklist, accent 1) and `gia-tri-don-v1` (metrics bars, accent 1).
- Juli copy follows /san-pham/*: title / description written only after approval; price, vouchers,
  bundles, shipping discounts are proposals the seller sets up in Seller Center; CTOR / AOV of a
  change measured on all channels; no chat replies, no ads.
- `keyword-map.md`: two rows (Draft). PROGRESS P46-C: posts 5–6 done on branch.
- Gates: landing lint 0, `tsc --noEmit` 0, vitest 478 passed (`--maxWorkers=4`), build OK,
  `check:seo` 31 passed. Rendered both posts at 390 / 1440 px (1 H1, all figures loaded, no
  horizontal overflow, no "—", robots noindex): screenshots in the session scratchpad `shots-p46c1/`.
  `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations / isolation
  FAIL (no DB; `docker info` hung and was killed; known).
- Next: owner reviews and merges; posts 7–8 (P46-C2).

## 2026-10-17 — P47 agent (Claude Opus) — group-verdict money metrics net of cancel / refund (D55.1)

- Branch `fasttrack/gmv-net` (worktree `/Users/macos/juli-fasttrack-gmv-net`) from 39fa0f04.
- **Data check.** Group verdicts read `analytics_performance_intervals` (grain product, daily):
  `gmv`, `sku_orders`, `items_sold` = TikTok GMV incl. cancelled / refunded orders; no cancel /
  refund column (`integrations/tiktok/mapping.py` `expand_analytics_product_list_item` /
  `expand_analytics_product_detail` drop A-34 `total_performance.refunds` and A-33
  `cancel_and_refunds`). The poll cycle does sync `silver.orders` (status, `tiktok_created_at`),
  `order_items` (product, quantity, `line_total`; keyed order × SKU) and `silver.returns`
  (`refund_amount`, `status`, `return_type`) — `workers/services/polling/orchestrate.py`
  `_FUJIWA_POLL_STEPS`, `sync.py` `sync_orders` / `sync_returns`. So net is derivable as shares.
- **Built** `services/action_cards/group_net.py` + `card_groups.py` wiring (net AOV / items per
  order for `metrics`, Ops-group primary, replay, guard, EB; `gross` beside; card-group primary
  and seller sentence unchanged, `net` beside; `verdict.basis`; plan `revenue_basis`,
  `gmv_net` / `orders_net`). Ops UI (`ops-card-groups.tsx`, `types.ts`). Ops chi-số guide §5.5 +
  glossary "Cách tính" notes. No migration (head stays 093).
- Gates: `test_p46_gmv_net.py` 13 passed; p30 / p31 / p36 / p45 / p46 + chi-số vocabulary 139
  passed (p36 label assertion updated to the gross label). One earlier combined run had a p31
  pytest-timeout (>30 s) while the disk briefly hit 0 bytes free and other agents loaded the host;
  re-run alone and combined: passed. `test_import_boundaries` strict-baseline fails identically on
  the base (pre-existing). mypy clean on the 2 source files. Demo (Node 26,
  `NODE_OPTIONS=--no-experimental-webstorage`, `pnpm install --offline`): tsc 0, eslint 0 on
  `src/components/ops` + `src/lib/ops`; vitest `src/components/ops` + `src/lib/ops` 15 files: 4
  tests timed out (5 s) under host load + 2 files failed to import before `packages/*` were
  installed; those files re-run alone 5/5 files 56 passed; touched files (p36, p46, pages) 25 passed.
  `check.sh --since fasttrack/optimize-product`, throwaway Homebrew Postgres 16 in UTC (port 55446,
  removed after): **5/5 PASS** (migrations to 093, isolation 12, gitleaks, ruff 4 files, pytest
  2 files / 35 passed).
- Next: owner merges `--no-ff`, pushes, tags a deploy (no migration).
## 2026-10-18 — P46-D2 writer (Claude Opus 5.5): posts 11–12, week 3

- Branch `fasttrack/p46d2-week3-mota-livestream` (from `fasttrack/optimize-product` at 017439b1).
- Post 11 `mo-ta-san-pham-tiktok-shop` (pain, optimize, 2,227 words, 5 figures, FAQ 5): the
  description as a pre-answer to repeated buyer questions. Main keyword "mô tả sản phẩm tiktok
  shop" (autocomplete VN 2026-10-18), moved off the pillar's supporting list; the pillar's
  description section now links down in one sentence. Facts re-opened 2026-10-18 on
  seller-vn.tiktok.com: listing policy (23/04/2026), Hướng dẫn đăng bán 3.1.1–3.1.5 (05/10/2026),
  phóng đại (29/06/2025), chuyển hướng truy cập (10/06/2026), SNAD (18/06/2025), bảng kích cỡ
  thời trang (01/10/2026), thông tin sai lệch / AIGC (30/09/2026), Trình Tối Ưu Hoá (04/08/2025),
  return policy (23/09/2026) and Trả hàng (15/10/2026). Juli copy per /san-pham/*: Juli does not read
  buyer messages, so the seller lists the questions and return reasons; Juli drafts after a card is
  approved, writes only after confirmation, keeps the old value for undo, measures CTOR day 7 / 14.
- Post 12 `quy-dinh-livestream-ban-hang` (news, guide, 1,495 words, 2 figures, FAQ 5, "Cập nhật
  ngày 18/10/2026", not legal advice): built from the Công báo PDFs re-read 2026-10-18 (Luật
  122/2025/QH15 Art. 3, 22–24, 40; NĐ 248/2026 Art. 12, 52; Luật 75/2025 Art. 15a; NĐ 87/2026 Art. 6,
  51, 93; Luật 19/2023 Art. 3.9, 22.3, 79) plus the TikTok Policy Center page (01/07/2026), labelled
  as TikTok's policy. Left out: legal list of goods needing an ad-content certificate, who counts as
  người có ảnh hưởng, fines for Art. 22–24. One Juli line (drafts LIVE host scripts, per
  /san-pham/de-xuat-va-thuc-thi) + soft CTA.
- Diagrams `mo-ta-nam-nhom-cau-hoi`, `mo-ta-truoc-sau`, `mo-ta-duoc-khong-duoc`,
  `livestream-ba-vai`, `livestream-luat-va-tiktok` (desktop + phone); screenshots reuse
  `cap-dl-tang-them`, `cap-dx-xac-nhan`. A fines diagram was dropped: legal numbers in an alt trip the
  "Ví dụ giả định" rule, so the fines are a table in the text. Covers `mo-ta-san-pham-v1` (optimize
  checklist, accent 1), `quy-dinh-livestream-v1` (guide tiles, accent 3). Post 11 added to FIGURE_POSTS.
- Gates: lint 0, `tsc --noEmit` 0, vitest 532 passed, build OK, `check:seo` 35 passed; rendered at
  390 / 1440 (1 H1, figures loaded, no overflow), screenshots in scratchpad `shots-p46d2/`.
  `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations / isolation
  FAIL (no DB, known; a hung `docker info` was killed).
- Next: owner review; merge with P46-D1 (posts 9–10; keyword-map pillar row touched by both).
## 2026-10-18 — P46-D1 writer (Opus): week-3 posts 9–10, title and cover-image drafts

- Branch `fasttrack/p46d1-week3-tieude-anhbia` (worktree `/Users/macos/juli-fasttrack-p46d1`), from 017439b1.
- Drafts (`format: "pain"`, category `optimize`): `/blog/dat-ten-san-pham-tiktok-shop` (main "đặt tên
  sản phẩm tiktok shop", per the brief; plan phrase "cách đặt tiêu đề…" kept in H1 / first H2 only;
  2,404 words, 9 H2, 5 FAQ, 5 figures) and `/blog/anh-bia-san-pham-tiktok-shop` (main "ảnh bìa sản
  phẩm tiktok shop"; opening separates the main product image from a video cover; 2,430 words,
  10 H2, 5 FAQ, 4 figures). Autocomplete VN re-checked 2026-10-18. The pillar links down to both in
  one sentence each; both link the pillar, each other, chỉ số, khách-xem-nhưng-không-mua, lượt hiển
  thị and the product pages.
- Sources re-opened 2026-10-18 (curl + text extraction, seller-vn.tiktok.com, title + link + page date):
  Tiêu đề, mô tả, hình ảnh và video về sản phẩm (23/04/2026), Hướng dẫn đăng bán sản phẩm (05/10/2026),
  Chẩn Đoán Thẻ Sản Phẩm 4 (15/12/2023), Chẩn Đoán Thẻ Sản Phẩm (21/02/2024), Trình Tối Ưu Hóa Tiêu Đề
  (23/11/2023), Trình Tối Ưu Hoá Sản Phẩm (04/08/2025), Đăng Sản Phẩm và Chỉnh Sửa Ảnh trên App
  (06/06/2025), nội dung tạo bởi AI (30/09/2026), Clickbait (29/06/2025), Mô tả phóng đại (29/06/2025),
  Cập nhật Chính sách mới nhất (01/07/2026, brand-masking rule from 28/05/2026), Lưu lượng truy cập
  sản phẩm (17/06/2026). Confirmed: "dài hơn 25 ký tự", "lớn hơn 1200*1200" + "ít nhất 3 hình ảnh"
  (recommendations), 600 × 600, max 9 square images, 60 % of frame. Not found on any official page:
  "900 × 900" and an image "5 MB" limit (5 MB is the video limit); the post says so, states neither.
- Juli scope: title written only after approval, old title stored for undo, day 7 / 14. Cover image:
  per the P46-D brief Juli does not shoot, edit or upload images, only proposes; SPEC does not say
  Juli records when an image changed, so the post asks the seller to note the date. Note for the
  owner: `/san-pham` and `/san-pham/de-xuat-va-thuc-thi` still say Juli uploads a seller-supplied
  cover photo (D13); the post follows the brief, the two should be reconciled.
- Figures: 6 new diagrams (`tieu-de-hai-viec`, `tieu-de-nam-thanh-phan`, `tieu-de-truoc-sau`,
  `anh-bia-tren-the`, `anh-bia-ba-phuong-an`, `anh-bia-doi-chung`), reused `hien-thi-ctr`, and two
  Dữ liệu mẫu screenshots opened before use (`cap-dx-luot-chay`: title written, old value stored,
  day 7 / 14; `cap-pt-pheu`: product-card CTR). A seventh diagram (official image requirements) was
  dropped: its official numbers trip the test's hypothetical-number rule; the body lists them.
  Covers `dat-ten-san-pham-v1` (optimize checklist, accent 1), `anh-bia-san-pham-v1` (optimize
  tiles, accent 0). Both slugs added to `FIGURE_POSTS`.
- `keyword-map.md`: two rows (Draft); "tối ưu tiêu đề" moved from the pillar to post 9. PROGRESS
  P46-D: posts 9–10 done on branch.
- Gates: landing lint 0, `tsc --noEmit` 0, vitest 533 passed (`--maxWorkers=4`), build OK,
  `check:seo` 35 passed. Rendered at 390 / 1440 px (1 H1, no horizontal overflow, all figures
  loaded); figure screenshots in the session scratchpad `shots-p46d1/`. `check.sh --since
  fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations / isolation FAIL (no DB;
  hung `docker info` killed; known).
- Next: owner reviews and merges; posts 11–12 (P46-D2).
- Follow-up: cover-photo conflict resolved in favour of D13 (coordinator): post 10 now says Juli uploads the seller-supplied photo as the main image after confirmation, keeps the old one for Hoàn tác (per /san-pham/de-xuat-va-thuc-thi), records the date and measures day 7 / 14; a seller who swaps it in Seller Center notes the date.
## 2026-10-18 · P46-E writer (Claude Opus 5.5) · month-1 posts 13–14 (week 4, Measurement)

- Branch `fasttrack/p46e-week4-do-luong-sale` (from `fasttrack/optimize-product` 017439b1). Two
  `pain` drafts: `/blog/do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop` (main "đo hiệu quả sau khi
  sửa sản phẩm", 2,479 words, 9 H2, 5 FAQ, 6 figures) and `/blog/doanh-thu-sau-sale-tiktok-shop`
  (main "doanh thu sau sale tiktok shop", lead supporting "sale 11.11 tiktok shop" in H1 / title,
  2,483 words, 10 H2, 5 FAQ, 6 figures). Autocomplete VN re-checked 2026-10-18: both main terms
  empty; "sale 11.11 tiktok shop" → "tiktok shop 11.11 sale"; "lịch chiến dịch tiktok shop" →
  "… 2026".
- Method copy follows SPEC §4 P6, D14, D29, D30, D31.7, D34 and `/san-pham/do-luong-gmv`: 14-day
  baseline frozen at apply, per-day averages, one target metric on the lever's channel, guard
  bands, day 7 Đang lên / Chưa rõ, day 14 four labels, ≥ 2× / 1–2× / < 1× band, "Bị ảnh hưởng bởi
  thay đổi khác", control groups experimental, Rõ / Tham khảo at ~30 orders. Nothing in SPEC / D30
  handles platform sale days, so both posts say Juli does not detect or exclude them; the seller
  marks them. No uplift figure quoted (SERP "+30 % / +25 %" excluded).
- Sources re-opened 2026-10-18 (curl + text; Q4 calendar image downloaded and read): Lịch Chiến
  Dịch TikTok Shop 2026 (16/10/2026: 10.10 07–10/10, giữa tháng 13–15/10, lương về 24–25,
  11.11 03–15/11, Black Friday 26–27/11, 12.12 03–15/12; registration "Seller Center hoặc quản lý
  gian hàng", rules not stated, so not written), Lưu lượng truy cập sản phẩm (17/06/2026), Trả hàng
  và Hoàn tiền (15/10/2026), Phí Xử Lý Đơn Hàng (11/10/2025), Trình Tối Ưu Hoá Sản Phẩm
  (04/08/2025), Chẩn Đoán Thẻ Sản Phẩm (21/02/2024).
- Finding: from late October to mid December 2026 there is almost no 28-day window free of a big
  sale; post 13 says so and points to the unchanged-product comparison.
- Figures: 9 new diagrams (`do-lich-14-ngay`, `do-doc-sai-doc-dung`, `do-ba-ket-qua`,
  `do-cua-so-sale`, `sale-ba-pha`, `sale-ghi-truoc`, `sale-theo-luong`, `sale-ba-nhom`,
  `sale-gmv-con-lai`) + 3 Dữ liệu mẫu screens opened first (`cap-dl-muc-tieu`, `cap-dl-ngay-14`,
  `cap-pt-khuyen-mai`). Real campaign dates kept in text, not in figure alts. Covers
  `do-hieu-qua-v1` (metrics checklist accent 0) and `sau-sale-v1` (metrics tiles accent 3), both
  unused pairs. Both slugs in `FIGURE_POSTS`. `doanh-thu-tiktok-shop-giam` sale bullet now links
  post 14 (brief); week-3 posts 9–11 not linked (not on this branch).
- `keyword-map.md`: two rows; "đo hiệu quả sửa sản phẩm" moved off `/san-pham/do-luong-gmv`.
- Gates: landing lint 0, `tsc --noEmit` 0, vitest 537 passed (`--maxWorkers=4`), build OK,
  `check:seo` 35 passed; both posts at 390 / 1440 px: 1 H1, 6 figures loaded, no horizontal
  overflow. `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations /
  isolation FAIL (no DB; hung `docker info` killed; known). Screenshots (390 / 1440 px, 24 figure shots) in the
  session scratchpad `shots-p46e/`.
- Next: owner reviews; post 14 must be approved before 03/11/2026 and revised after 15/11.

## 2026-10-18 · P48-A reach / conversion tiers in code (D59.1, D59.2)

- Branch `fasttrack/p48a-tiers` from `fasttrack/optimize-product` @ 1281cf1e. Infrastructure only:
  no post body changed.
- `blogTier(post)` / `FORMAT_TIER` (`content/blog/index.ts`): pain, news → `reach`; pillar,
  comparison, new `guide` → `conversion`. Derived from `format`, not a field. `BlogTier` type;
  `guide` format: 1,500–3,000 words, 5+ H2, FAQ 3–5, figures 3–8.
- Post page: reach posts end with a neutral dark box `blog-cta-tool` ("Tự tính GMV và tìm bước yếu
  nhất", lead about the free calculator, button "Mở công cụ tính GMV" → `/cong-cu/tinh-gmv`,
  secondary "Đọc thêm bài viết" → `/blog`); conversion posts keep the Juli trial + demo CTA. No
  other Juli copy in the template besides the byline (author) and related cards.
- Tests (`blog.test.tsx`, "reach vs conversion tier (D59)"): tier mapping; every reach post renders
  `blog-cta-tool`, no `blog-cta-trial` / `-demo`, no "Juli" in the box; for reach posts not in
  `REACH_JULI_PENDING`: no "Juli" in body / title / seoTitle (minus " | Juli AI") / description /
  excerpt / breadcrumb / cover alt / FAQ / figure alt+caption, no screenshot figures, no links to
  `/san-pham*`, `/ket-noi*`, `/dang-ky`, the demo or app-juli.com, and the rendered `<main>` minus
  byline and related cards has no "Juli". Internal-link test: reach posts need 2+ distinct onward
  links (other posts or the calculator) instead of product pages. With the pending list empty, 33
  tests failed (16 × body rules, 16 × rendered page, 1 onward-link: `thue-ban-hang-tiktok-shop`);
  with all 16 reach slugs pending the suite is green. A pending slug that is already clean fails.
- README: "Reach vs conversion (D59)" section; format table + figures / FAQ / links updated.
- Gates: lint 0, `tsc --noEmit` 0, vitest 611 passed / 32 skipped (`--maxWorkers=4`), build OK,
  `check:seo` 39 passed. `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS;
  migrations / isolation FAIL (no DB; hung `docker info` killed; known).
- Next: P48-B/C strip Juli from the reach posts and remove their slugs from `REACH_JULI_PENDING`.

## 2026-10-18 · P48-B strip Juli from 8 reach posts (D59.1)

Branch `fasttrack/p48b-reach-strip-1` (from `fasttrack/optimize-product` 081dfca9), not merged.

- Posts: `tiktok-shop-khong-ra-don`, `doanh-thu-tiktok-shop-giam`,
  `san-pham-tiktok-shop-khong-co-luot-hien-thi`, `thue-ban-hang-tiktok-shop`,
  `video-tiktok-nhieu-view-khong-ra-don`, `live-tiktok-shop-khong-ra-don`,
  `ty-le-hoan-hang-tiktok-shop`, `phi-san-tiktok-shop-2026`. Every Juli mention (body, FAQ),
  each "Juli AI giúp gì" section, trial CTA line and link to `/san-pham*`, `/ket-noi*`, `/dang-ky`
  removed. Juli's data floors (CTR 50 lượt hiển thị / CTOR 20 lượt nhấp / 30 đơn) are now "a
  threshold you set", given as a "Ví dụ giả định".
- New seller-side sections: "Tự theo dõi phễu mỗi tuần", "Bảng theo dõi doanh thu mỗi tuần",
  "Tự kiểm tra lượt hiển thị mỗi tuần", "Theo dõi doanh thu cả năm" (H3), "Bảng theo dõi video
  mỗi tuần", "Sổ theo dõi các buổi LIVE", "Bảng theo dõi hủy và hoàn mỗi tuần", "Tự đối chiếu phí
  mỗi tháng" (H3). Only Seller Center fields and facts already cited in each post.
- Figures: 8 `cap-*` screenshot figures deleted from `figures.ts` (pt-xep-hang, pt-pheu, pt-video,
  pt-xep-hang-doanh-thu, dx-xac-nhan-tieu-de, video-ctr-du-lieu-mau, live-luong-du-lieu-mau,
  dx-xac-nhan-mo-ta; unused `CAP_DL_TIN_CAY` import dropped); `checklist-khong-ra-don` diagram
  dropped (duplicated the table; 7 → 6 figures); `doc-pheu-o-dau` re-rendered as v2 (image said
  "Juli"), v1 files and the checklist files deleted.
- `related` now favours reach posts + the GMV pillar; `updatedAt` 2026-10-18; 8 slugs out of
  `REACH_JULI_PENDING` (8 left for P48-C).
- Words: khong-ra-don 4,245; doanh-thu-giam 3,868; khong-co-luot-hien-thi 2,464; thue 1,283;
  video 2,445; live 2,423; ty-le-hoan 2,460; phi-san 1,417. Onward links 3–8 per post.
- Gates: lint 0, `tsc --noEmit` 0, vitest 618 passed / 16 skipped, build OK, `check:seo` 39
  passed; 390 px render of khong-ra-don and phi-san: neutral calculator box, no "Juli" in `<main>`
  outside byline / related, no horizontal scroll. `check.sh --since fasttrack/optimize-product`:
  gitleaks, ruff, pytest PASS; migrations / isolation FAIL (no DB; hung `docker info` killed; known).
## 2026-10-18 · P48-C strip Juli from 8 reach posts (D59.1)

- Branch `fasttrack/p48c-reach-strip-2` (from `fasttrack/optimize-product` 081dfca9), not merged.
- Posts: `khach-xem-nhung-khong-mua-tiktok-shop`, `tang-gia-tri-don-hang-trung-binh-tiktok-shop`,
  `mo-ta-san-pham-tiktok-shop`, `quy-dinh-livestream-ban-hang`, `dat-ten-san-pham-tiktok-shop`,
  `anh-bia-san-pham-tiktok-shop`, `do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop`,
  `doanh-thu-sau-sale-tiktok-shop`. Each "Juli AI giúp gì" section replaced by seller-side guidance
  (self-kept Seller Center sheets / routines from the sources already cited); Juli trial CTA lines and
  product / connect / sign-up links removed; "Juli's rule" thresholds reworded as our practice rules.
  `do-hieu-qua` rewritten as a method the seller applies (no Juli labels: day 7 đang lên / đi ngang /
  đang giảm, day 14 giữ / đo thêm / sửa tiếp / quay lại; mức mong đợi written before the change;
  optional "sửa sau 14 ngày" group by lot). FAQs: Juli answers replaced (ảnh bìa, mô tả, đặt tên,
  đo hiệu quả ×3). `related` favours reach posts + `gmv-la-gi-tiktok-shop`; updatedAt 2026-10-18.
- Figures: 11 `cap-*` screenshot figures removed from `figures.ts` (used only by these posts; 4 unused
  CAP_* imports dropped); `do-lich-14-ngay` and `do-ba-ket-qua` re-rendered as v2 without Juli labels
  (v1 files deleted). Figure counts 3–5 per pain post, 2 for the news post.
- Gates: lint 0, `tsc --noEmit` 0, vitest 616 passed / 16 skipped (the 8 still-pending P48-B slugs),
  build OK, `check:seo` 39 passed; 390 px spot-render of `do-hieu-qua` and `anh-bia`: neutral
  calculator box, no "Juli" in `<main>` outside byline / related cards, no horizontal overflow.
- `check.sh --since fasttrack/optimize-product`: gitleaks, ruff, pytest PASS; migrations / isolation
  FAIL (no throwaway DB; one hung `docker info` killed after 2 min; known).

## 2026-10-18 · P48-H unique hero per blog post (D59.3)

- Content engine (`juli-content-engine`, branch `blog-heroes`, not pushed): new still `BlogHero`
  (1200×675 at `--scale=2` → 2400×1350) + `BlogHeroOG` (1200×630, own side-by-side layout), 23 vector
  motifs (one metaphor per post, own palette from the landing tokens, left / right / centre), kicker in
  Be Vietnam Pro latin + vietnamese; specs in `projects/blog-heroes/heroes.json`;
  `npm run hero:render -- <heroes.json> [--only] [--contact-sheet]`. Commits d980b58, c81b11c.
- Landing, branch `fasttrack/p48h-heroes` (from `fasttrack/optimize-product` 52f91f63), not merged:
  `media.py blog-hero` (size check, never overwrites) wrote `blog-hero-<slug>-v1-{600,1200}.{avif,webp}`
  + `-og.png` for all 23 posts; every `cover` points at it with a new Vietnamese alt describing the
  illustration (no "Juli"). The 115 old shared-motif cover files and `scripts/blog-covers.mjs` are
  removed (referenced only by `posts.ts` and history in this log). README "Hero images" section.
- Weight: 600-wide AVIF set 41.7 KB → 136.9 KB for 23 cards (3.9–7.9 KB each; the published index
  shows 2 cards); all new cover files 2.0 MB (old 0.49 MB), OG PNGs ~45 KB each.
- Gates: lint 0 (6 old warnings), `tsc --noEmit` 0, vitest 623 passed (with `--testTimeout=30000`; at
  5 s one or two render tests timed out at load ~25, pass in isolation), build OK, `check:seo` 39
  passed; `/blog` and 2 posts rendered at 390 / 1440 px. `check.sh --since fasttrack/optimize-product`:
  first run stuck in migrations (docker hung host-wide, stopped after 10 min); rerun with
  `--skip-migrations`: gitleaks, ruff, pytest PASS, migrations / isolation SKIPPED.
- Note: a `git stash` / `pop` probe popped an unrelated old stash (conflict in docs/adr/README.md);
  undone with `git reset --merge`, the stash entry is still in the list (same trap as before).

## 2026-10-18 — P49-S fresh sample-shop screenshots (agent: Claude Opus, branch `fasttrack/p49s-screenshots`)
- Branch from `fasttrack/optimize-product` b2b553f2; assets commit 798afcfc. Not merged.
- **How**: `apps/demo` `next dev` (Node 20) with placeholder `NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co`
  / anon key `example-anon-key-not-a-secret` (only so the auth buttons render as links; no request is
  ever sent), driven by a scratchpad Playwright script at 1280 px, deviceScaleFactor 2, `vi-VN`,
  Asia/Ho_Chi_Minh. Every request off localhost was aborted. Three views: (1) the signed-out sample
  (most shots); (2) signed-in over Playwright `page.route` stubs, fake token, shop "Cửa hàng Mẫu Hoa
  Mai", the bundled `sampleEnvelope()` for Phân tích, rules like the sample's, onboarding step 2/3 (the
  P17 e2e pattern), for the quick scan and the CTR title card, which the bundled sample has no card
  for (KD-030 title / CTR 3,7 → 3,9 %, matching the sample's CTR ranking; GMV method text = backend
  `_GMV_METHOD_VI["ctr"]`); (3) the partner-reviewer sample (mocked `/v1/reviewer/me`, `shop: null`)
  only to reach "Ngày 14 (mô phỏng)": the day-14 shot is the measure panel alone, no reviewer banner.
  No production data, credentials or real shop.
- **New files** (`public/media/`, `media.py optimize` 640 + largest; exports in
  `components/product/screens.ts` after the v1 block): `cap-kn-dang-nhap-v2` (D44.5 / D47.6 sign-in
  column only, 1280×1745; right panel left out, see below), `cap-kn-quet-nhanh-v2` (strip "bước 2/3",
  quick-scan chip, 1280×869), `cap-pt-nghen-v2` (Thẻ sản phẩm, CTOR cell, the three rows with "Xem đề
  xuất", cropped above the two "Chưa có đề xuất" rows, 1280×595), `cap-dx-the-v2` (MN-015 description
  card expanded, 1184×868), `cap-dx-anh-bia-v1` (SR-007 cover card, 1184×1034),
  `cap-dx-anh-bia-tai-len-v1` (run waiting for the seller's photo with the 3 requirements and "Chọn ảnh
  từ máy", 1280×1208), `cap-dx-ctr-tieu-de-v1` (1184×1046), `cap-dl-ngay-7-v2` (1280×1565),
  `cap-dl-ngay-14-v2` ("Đạt", final box, 1280×1821), `cap-dx-hoan-tac-v2` (undo dialog, rounded alpha
  corners, 1040×1060). Mobile crops (`MOBILE_CROPS`, now any `-vN-` name): kn-dang-nhap-m-v2 720×931,
  kn-quet-nhanh-m-v2 678×799, pt-nghen-m-v2 720×297, dl-ngay-7-m-v2 720×250, dl-ngay-14-m-v2 720×191;
  cards and the dialog need none (2x, large text). v1 files and exports untouched.
- **Skipped**: `cap-pt-lich-sale` v2. The sample report's `end` is fixed at 2026-10-06, so "Sắp tới"
  is always "10.10, 11.11" (10.10 is past today); not capturable without changing the sample.
- **App copy for the owner (not edited)**: (a) SR-007 cover card chip "Juli tải lên — cần ảnh từ bạn"
  (em dash); (b) sample run step "Ảnh bìa đạt chuẩn — không đổi" (`sample-data.ts`); (c) sample
  SM-012 proposal title "Son môi lì cao cấp số 12 — màu đỏ ruby", also baked into the demo auth
  screen's right-panel image (`apps/demo/public/auth/`, the old cap-dx-the with "TikTok báo mã chẩn
  đoán"), which is why the sign-in shot is the column only; (d) "Chưa đặt quy tắc nào — Juli dùng mặc
  định." when rules are empty; (e) the sample's CTR card (SR-007) shows the CTOR formula — sample
  `GMV_METHOD` is one string for every KPI, the backend has one per KPI; (f) day-14 sample band row
  "155.000 – 165.000" vs "155k – 165k ₫" elsewhere (`sampleSimulatedMeasurement`).
- Gates (landing): lint 0 errors (6 pre-existing unused-import warnings in `figures.ts`), `tsc
  --noEmit` 0, vitest 17 files / 623 passed (Node 26, `NODE_OPTIONS=--no-experimental-webstorage`,
  `--maxWorkers=4`), build OK (Node 20); ruff on `media.py` clean. Contact sheet in the session
  scratchpad `shots-p49s/contact.png`.
- Next: P49-A/B writers use the `*_V2` / new exports; owner decides on the copy items above.

## 2026-10-18 · P49-F demo copy fixes + recapture (agent: Claude Opus, branch `fasttrack/p49f-demo-copy`)
- Branch from `fasttrack/optimize-product` 8eda6de8. Commits 5e981b18 (demo), 57260f97 (landing). Not merged.
- **Em dashes (D46.4) in `apps/demo/src`**: every prose " — " in UI strings and sample data (≈200 lines,
  58 files incl. the legacy recommendations / workflows / settings fixtures and Ops screens) became ", ",
  ": " (IDs, "FBT", "Unresolved", "Chưa xác định", headings), parentheses for ID + name mid-sentence, or a
  split sentence. Owner items: chip "Juli tải lên · cần ảnh từ bạn" (matches "Juli soạn · bạn làm");
  "Ảnh bìa đạt chuẩn, không đổi"; "Son môi lì cao cấp số 12, màu đỏ ruby"; "Chưa đặt quy tắc nào, Juli
  dùng mặc định."; also "Hoàn tất, không đổi", "Juli không tự hoàn tác, bạn quyết định.", aria "Juli:
  Trang chủ", logo label "Juli AI, về trang chủ app-juli.com". Lone "—" empty-value placeholders (table
  cells, `DASH` constants) are left: a glyph for "no value", not punctuation. Comments untouched.
  `dictionary.md` entries (3) and 13 test assertions follow the new text.
- **Formula**: sample `GMV_METHOD` is now per KPI (ctr / ctor / aov), text copied from the backend's
  `_GMV_METHOD_VI` (`services/demo_decisions/card_view.py`); SR-007 shows the CTR formula.
- **Day 14**: `sampleSimulatedMeasurement` writes vnd bands as "155k – 165k ₫" (count bands unchanged).
- **Auth panel**: `public/auth/cap-dx-the-v1-{640,1186}` (old card with "—" and "TikTok báo mã chẩn
  đoán") replaced by `cap-dx-the-v2-{640,1184}` (copied from landing media, 1184×868; the panel is
  `object-fit: cover` 360 px high, so any ratio fits); `<img>` width/height updated; alt now "Thẻ đề xuất
  của Juli: Mặt nạ đất sét 100g, CTOR 5,4 % lên 5,9 % (dữ liệu mẫu)".
- **Recapture** (P49-S scripts, copied to the session scratchpad `p49f/shots/`; same safety: localhost
  only, placeholder Supabase env, sample shop / mocks). All 10 shots re-run and pixel-diffed against the
  published files: changed text only in sign-in, SR-007 cover card and day 14. New names (media is
  cached immutable): `cap-kn-dang-nhap-v3` (full 1280 viewport with the right panel, 1280×900; mobile
  crop `-m-v3` 720×943 cut from the 2x raw), `cap-dx-anh-bia-v2` (1184×1034), `cap-dl-ngay-14-v3`
  (1280×1821, mobile `-m-v3` 720×191 via `media.py mobile-crops`). Superseded files were referenced only
  by `screens.ts` and are removed; export names unchanged, paths/sizes updated. Unchanged, not
  recaptured: `cap-dx-anh-bia-tai-len-v1` (timestamps only; the chip is not in the run view),
  `cap-dx-ctr-tieu-de-v1` (its mocked card already had the CTR formula), dx-the-v2, dl-ngay-7-v2,
  pt-nghen-v2, kn-quet-nhanh-v2, dx-hoan-tac-v2.
- Gates: demo lint 0 errors (7 old warnings), `tsc --noEmit` 0, vitest 159 files / 1991 passed;
  landing lint 0 errors (6 old warnings), tsc 0, vitest 17 files / 623 passed (Node 26,
  `NODE_OPTIONS=--no-experimental-webstorage --maxWorkers=4`), build OK (Node 20); ruff `media.py` clean.
- Goes live on the next owner deploy tag.

## 2026-10-18 · P49-A2 conversion drafts C5–C8 (agent: Claude Opus, branch `fasttrack/p49a2-guides-problems`)
- Branch from `fasttrack/optimize-product` d9f6dbaf. Commits 9c632546 (bodies + hero covers), c237bbcf (17
  screenshot figures), 25323dd3 (posts.ts, bodies/index.ts, FIGURE_POSTS), af50ec8a (keyword-map rows). Not merged.
- Four `format: "guide"` drafts, all `status: "draft"`: `dung-thu-juli-ai-mien-phi-3-thang` (C5, ~2,080 words,
  5 figures), `tim-san-pham-keo-gmv-xuong-tiktok-shop` (C6, ~2,070, 4), `ctr-the-san-pham-thap-doi-tieu-de-anh-bia`
  (C7, ~2,020, 5), `ctor-thap-viet-lai-mo-ta-san-pham` (C8, ~2,110, 3). FAQ 4–5 each. Screenshots only P49-S/F v2/v3
  shots plus cap-pt-luong / pt-pheu / pt-xep-hang / pt-khuyen-mai; no pt-nghen v1, dx-the v1. Trial facts only from
  /terms §5, /dang-ky copy and D43 additions 2; PROPOSED P33-F items (retention 12 months / 30 days, Ops access) left out.
- Heroes: `juli-content-engine-heroes/projects/blog-heroes/heroes-p49a2.json`; four NEW motifs (sprout-pots,
  anchor-balloons, magnet-pointers, quill-scroll) had to be added to `my-video/src/stills/blog-hero/{spec,motifs}.ts(x)`
  there, uncommitted (heroes.json untouched). Converted with `media.py blog-hero` → `blog-hero-<slug>-v1-*`.
- Conflicts noted (owner): sample day-7 / day-14 shots (TN-021) show "Đã đổi Tiêu đề" with a CTOR target, against the
  product pages' lever map (title → CTR), so they are used only in C5; sample Kéo xuống rows sum to −278k (264k + Còn
  lại 14k) while the tile and "Tổng" say −250k, so no sum is quoted; cards say "CTOR · Thẻ sản phẩm" while
  /san-pham/do-luong-gmv says CTOR is measured on all channels (C8 follows the page); /privacy already states the
  PROPOSED 12-month retention; /terms says "500.000đ/tháng", home says "từ 500.000đ/tháng" (posts use /terms).
- Gates (landing): lint 0 errors (2 old warnings, was 6), tsc 0, vitest 17 files / 680 passed (Node 26,
  `NODE_OPTIONS=--no-experimental-webstorage`, `--maxWorkers=4`), build OK + check:seo 43 passed (Node 20);
  `check.sh --since fasttrack/optimize-product --skip-migrations` OK. Shots 390 / 1440 in the session scratchpad
  `shots-p49a2/` (no horizontal scroll at 390).
- Next: P49-L end-of-post box links from the reach posts; owner review of the four drafts.
## 2026-10-18 — P49-A1 guide drafts C1–C4 (agent, Claude Opus 5.5)

- Branch `fasttrack/p49a1-guides` from `fasttrack/optimize-product` d9f6dbaf. Four `format: "guide"` drafts,
  natural Vietnamese, per the conversion plan C1–C4 and D59 additions 5: `huong-dan-ket-noi-tiktok-shop-voi-juli`
  (2,576 words, 4 figures), `doc-phan-tich-tiktok-shop-theo-luong-truy-cap` (2,568, 4),
  `duyet-de-xuat-toi-uu-san-pham-tiktok-shop` (2,726, 7), `do-ket-qua-ngay-7-ngay-14-hoan-tac` (2,451, 4); FAQ 5
  each; links to `/san-pham`, the three capability pages, `/ket-noi/tiktok-shop`, `/dang-ky` (C1 only), the pillars
  and each other. Figures are new `hd-*` screenshot entries in `figures.ts` (v2/v3 sample shots; no `cap-pt-nghen`
  v1, `cap-dx-the` v1, `cap-kn-ghi`, `cap-dx-xac-nhan`, `cap-dx-luot-chay` because of the em dash / W4 issues; shots
  with no mobile crop use their 640 file). No diagrams (avoids a merge clash in `blog-diagrams.mjs` with P49-A2).
- Facts kept to the product pages + D13/D14/D22/D24/D29/D30/D31/D32: no control groups (PP-DL's "Nhóm đối chứng
  (đang thử nghiệm)" not repeated), no simulation, no AOV lever, competitor price only "khi có", cover only with the
  seller's photo, day 7 asks, Juli never undoes by itself. SPEC §3.1 (30 days) and §4 P4 (top-10 / ≤ 5) not used.
- Heroes: new motifs `plug-socket`, `prism-rays`, `keys-padlock`, `hourglass-undo` added to the content engine
  `motifs.tsx` / `spec.ts` (after P49-A2's four; a new metaphor needs a motif), spec
  `projects/blog-heroes/heroes-p49a1.json`, rendered to the scratchpad, converted with `media.py blog-hero` (`-v1`).
  Content-engine changes are uncommitted (coordinator commits).
- Conflicts noted: sample day-7/14 shots target "CTOR Thẻ sản phẩm" after "Đã đổi Tiêu đề" (D32.2: CTOR is
  all-channel; D22/PP-DX map title to CTR); PP-DX lists "mua nhiều giảm nhiều cho AOV" and its hero lead says Juli
  changes the cover after confirmation (D13: only with the seller's photo); PP-DL describes control groups (D34 not
  built); `cap-dx-luot-chay` / `cap-dl-muc-tieu` dates (07/10, chốt 21/10) disagree with `cap-dl-ngay-7-v2` (10/10, 24/10).
- Gates: landing lint 0 errors (6 old warnings), `tsc --noEmit` 0, vitest 17 files / 682 passed, build OK, check:seo
  43 passed; 390 / 1440 renders: one H1, all figures, no horizontal scroll (shots in the session scratchpad
  `shots-p49a1/`); `check.sh --since fasttrack/optimize-product --skip-migrations` OK. Keyword SERP re-check on the
  writing day not done (plan's 2026-10-18 autocomplete used).
- Next: owner review of the drafts; P49-L end-of-post guide line for reach posts.

## 2026-10-18 — orchestrator (Claude Opus) — P49-L reach → guide link; P49 merged

- P49-A1 / P49-A2 merged (8 conversion drafts: C1–C5 guides, C6–C8 problem posts, each with its
  own hero rendered in juli-content-engine). Content engine: `blog-heroes` commits d980b58,
  c81b11c, 4a67a65; local `main` fast-forwarded to 4a67a65, not pushed.
- P49-L: `guide` on the 16 reach posts, `guideFor()`, the neutral box line
  "Đọc hướng dẫn liên quan" (no "Juli"), README note, 3 tests. Gates: tsc, lint, vitest 742,
  build, check:seo 47. Owner follow-ups from the writers (not done): sample day-7 / day-14 shots
  show a title change on a CTOR target; sample "Kéo xuống" rows do not add up to the tile;
  /san-pham/de-xuat-va-thuc-thi lists an AOV lever and implies cover upload without the seller's
  photo; /san-pham/do-luong-gmv describes control groups as live; /privacy states the still
  PROPOSED retention; "500.000đ/tháng" vs "từ 500.000đ/tháng".

## 2026-10-18 — orchestrator (Claude Opus) — all blog posts published

- Owner: "Đăng tất cả ngay". 29 drafts → published (publishedAt / updatedAt 2026-10-18), 31
  published in total; keyword-map statuses updated. Vendor prices in the four tools posts
  re-checked 18/10/2026: only MISA eShop changed (now publishes prices; the post no longer says
  it has none, no figures quoted) and the Nhanh.Ecom trial length could not be confirmed
  (now "có dùng thử miễn phí"). Gates: vitest 742, build, check:seo 47.
- Follow-ups: re-check `phi-san-tiktok-shop-2026` after the 20/10 and 21/10/2026 fee changes;
  owner to request indexing in Search Console for the new URLs; weekly GSC blog report (G6).

## 2026-10-18 — P51-B agent (Claude Opus) — landing product copy (D60.2, D60.3, D60.5)

- `/san-pham/de-xuat-va-thuc-thi`: "mua nhiều giảm nhiều" removed from the FAQ, the lever list
  (and the AOV trigger: cards open on "một chỉ số của phễu", recoverable GMV is CTR / CTOR only per
  SPEC P3) and the Seller Center promotion list (D45, Ops-only). Hero lead now splits title /
  description (Juli writes after confirmation) from the cover (only the seller's photo, after
  confirmation, old one kept for undo, D13); the cover H3 and the daily-slot line say the same.
- `/san-pham/do-luong-gmv`: H3 "Nhóm đối chứng (đang thử nghiệm)" and its paragraph removed
  (inside "Tác động tăng thêm"; TOC and FAQ unchanged, nothing else referenced it). Same claim
  removed from `/san-pham` (Đo lường body + point), home measurement row, home transparency
  paragraph, home FAQ (JSON-LD follows the constant), and the `toi-uu-the-san-pham` pillar's Juli
  lines (also its "chương trình mua nhiều" lever). General seller advice about comparing with
  unchanged products in Juli-free posts stays.
- Price (D60.5): "từ" dropped and "mỗi tháng" normalised to "500.000đ/tháng" in home (3),
  `/san-pham` meta (Service JSON-LD description), llms.txt, two tools posts, the trial guide (2)
  and its FAQ. New `price-wording.test.ts` scans src (minus /terms, /privacy, tests) for
  /từ\s*500/iu; `cta.test` no longer pins "từ 500.000đ/tháng"; D60 copy guards added to
  `capability-pages.test`.
- Gates: lint 0 errors (2 pre-existing warnings in figures.ts), tsc, vitest 748, build, check:seo
  47, check.sh OK (migrations / isolation skipped). Screens at 390 / 1440 in the session scratchpad
  `shots-p51b/`, no horizontal scroll, one H1.
- Not changed (out of scope, noted): pillars `gmv-la-gi`, `chi-so…` and `toi-uu…` say "Juli làm
  tự động các bước…"; `toi-uu…` still calls Juli "trợ lý AI cho nhà bán TikTok Shop" (D46.7).

## 2026-10-18 · P52-B: algorithm details out of the eight Juli guides (D61)

- Scope: the 8 guide bodies, their `posts.ts` entries (description, FAQ, source notes) and their
  `figures.ts` alts / captions; header comments cleaned too. Audit items G1–G58 and F1–F8 applied,
  borderlines resolved conservatively (G9, G52 market-price input dropped; G32 names "nhà cung cấp
  AI nêu trong Chính sách bảo mật" instead of OpenAI; PB4 channel fallback cut; PB1 "dao động bình
  thường" kept as concept).
- Removed: expected / recoverable GMV formulas and worked examples, "trung bình 30 ngày", "ước tính
  theo quy tắc", rules-vs-model and model-call timing, triggers, ranking key, target bounds, peer
  reference, 30-click / 30-order floors and the 14 / 30 / 60 window search, the 2× / 1× verdict rule,
  caps 5 / 25 / 30, slots 3 / 1 / 1, 7-day validity, 3-day stay, 7-day cooldown, priority demotion and
  60-day fade, calibration coefficient, "Juli học" section (now "Kết quả được lưu lại").
- Kept: TikTok definitions and GMV identity, workflow, labels (Rõ / Tham khảo, Đang lên / Chưa rõ,
  four day-14 labels), 14-day baseline, calculator links; calculator anchors untouched.
- Words (guide 1,500–3,000): ket-noi 2572, phan-tich 2536, duyet 2531, do-ket-qua 2292, dung-thu
  2050, keo-xuong 1925, ctr 1890, ctor 1989; figures 4 / 4 / 7 / 4 / 5 / 4 / 5 / 3.
- Pixels still show leaked text until P51-A recaptures: CAP_DX_THE_V2 (dung-thu-the-dau-tien,
  keo-xuong-the, ctor-mo-ta-the, hd-dx-the-mo-ta), CAP_DX_CTR_TIEU_DE (ctr-the-tieu-de,
  hd-dx-the-tieu-de), CAP_DX_ANH_BIA (ctr-the-anh-bia, hd-dx-the-anh-bia), CAP_DL_NGAY_14_V2
  (dung-thu-ngay-14, hd-dl-ngay-14), CAP_DX_QUY_TAC (hd-dx-quy-tac, hd-dl-quy-tac-on-dinh).
- Gates: lint 0 errors (2 pre-existing warnings in figures.ts), tsc, vitest 748, build, check:seo 47,
  check.sh OK (migrations / isolation skipped). Self-grep of audit patterns: zero hits in the 8 files.
## 2026-10-18 — P52-A agent (Claude Opus) — no algorithm details on product pages (D61)

- `/san-pham/de-xuat-va-thuc-thi`: FAQ caps (5/25/30, 7-day validity) and cooldown/demotion
  answers rewritten; H3 "GMV dự kiến được tính thế nào" + `<Formula>` + "trung bình 30 ngày" →
  "GMV dự kiến là một ước tính" (Formula import dropped); target rule → "Mục tiêu đo được";
  trigger and ranking ("Xếp hạng theo GMV có thể lấy lại" → "Việc đáng làm nhất đứng trước");
  30-click / 30-order floor and 7-day cooldown in the conditions list; H3 "Quy tắc chọn, AI chỉ
  viết" removed (blog link moved to the AI-writing H3); reasons/decay paragraph; section
  "Giới hạn số thẻ…" → "Nhịp đề xuất và thời gian chờ" (id `gioi-han` kept, TOC "Nhịp đề xuất"),
  no caps/slots/validity/cooldown numbers; "1 đến 3 đề xuất nhanh", "lấp đầy" → "vài", "các đề
  xuất khác xuất hiện"; card alt/caption no longer mention the formula; "ước tính theo quy tắc"
  → "ước tính".
- `/san-pham/do-luong-gmv`: FAQ "ước tính theo quy tắc, 30 ngày" → "ước tính từ số liệu gần đây";
  lead feedback-loop sentence removed; channel-fallback sentence cut (PB4, 14-day baseline kept);
  verdict 1–2× → "chưa đủ rõ để loại trừ may rủi"; "Độ mạnh của thay đổi" 2×/1× rule → "Khi nào
  một thay đổi là rõ"; "30 đơn mỗi bên, khoảng tin cậy không chứa 0" → "vượt khỏi vùng nhiễu";
  adaptive 14/30/60 window → "khi số liệu đủ để đọc"; section `#hoc` "Juli học từ kết quả đã đo"
  (coefficient, ranking, decay, cross-shop test) → "Lưu lại kết quả của từng thay đổi" (one
  paragraph, screenshot kept; alt and caption cleaned). `CAP_DL_HOC` / `CAP_DX_THE` pixels still
  show the demo copy: re-capture after P51-A.
- `/san-pham`: stepper "Tối đa 5 đề xuất mới…" → "Mỗi ngày vài đề xuất mới, việc đáng làm nhất
  đứng trước"; measurement point and FAQ demotion sentence. `/san-pham/phan-tich-shop`: "Thứ tự
  trong bảng cũng là thứ tự ưu tiên… Juli dùng chính phép tính này" and PB3 priority clause.
  `/ket-noi/tiktok-shop`: "1 đến 3" → "vài"; OpenAI named as data disclosure kept, no model name.
  `/cong-cu/tinh-gmv`: 50/20/1 floors "quy tắc của Juli" → DIY advice. Home `LOOP_STEPS`: "so với
  sản phẩm không đổi" → "hoàn tác được"; home-content comment no longer cites ADR-077 / D34.
- Tests: `info-pages` pins "Mỗi ngày vài đề xuất mới"; D60 control-group regex also bans "sản
  phẩm không (thay) đổi"; new `no-algorithm-leak.test.ts` (40-odd documented patterns, scans
  app minus terms/privacy, components, lib/seo, content/blog; `LEAK_PENDING_FILES` holds the 20
  blog files that still hit, with a stale check so P52-B/C must remove entries as they clean).
  lastModified bumped for phan-tich-shop, ket-noi, tinh-gmv.
- Gates: lint 0 errors (2 pre-existing warnings in figures.ts), tsc, vitest 767, build,
  check:seo 47, check.sh OK (migrations/isolation skipped). Shots at 390 in scratchpad
  `shots-p52a/`, one H1, no horizontal scroll. Note: port 3007 was taken by another agent's
  server; screenshots used port 3127.
## 2026-10-18 — P52-C agent (Claude Opus) — reach posts, pillars, tools posts (D61)

- Reach posts (Juli-free, D59): removed the first-person "quy tắc thực hành của chúng tôi" data
  floors (50 impressions / 30 clicks / 30 orders, 50 / 20 examples) from `anh-bia`, `dat-ten`,
  `khach-xem`, `tiktok-shop-khong-ra-don`, `san-pham-…-khong-co-luot-hien-thi`, `doanh-thu-…-giam`,
  `do-hieu-qua…`; the 2× / 1–2× verdict multiples and the one-third holdback in `do-hieu-qua…`
  (now "vượt hẳn / nhỉnh hơn / nằm trong" the product's own swing, "để vài sản phẩm chưa sửa làm
  mốc so sánh"); the 4-star rule and Juli's 40 / 25-character rule (TikTok's 25-character minimum
  kept); the clicks × peer-CTOR-gap ranking in `khach-xem`; peer medians; the log decomposition
  in `doanh-thu-…-giam` (plain "which metric fell most in percentage"). FAQs in posts.ts follow.
- Pillars: `chi-so…` log formula removed (GMV identity and a plain reading kept), 30-order floor
  removed; `gmv-la-gi` 50 / 20 / 1 floors and median removed (calculator anchor H3 untouched);
  `toi-uu…` 40-character, BMSM "+1", 4-star and 50 / 20 / 1 table removed. All three: TMĐT
  descriptor (D46.7) and no "Juli làm tự động" (changes happen only on approval). Tools hub:
  comparison-group claim (also in the toi-uu FAQ) replaced by the 14-day baseline.
- Diagrams re-rendered with the generator: `doc-pheu-o-dau-v3`, `do-doc-sai-doc-dung-v2`,
  `do-ba-ket-qua-v3` (old files deleted); alts and heights in figures.ts.
- Word counts stay in range (pain posts 2,448–2,509; pillars 4,548–4,845). Gates: lint 0 errors
  (2 pre-existing warnings), tsc, vitest 748, build, check:seo 47, check.sh OK.
## 2026-10-18 · P51-A sample data (D60.1) + demo/backend card copy (D61) + recapture (agent: Claude Opus, branch `fasttrack/p51a-sample-data`)
- Branch from `fasttrack/optimize-product` 371a0d3e, merged e5cfc47d (D61). Commits 2247eb13 (demo D60.1), 5bad50fa
  (landing shots + captions), 84dfaa0f (D61 demo + backend copy), a9d98166 (figures.ts alts reverted to P52-B's),
  524da0d6 (D61 recapture). Not merged, not pushed.
- **Lever ↔ target**: TN-021's title run now targets **CTR on Thẻ sản phẩm 3,2 % → 3,5 %** (1.770 channel
  impressions × 0,3 pt × CTOR 6,6 % × AOV 170k ≈ +60k ₫/ngày, +1,8 tr/tháng); guard bands are the other three
  metrics, product-wide: Lượt hiển thị 3.480, CTOR 6,6 %, AOV 170k (±3 %), GMV/ngày 1,6 tr. Day 7: CTR 3,4 % Đang lên,
  GMV +38k Sơ bộ; day 14 (simulated): CTR 3,53 % Đạt, +54k/ngày = 90 %. Target labels follow the backend
  ("CTR · đo trên kênh Thẻ sản phẩm", "CTOR · đo trên tất cả kênh"); main row "CTR (chỉ số chính)"; simulated band
  text = the day-7 format; day 14 keeps the 20 % progress mark. CTOR cards read "CTOR" (D32.5), group "nâng CTOR
  (mọi kênh)" (channel_scope ALL_CHANNELS for CTOR/AOV); waiting measurements drop their own target from the guards.
  SM-012 still proposes Tiêu đề + Mô tả on a CTOR card (artboard card; owner call).
- **Kéo xuống sums**: not a data error. The payload is down + up + closing = cell, but a view showed one direction +
  closing. `phan-tich/rows.ts` now folds the other direction's rows into Còn lại ("1 sản phẩm kéo CTOR lên +28k"):
  Thẻ sản phẩm CTOR Kéo xuống −112 −64 −58 −21 −9 = −264k + Còn lại +14k (4 dòng) = −250k = tile = Tổng; Kéo lên
  +28k + Còn lại −278k = −250k. Test asserts it for every product table and both directions (also fixes real shops).
- **Dates**: one capture clock (2026-10-18 09:33 +07), so every run shot reads 10/10 → 17/10 → 24/10.
- **D61 copy** (audit §8): card GMV line = "Juli ước tính GMV có thể lấy lại từ lượt hiển thị, CTR, CTOR và giá trị
  đơn hiện tại của sản phẩm" (backend `_GMV_METHOD_VI` / 14-day map, content cards, sample, no "theo cách của
  TikTok" prefix); "Thứ tự đề xuất đã điều chỉnh…" not rendered; day 14 without the calibration step, "Một phần:
  N % GMV dự kiến", no "mức kỳ vọng" lines, FINAL_RULE_NOTE without 1–2×; rules editor without 5/25/3·1·1; reasons,
  run and content panels without "sau 7 ngày"; "ước tính theo quy tắc (chưa phải mô hình)" → "ước tính" (demo
  RULE_BASED_ESTIMATE, evidence block, backend impact sentences, RECOVERABLE_LABEL); sample codes v1 / metric_drop,
  no status_label. Kept (borderline, owner): "trung vị shop / đối thủ" in sample reasons, legacy plan-caveats.
- **Recapture** (scratchpad `p51a/shots/capture.mjs`, P49 safety: localhost only, placeholder Supabase env, sample
  shop / mocks): new files cap-dl-hoc-v2, dl-muc-tieu-v2, dl-ngay-7-v3 (+m-v3), dl-ngay-7-v4, dl-ngay-14-v4 (+m-v4),
  dl-ngay-14-v5, dl-tang-them-v2, dx-luot-chay-v2, dx-seller-center-v2, dx-the-v3, dx-the-v4 (+m-v4 home hero),
  kn-ghi-v2, pt-nghen-v3, pt-xep-hang-v2, pt-luong-v2, dx-quy-tac-v2, kn-dang-nhap-v4, dx-anh-bia-v3,
  dx-ctr-tieu-de-v2, kn-quet-nhanh-v3 (+ their m- crops); exports keep their names; superseded files and their
  MOBILE_CROPS entries removed (only screens.ts referenced them). Demo auth panel `cap-dx-the-v3`.
- Captions: product pages / home alts follow the new shots; blog figures.ts alts left to P52-B (my alt diff saved in
  the scratchpad `p51a/figures-alts-d60.patch`).
- Gates: demo lint 0 errors (7 old warnings), tsc 0, vitest 159 files / 1992; demo build OK (Node 20); landing lint
  0 errors (2 old warnings), tsc 0, vitest 18 / 748, build OK, check:seo 47; backend pytest 31 files touching the
  card code 536 passed, 1 pre-existing failure (`test_cross_tenant_probe` demo runs events 404, fails on the base too);
  ruff clean.
## 2026-10-18 · P52-D leftovers: alts follow the recaptured shots, no peer median, SM-012 description only (D60.1, D61) (agent: Claude Opus, branch `fasttrack/p52d-leftovers`)
- Branch from `fasttrack/optimize-product` 8e3884bb. Not merged, not pushed.
- **Alts** (`figures.ts`, 17 replacements over 15 figures; P51-A's patch used for numbers / labels only): TN-021 day 7 /
  day 14 now read CTR · đo trên kênh Thẻ sản phẩm 3,2 % → 3,5 % (day 7 3,4 % Đang lên, GMV +38k Sơ bộ vs +60k dự
  kiến; day 14 3,53 % Đạt, +54k/ngày = 90 %, +1,6 tr vs +1,8 tr/tháng), guards Lượt hiển thị 3.480 / CTOR 6,6 % /
  AOV 170k; CTOR cards "CTOR" (no "Thẻ sản phẩm"); Phân tích "Xem 3 đề xuất"; Quyết định "3 thẻ tối ưu để nâng CTOR
  (mọi kênh)", group +7,2 tr; Kéo xuống "Còn lại 4 dòng +14k, Tổng −250k". The "đang tiến triển từ" figure and every
  D61 pattern stay out. Pages: `/san-pham` card alt, `/san-pham/de-xuat-va-thuc-thi` card / consent alts (Mô tả only,
  reason without median). Bodies next to the figures already carried the new values.
- **Peer median** (D61): SM-012 reason "Đơn/thêm giỏ của sản phẩm là 38,9 %, thấp hơn các sản phẩm tương tự trong
  shop."; KD-030 "Giá 279k, cao hơn các sản phẩm tương tự trên TikTok Shop." and its run step "Giá 279k · cao hơn sản
  phẩm tương tự". Same text in the mirrored unit / e2e fixtures. No backend card copy had the string (only an internal
  report note and Ops HTML, untouched).
- **SM-012**: CTOR card proposes Mô tả only (change fields, before/after, run proposal); sample tests edit the
  description. Legacy `lib/recommendations.ts` optimize fixture (not a CTOR card) untouched.
- **Recapture** (scratchpad `p52d/shots/capture.mjs`, P51-A safety: localhost only, placeholder Supabase env,
  signed-out sample, fixed clock): `cap-dx-the-v5` (+ home phone crop `m-v5`), `cap-kn-ghi-v3`, `cap-dl-hoc-v3`
  (+ `m-v3`), `cap-dx-xac-nhan-v2` (+ `m-v2`, SM-012 consent shows only the description). Superseded v4 / v2 / v2 / v1
  files and their MOBILE_CROPS entries removed (only screens.ts / sections.test referenced them).
- Gates: landing lint 0 errors (2 old warnings), tsc 0, vitest 19 / 767 (also with `--no-experimental-webstorage`
  on Node 26), build OK, check:seo 47, leak test green with empty pending list; demo lint 0 errors (7 old warnings),
  tsc 0, vitest 159 / 1992, build OK (Node 20, placeholder Supabase env). Backend unchanged.

## 2026-10-18 — orchestrator (Claude Opus) — D60 + D61 merged

- Merged P51-A (D60.1 sample data, D61 demo + backend card copy, 20 recaptures), P51-B (D60.2,
  .3, .5), P52-A/B/C (D61 landing, guides, posts) and P52-D (alts, peer median in sample
  reasons, SM-012 CTOR card proposes Mô tả only, 4 more recaptures). `no-algorithm-leak.test.ts`
  runs with an empty pending list. Gates at 735b3e10: landing tsc, lint, vitest 767, build,
  check:seo 47; demo build. P51-A changed display logic in `apps/demo/src/lib/phan-tich/rows.ts`
  (rows of the other direction fold into "Còn lại", so both views add up; affects real shops) —
  kept, owner told.
- Not changed: `backend/.../action_cards/card_groups.py` "so với các sản phẩm chưa đổi" is the
  real result text of the D34 group experiment (Ops / shops with groups only), accurate, not
  public content. Pre-existing backend failure `test_cross_tenant_probe` (demo runs events 404)
  fails without these changes too.

## 2026-10-18 · P53-C2 remove the three legacy demo routes (owner C2) (agent: Claude Opus, branch `fasttrack/rm-legacy-routes`)
- Branch from `fasttrack/optimize-product` 1f7dfe64. Not merged, not pushed.
- **Closure** by a TypeScript import graph (`ts.resolveModuleName`, every `app/**` page / layout /
  route / robots + `middleware.ts` + `next.config.ts` as live roots): 38 files reachable only from
  the 3 pages; removed 37 (kept `repeat-consent-block.tsx`, consent / TOO-RISKY) plus 4 dead
  components that imported the closure (`recommendations-view`, `recommendations-panel`,
  `settings-thresholds-panel`, `settings-workflow-list`), `lib/run-surface/run-id.ts` (only user left
  was demo-shell's run branch) and `scripts/verify-replay-scenario-in-build.mjs` (checked the removed
  golden scenario; dropped from `build`). 106 shared modules stay (`lib/workflows/*`, `lib/reviews`,
  `lib/executions`, `lib/recommendations`, `lib/run-ledger/{api-client,copy,…}`,
  `lib/run-surface/{reduce-run-view,option-diff,use-run-stream,confirmation-*}`, `lib/analytics/{api-client,
  analytics-data-context,fallback-envelope,main-kpis}`, `lib/repeat-consent`, `lib/plan-caveats`, …).
  Non-test: 46 files, −7,156 lines; tests / e2e: −13,106 lines.
- **Links**: no live UI, landing page, backend / email copy or sitemap points at the 3 paths
  (git grep; robots allows all, no sitemap; middleware has no rule for them), so no redirect: they
  now 404. `lib/recommendations.ts` `buildRecommendationDetailHref` removed (only user deleted).
- **demo-shell**: `RUN_DETAIL_PATH_PATTERN` / run-focus branch removed; test now pins that the
  retired run path gets the full shell. `replay-module-graph.test.ts` entries for the review page and
  `replay-run-detail` removed (remaining signed-out entries unchanged, still green).
- **Tests**: 46 test files deleted (only covered removed code); trimmed to their live parts:
  `demo-shell`, `destination-naming`, `dictionary-and-banned-pattern-coverage`, `repeat-consent`
  (pure eligibility / gates), `recommendations-copy-guard` (fixture guard, now `.ts`),
  `recommendations-routing`. e2e: `decisions-journey`, `replay-fixture-presence`,
  `replay-run-accessibility`, `replay-run-journey`, `fixtures/{replay-scenario,workflow-keys}`,
  `helpers/workflow-journey` deleted (`resetDemo` moved to `helpers/demo-navigation`);
  `accessibility.spec` drops the review-route test. `tests/unit/test_phase_2_6_demo_exit_gate.py`
  no longer requires `decisions-journey.spec.ts`.
- **Route inventory** (`next build`): 25 → 22, the diff is exactly the 3 routes; API route
  `/api/tt/event` unchanged.
- Gates (Node 20): demo tsc 0, lint 0 errors (1 old warning), vitest 117 files / 1157 (was 159 /
  1992), `@juli/ui` + `@juli/utils` tests green, `build:demo` OK (placeholder Supabase env),
  Playwright `e2e/exit-gate` 62 passed / 2 failed — the pre-existing `responsive-parity` wordmark
  label (DEBT P53-C2), not touched here. `fasttrack/check.sh --since fasttrack/optimize-product` OK on a
  throwaway Postgres 16 (UTC): migrations, isolation 12, gitleaks, ruff, pytest 15.


## 2026-10-18 · P53-A cleanup: A1–A4, B3, B4, B6, B7 (D62) (agent: Claude Opus, branch `fasttrack/cleanup-a`)
- Branch from `fasttrack/optimize-product` 1f7dfe64, rebased onto 30cc88dc (P53-C2 merge). Not merged,
  not pushed. Owner approval of A1–A4, B, C1, C2 recorded as **D62**.
- **A1**: `workers/tasks/__init__.py` imports `product_history`. Proof: a fresh interpreter's
  `celery_app.loader.import_default_modules()` listed 26 tasks and the beat entry
  `product-history-fanout` was unregistered; now registered. `test_beat_schedule_registration`
  builds the registry in a fresh interpreter: red without the import even when run after
  `test_p23_product_history` (2 failed), green with it. **This turns the P23 nightly fan-out, the
  webhook re-reads and the approval baselines on in production for the first time** — scope,
  call volume and what to watch in DEBT P53-A.
- **A2**: the 8 deep imports go through `services.ops` (`ops_role`; lazy `purge_expired`,
  `check_alert`) and `services.action_cards` (`GroupError`; lazy `open_cell_counts`,
  `rescore_shop_cards`). Boundary baseline re-derived: 54 rows (the 3 stale ones gone; it said 55
  over 57). `check_import_boundaries --strict` with baseline PASS.
- **A3**: `test_trial_signups` reads the `versions/` head (ScriptDirectory) instead of 093;
  `test_ratchets`: the 7 new suppressions (all in tests) removed rather than baselined, so the
  committed baseline equals the tree unchanged; `test_reaper_two_tenant`: red on a PG16 server in
  Asia/Ho_Chi_Minh (aware stamps in naive columns), green after the fix in Asia/Ho_Chi_Minh, UTC,
  America/Los_Angeles; module-drift allowlist regenerated from the tree (+ api MODULE.md
  `reviewer_me` bullet); quality reconciliation re-derived (prose had drifted from the 6,417
  constant) to 6,851 / 661 modules / layers 493·130·115·115·53·49. Still red, left for the owner:
  `test_test_quality::test_reconciliation_reproduces_from_the_tree_it_describes` (prior-figure
  drift 18 > 15, the 9 `test_ops_round_trips` helper-asserting tests).
- **A4**: `JULI_TEST_DATABASE_DISPOSABLE: "1"` on the deploy workflow's check.sh step (check.sh
  already exports it in `use_db`); `test_destructive_migration_isolation` 10 passed.
- **B3** `services/etl/topics.py` deleted (0 importers). **B4** `apps/dashboard/tsconfig.tsbuildinfo`
  untracked (`*.tsbuildinfo` already ignored); `apps/dashboard/package-lock.json` and `done.md`
  **kept** — still read by pr.yml (`frontend` npm ci; blocking `check_done_md`). **B6** LEGACY
  markers: `agent-runtime/LEGACY.md` (+README banner, what still reads it), `ios/LEGACY.md`,
  `Design-md/LEGACY.md`, `EXECUTION.md` banner, Status sections in 7 backend MODULE.md files
  (`ai/**` untouched, frozen). **B7** LOG (36 entries), DECISIONS (G1–G4, defaults, D20–D27, with an
  index of D1–D27 left in place) and 26 closed DEBT items before 2026-10-12 moved verbatim to
  `fasttrack/archive/`; no non-blank line lost; no test parses these files. Not done here: B1, B2, B5.
- Gates: unit suite in 4 processes + harness: the only failures are the known environment ones
  (`test_agent_workflow_task_wiring` 7, `test_cross_tenant_probe` 1 — empty DATABASE_URL), the
  prior-figure check above, and load timeouts that pass alone (`test_credentials_in_url_guard`
  46 s, `test_shop_ingestion`, `test_agent_run_event_stream`, `test_api`, `test_status_record_gate`
  — 108 passed when re-run). Targeted: boundaries / ratchets / harness / quality / beat / trial
  signups / migration isolation 173 passed, 1 known fail. `fasttrack/check.sh --since
  fasttrack/optimize-product` OK on a throwaway Postgres 16 (UTC, port 55491, dropped after):
  migrations, isolation 12, gitleaks, ruff 16 files, pytest 19 files / 362. Demo / landing not
  touched (no file under apps/demo, apps/landing, packages changed).

## 2026-10-18 · P53-C1 delete apps/dashboard (owner C1) (agent: Claude Opus, branch `fasttrack/rm-dashboard`)

- Re-verified nothing deployed builds or serves it: not in `deploy.sh` lanes,
  `fasttrack-deploy.yml`, `release.yml` matrix or `build-release-artifact.sh` DEPLOYABLES; no
  nginx vhost or `server_name` for it (`dashboard.app-juli.com` exists only in old docs; no
  config); not a pnpm workspace member and absent from `pnpm-lock.yaml` (lockfile unchanged,
  `pnpm install --frozen-lockfile --offline` OK). Live only via pr.yml `frontend` job (+ its
  `dashboard` path filter, dependency-validation npm step, status-check / deployment-checks
  wiring), dependabot npm entry, `build-frontend-review.sh` / `provision-frontend.sh`, root
  `dev:dashboard` / `setup`, `.claude/launch.json`, and ~10 Python tests.
- Removed: `apps/dashboard/` (345 tracked files, ~2.0 MB source, 2.7 MB on disk), the two VPS
  review scripts, `tests/unit/test_phase_2_5_frontend_deploy.py`, the pr.yml `frontend` job
  and every `dashboard` output/needs/require, the dependabot npm entry, root `dev:dashboard`,
  `setup` → `pnpm install`, launch config, gitignore line, clean-local paths, the
  public-release classifier prefix. Tests updated to guard the deletion instead (343, 397,
  main-domain, 2.5 docs/reviewer/workspace, three-tier CI, public-release).
- Docs: README, apps/README, infra READMEs, nginx comment, architecture map/MODULES (dead
  links unlinked), agent skills/rules (.claude/.cursor; `sync_claude_skill_pointers.py`
  regenerates the same pointers), runbooks with a HISTORICAL banner. ADRs, product docs,
  handoffs, artifacts, slice routing left as records. Ratchet `check`: same 292 violations as
  1f7dfe64, no new ones.
- Kept on purpose (VPS-live, see DEBT P53-C1): `juli-web.service`, `web.env.example`, and the
  `juli-web` lines in fetch/refresh-secrets and rollback-release.
- Gates (Node 20, placeholder Supabase env): check:demo — lint 0 errors (7 old warnings), tsc,
  vitest 159 files / 1992, ui + utils tests, build OK; check:landing — lint 0 errors (2 old
  warnings), tsc, vitest 19 / 767, build OK. Under Node 26 both suites fail on localStorage
  (pre-existing, environment). `apps/demo`, `apps/landing`, `apps/connector`, `packages/`,
  `pnpm-lock.yaml`, `turbo.json`: zero diff; route files identical (demo 24, landing 20).
- check.sh --since fasttrack/optimize-product (throwaway PG16, UTC, port 55473, dropped
  after): OK — migrations up/down/up at 093, isolation 12, gitleaks, ruff 12 files, pytest
  8 files / 107. Two ruff-format fixes were whole-file formatting of touched files
  (`public_release_classification.py`, `sync_claude_skill_pointers.py`).
- tests/unit (no DATABASE_URL): 18 failed / 7515 passed / 3 errors; all pre-existing or
  flaky (agent_workflow_task_wiring ×7, cross_tenant_probe, destructive_migration_isolation,
  ratchets suppression baseline, import_boundaries baseline, test_quality / quality_reconcile
  ×6 fail on the base too; credentials_in_url ×2 and onboarding_speed pass alone).

## 2026-10-18 — agent (Claude Opus) — P54 Dependabot pip bumps (D63)

- One `pip-compile --upgrade-package` regeneration of `backend/constraints.txt`: pyjwt 2.15.1,
  starlette 1.7.0, markupsafe 3.0.4, python-dotenv 1.2.4, tzdata 2026.5, amqp 5.4.1,
  wcwidth 0.9.2, ast-serialize 0.12.1, librt 0.16.0; cloudpickle 3.1.2 newly pinned (was
  installed unpinned via joblib). No other pin moved. pydantic-core 2.49.0 deferred (pairs only
  with pydantic 2.14.0b2). `backend/pyproject.toml` and root `requirements.txt` now list identical
  ranges (pyjwt `>=2.15.1`, python-dotenv `>=1.2.4`, plus five floors that had drifted).
- Fresh Python 3.12 venv, `pip install -e "./backend[dev]" -c backend/constraints.txt`: resolves,
  `pip check` clean, every installed package pinned; `pip install -r requirements.txt -c
  backend/constraints.txt` (the deploy path) resolves. App and security modules import.
- Base vs new, same worktree, PYTHONPATH pinned: `tests/unit -m "not live"` 42 failed / 7512
  passed / 3 errors on both, same failing set (node_modules missing for contract tests, no
  DATABASE_URL, import-boundaries / ratchet / quality-corpus drift — all pre-existing; two
  timing tests flaked once each under parallel load and pass alone). Auth / JWT / JWKS / CF
  Access / routes / Celery / trial-signup (BackgroundTasks) files: 602 tests, 0 failures on both.
  `tests/integration -m "not live"` on a throwaway Postgres 16 (UTC): 356 passed, same 14
  pre-existing failures/errors on both. mypy and ruff clean on both. `fasttrack/check.sh`
  (throwaway Postgres 16, UTC): OK with `--since fasttrack/optimize-product` and with the deploy
  default `origin/main` (212 files, 3098 passed).
- Owner: close Dependabot PRs #2124, #2122, #2121, #2119, #2117, #2115, #2114, #2111, #2112
  (applied here) and #2118 (pydantic-core, cannot apply alone) after the merge.

## 2026-10-19 — agent (Claude Opus) — P55 deploy gates (D64)

- Branch `fasttrack/deploy-gates` from efb1df92.
- **A, #1682 (option A, owner).** Root cause: the headline (49) already credited same-file
  helpers. The red check is the *prior-figure* layer `and_no_mock_assert_called`, which is by
  definition the old detector (no helper credit). The 9 `test_ops_round_trips.py` tests assert
  only through `_check` (and `Probe.warm` → `Probe.once`), so they took that layer from 106 at
  the branch point 0739f4da to 115. The added set is exactly those 9, derived on both trees.
  Detector: `HelperResolver` follows imports into `conftest.py` and `tests/` packages and
  judges helpers by their bodies. It credits same-file class methods on any receiver and
  third-party `assert_*` / `expect_*`. `backend/src` is resolved as non-helper code, so
  production `assert_*` stays uncredited. A first cut without that rule credited 3 tests that
  call `assert_agent_broker_is_durable` / `assert_allowed`; caught by an old-vs-new set diff and
  fixed. Layer renamed `and_no_asserting_helper`. Counts before → after on this tree:
  493·130·115·115·53·49 → 493·130·115·115·53·49 (headline 49 → 49; the same on the branch
  point). No existing finding was dropped or added. The claim now runs over the fixed set
  `eval/quality_prior_figure_set.json` (53 helper-credited identities at 0739f4da): 115 − 9
  newcomers = **106, drift 9 ≤ 15** (tolerance unchanged). `reconcile --write` re-derived the
  corpus figures (6,830 functions / 660 modules) and the prose, and prunes the set (never
  adds). New synthetic tests: imported, module-attribute, conftest, method-on-fixture and
  third-party helpers are credited; each silent twin and a production `assert_*` stays
  flagged; a helper-style newcomer leaves the fixed set while a vacuous newcomer stays in it;
  the 9 ops tests are helper-credited and not flagged. 3 corpus-scan tests get
  `timeout(180)` (same reason as `test_quality_reconcile.py`).
- **B, no-database unit suite.** First run: 9 failed. Fixed:
  - `test_agent_workflow_task_wiring` (7). 5 needed only a session *factory*: an autouse
    stand-in replaces `_ensure_session_factory`, which no longer builds an engine from an empty
    `DATABASE_URL` or registers the global factory. 2 (`TestTaskBodiesCallRealRunnerMethods`)
    really open a sync ledger session on `DATABASE_URL` and are now `requires_postgres`.
  - `test_cross_tenant_probe` (1): the run-events stream factory is bound to the test engine.
    With Postgres, the 404 used to come from the row being absent there. A swap of the run to
    tenant A's own shop no longer 404s, so the test now measures the tenant check.
  - `test_credentials_in_url_guard`: `timeout(120)` on its two whole-tree scans only.
  - The 9th failure (`test_action_card_refresh_cooldown` slow-store test, #2058) is load-only
    and passed 3/3 alone.
  Second run, exactly as the job runs it (fresh 3.12 venv, `backend[dev]` + constraints, Node
  20, no `DATABASE_URL`): **7536 passed, 245 skipped, 2 xfailed, 0 failed in 14 min 37 s**
  (laptop at load 3–7). The two touched files with Postgres: 39 passed.
- **C, workflow.** `frontend`, `backend-unit` and `static` need only `validate`; `deploy` needs
  them plus `check` and `build`. Added `.nvmrc` (20); `build` and `check` read it too.
  `actionlint` clean. Local timings, uncached:
  - `frontend`: demo lint + tsc + vitest 120 s, ui + utils 10 s, landing 75 s (205 s, plus
    install). 1157 + 180 + 2 + 767 tests passed.
  - `static`: mypy 21–57 s (705 files, clean); bandit 8–13 s (clean at `-ll`).
  - `packages/theme` was dropped from the job: 2 stale tests (DEBT P55).
  - Under heavy load (avg 9–24) demo vitest showed 4 different one-off races; each passed
    alone and in the clean full run (DEBT P55).
  - Estimated CI wall time: `frontend` ~6–8 min, `static` ~3 min, `backend-unit` ~15–18 min
    including install. All run beside backup + check (~12–15 min, from check.sh's ~9 min of
    pytest here). So about **+0–5 min** on the critical path, set by `backend-unit`.
- `fasttrack/check.sh --since origin/main` (throwaway Postgres 16, UTC, dropped after):
  migrations PASS (093 head), isolation 12 passed, gitleaks PASS, ruff PASS (505 files),
  pytest PASS (222 files: 3236 passed, 2 skipped, 1 xfailed). **check.sh: OK**.
- DECISIONS' duplicate D59 left (75 mixed references; DEBT entry extended).

## 2026-10-18 · P50 · PDPL legal terms and the features they promise (Opus 5.5, parent + 3 agents)

- Owner grill → D68 (B2B only, de-identified model improvement as a condition of use, never buyer data, total liability exemption, breach-only termination, rights in-app + e-mail with NĐ 356 deadlines, 15-day notice, disputes, 30-day export window, date-only pages). Research: Viettel AI, FPT Shop / FPT IS policies; Luật 91/2025, NĐ 356/2025, Luật AI 134/2025, Luật BVQLNTD Điều 25, BLDS Điều 405.
- P50-L 490dc852: /terms (VI) adds §1 B2B, §8.6 licence + model ownership, §9 breach list, §10 15 days, §11 liability, §12 disputes, §13 general (signed contract prevails); /privacy VI + EN cite Luật 91/NĐ 356, §6.1–6.3, rights deadlines, 20-day deletion / 30-day window, no version. Google Limited Use sentence kept verbatim plus a stricter line. Landing 623/623.
- P50-B (merged b4503d55): migration 094 (7 users columns + column grant, periods.shop_id nullable, pollable shops skip pending deletion, juli_ops-only purge functions), /v1/me privacy|consents|export|deletion, pending deletion = read-only shops, nightly `privacy_account_purge` 21:13 UTC. Agent ran check.sh (migrations up/down/up, isolation, gitleaks, ruff, 375 tests) on its branch.
- P50-U (merged 73dc51eb): Cài đặt → Quyền riêng tư tab, re-acceptance strip with the Điều 11 checkbox, demo pixel + registration gated on ad_measurement_opt_out. Demo 2033/2033 (one flaky run, green on two reruns), tsc clean.
- P50-P/E (merged 7a9cc99f): core/privacy/deidentify.py at all three OpenAI call sites + AST guard test; ops masking shares its regexes; `services/ops/terms_notice` CLI (dry run default, hashed sent-list).
- Merge fix: `services/privacy/export.py` added to the users.phone reviewed list (export copies the seller's own value, NULL as null).
- Known red, pre-existing and unrelated: 7 tests in test_agent_workflow_task_wiring.py need a database URL locally.
- Not done: check.sh on the merged branch (needs CHECK_DATABASE_URL); see DEBT P50 (Supabase Auth user deletion is the one live promise gap). Next: owner deploy tag, then terms_notice dry run and --send.

## 2026-10-19 · P50 · merged into optimize-product (Opus 5.5)

- D60 was taken on optimize-product (P51) and D65/D67 on open branches; P50's decision renumbered **D68** (17e00f0b).
- The deploy gate's full unit suite (`pytest tests/unit -m "not live"`, no database) found 6 P50 failures the
  agents' runs missed; fixed in 132cc369: the nightly `privacy_account_purge` was never imported by
  `workers/tasks/__init__.py` (beat would have dispatched it into nothing); core→services and deep imports;
  a `noqa:E501`; `reconcile --write` (zero-assertion layer unchanged at 49); surface inventory (+5 `/v1/me` routes).
- Gate suite on the P50 branch: 7580 passed, 5 failed — all five `pytest-timeout` (>30 s) under machine load,
  63/63 green when re-run alone. Landing 767/767, demo 1199/1199 + tsc on the merged tree.
- Supabase Auth deletion: option A chosen, deferred (DEBT P50).

## 2026-10-19 — agent (Claude Opus) — P56 first `backend-unit` failure (D65)

- Run 39214813315 (tag `fasttrack-deploy-20261019T0715Z`, 310cc0e1): `backend-unit` failed 2
  tests and deploy was skipped. Branch `fasttrack/ci-fix` from 310cc0e1.
- **`test_clean_record_produces_no_failures`: environment, not data.** The gate output is
  `unsupported CI flow: event='push' base='' ref='fasttrack-deploy-20261019T0715Z'`.
  `run_gate` copied `os.environ`, so the runner's tag-push context reached
  `required_artifacts.resolve_tier_and_branch`, which correctly fails closed. Locally no
  `GITHUB_*` is set, so the gate saw the issue tier. pr.yml and release.yml use supported events,
  which is why this never showed before. Reproduced in a fresh clone by setting the tag-push
  env. Fix: `gate_env()` (D65.1). New tests: env pinning, plus a regression that runs the raw
  gate under the tag-push env (asserts FAIL, so the env really reaches it) and `run_gate`
  (asserts PASS).
- **`test_every_row_provenance_resolves`: environment plus a latent resolver gap. Not the
  branch cleanup.** The record ids `f6c0630567443eb4` / `702867bf541e1fcd` are record digests,
  not SHAs, so `git cat-file` on them always failed. The cited commits are `d408041c` and
  `62a70cec` (PR #1472). Their head branch was deleted at merge on 2026-09-01
  (`head_ref_deleted` event), not today. Locally they are not in the object store, not in any
  reflog and not unreachable. On GitHub, `gh api commits/<sha>` finds both, and
  `git ls-remote origin` shows `62a70cec refs/pull/1472/head` (d408041c is its parent). A
  complete clone gets neither, so the resolver said MISMATCH. The shared local repo is shallow
  (since 2026-10-18 21:42), so the P55 local run took the MISSING_SOURCE path. Fix: D65.2.
- **Fresh-clone reproduction.** `git clone --no-local` of `origin/fasttrack/optimize-product`
  into /private/tmp/claude-501/ci-clone (not shallow), Python 3.12.9 venv with
  `backend[dev] -c constraints.txt`, contracts `pnpm install`, no `DATABASE_URL`, tag-push
  `GITHUB_*` env.
  - At 310cc0e1: both tests fail, as in CI.
  - At ci-fix with no archive fetch: 22/22 pass in the two files.
  - With `JULI_REQUIRE_ARCHIVED_COMMITS=1` and no fetch: fails, naming the refspec.
  - After the workflow's fetch step (`refs/pull/1472/head -> refs/archive/pull-1472-head`) with
    `REQUIRE=1`: 22/22 pass, and the 2 rows are RESOLVED with the digest checked.
- **Full no-DB suite**, same clone and deploy configuration: **7537 passed, 245 skipped,
  2 xfailed, 3 failed in 77 min 49 s**. The laptop was at load 8–16, with another pytest running.
  The 3 failures were all pytest-timeout: `test_ratchets::test_baseline_captures_394_suppression_identities`
  and 2 in `test_status_record_gate`. They did not fail because of the change. Re-run:
  `test_ratchets.py` + `test_status_record_gate.py` gave 59 passed, 1 skipped. The 3 took
  25/16/31 s at base 310cc0e1 against 11/11/26 s on ci-fix under the same load. DEBT P55's
  re-run advice applies.
- ruff check + format clean. `actionlint` clean. No branch restored, no ref pushed, nothing merged.

## 2026-10-19 — agent (Claude Opus) — P58 production bugs from the worker log (D67)

- Branch `fasttrack/prod-bugs` from `fasttrack/optimize-product` 310cc0e1, which only adds CI /
  docs / test-quality changes on top of the deployed release `efb1df92`. No product code
  changed in between, so line numbers match the log. Numbered P58 / D67: `ci-fix` and
  `rollback-fix` both claim P56 / D65.
- **Bug 1, `product_history_promotions_failed`.** Trace: `sweep_promotions`
  (job.py:442, `epoch_to_naive_utc(raw.get("update_time"))` on a Search Activities row) →
  normalize.py:53 `datetime.fromtimestamp(seconds, UTC)`. `int(str(v))` already turned
  junk / None / "" into `None` (caught at :49), and `<= 0` covered 0. So line 53 can only raise
  for a number out of `datetime`'s range: `fromtimestamp(1791000000123)` is "ValueError: year
  58724 is out of range". The 202309 OAS (bundled skill copy) types every activity time as int64
  seconds. The repo's own sample notes (`services/shop_diagnosis/promotions.py`: "create /
  update times are milliseconds"; `optimize_product/promotions.py` `_seconds`) show TikTok
  sends milliseconds. The raise was inside the first session block, so the whole transaction
  rolled back: **the shop has no `promotion_activities` / `promotion_activity_products` rows
  and no promotion external changes.** The products half had committed (`reconciled`). Fix
  per D67.1–2. The next nightly run sees `stored` empty and does the one-time backfill (all
  four statuses), so the history recovers. Activities created and ended between connect and
  that run are kept as rows, but as backfill they get no "start" / "deactivate" change rows,
  by design. Webhook 63 / 39 parsing uses the same function, so a ms `update_time` there would
  also have raised; it no longer can.
- **Bug 2, `bootstrap_shop` 106013.** `TikTokClient._build_params` (client.py:720) adds
  `shop_cipher` only when the client has one. The bootstrap passes `credential.shop_cipher`
  (orchestrate.py:385 `_factory_config`) unchanged, so the shop's read credential row has
  `shop_cipher` NULL / "". The OAuth write has stored a vendor-verified cipher since #1200
  (`tiktok_oauth.py` :198 / :220), so the row predates it, or came from a hand fix / restore.
  The cadence: `shop_poll_fanout` (:07/:22/:37/:52) enqueues `bootstrap_shop` for every
  pollable shop without `fast_done_at` (shop_ingestion.py `run_fanout`). The failure leaves
  `fast_done_at` unset and the credential `active`, so it repeats forever. The log's 21:37 and
  00:07 are two of those ticks. **That shop never completed bootstrap.** It has no orders /
  products / returns / inventory sync, no 30-day analytics window, no history phase, no
  diagnosis report and no scored cards. Product history skips it too (fast-done shops only).
  The quick scan uses the same credential, so it also had no cipher. Fix per D67.3–4.
  The URL in the ERROR came from `raise_for_status()`'s message ("… for url:
  https://…?app_key=…&sign=…"). `_handle_response` appended the body but kept that message
  and chained the original, so the traceback printed it twice.
- Tests: `test_p23_product_history.py` +26 (24 epoch shapes incl. ms / µs / ns / "" / 0 / NaN /
  1e400; a sweep with ms create/update + `end_time` 0 + string begin_time; one activity whose
  upsert raises after dirtying its savepoint → skipped and logged, the other stored with its
  products). `test_shop_ingestion.py` +5 (`TestMissingShopCipher`: cipher fetched, stored, sent,
  not re-fetched; zero shops → `needs_reauth`, nothing sent, dropped from
  `enumerate_pollable_shops`; blank cipher → `needs_reauth`; transient `ConnectionError` →
  credential untouched; stored cipher → no lookup). `test_tiktok_error_body_is_surfaced.py` +4
  (400 / 106013 message and logged traceback carry no app_key / sign; transport error keeps
  its type and loses the query; text without a URL unchanged).
- Verification (laptop at load avg 7–15 throughout):
  - Affected files: 102 passed alone, with and without Postgres. Ruff and mypy clean on the 7
    source files. Gitleaks: a realistic-looking test cipher tripped `generic-api-key`, so it
    became `ROW_fake-cipher-for-tests` and the commit was rebuilt.
  - No-database unit suite (`pytest tests/unit -m "not live"`, no `DATABASE_URL`): 7540
    passed, 31 failed. 27 were `test_agent_events_contract` (fresh worktree, no
    `node_modules`; 37/37 after `pnpm install`). 4 were load timeouts (`juli_app_grants` scan,
    `ops_api`, `ops_d28_costs`, `ratchets`), and all 86 tests in those files pass alone.
  - `fasttrack/check.sh` (deploy default `--since origin/main`; Docker unresponsive, so a
    throwaway Homebrew Postgres 16 in UTC on :55440, recreated per run and dropped after):
    migrations, isolation (12), gitleaks and ruff (508 files) PASS. pytest (224 files) left
    only pytest-timeout failures, and each run hit a different set: run 2 failed in migrations
    on a reused DB, run 3 had 3 × `TestHistoryPhase` (3 s alone), and the last run had 1 ×
    `test_juli_app_grants_cover_mutations::test_the_scan_is_not_vacuous`, a whole-tree scan
    that takes 15 s alone against the 30 s default. The last run was 3287 passed, 1 failed.
    Every failed test passes alone, so check.sh reports FAILED only on load-bound timeouts.

## 2026-10-19 — agent (Claude Opus) — P57 rollback works again (D66)

- Branch `fasttrack/rollback-fix` from 310cc0e1, worktree `/Users/macos/juli-fasttrack-rollback`.
  No SSH, no VPS action, no AWS change.
- **Topology, read from the repo.** API / Demo / Landing are served by transient
  `juli-<lane>-candidate-<port>` units on paired slots (8000/8020, 3001/3021, 3007/3027);
  `/etc/nginx/juli/<lane>-upstream.conf` names the live slot; `~/releases/{current,
  demo-current,landing-current}` name the release; worker + beat run `~/releases/current`.
  The durable `juli-api` is stopped after every deploy (#1069), so it is not a health signal.
  A release dir carries only the lanes its deploy built (venv / demo tarball / landing
  tarball); `deploy-history.log` gets one line per successful deploy.
- **A** `juli-web` removed from the unit dir, env templates, `fetch-secrets.sh`,
  `refresh-secrets.sh`, the IAM template, nginx and unit comments, and tests (a new test
  scans every script, unit, nginx conf and workflow). `juli-api.service` keeps its stale
  comment (API lane path filter; DEBT P57).
- **B** `rollback-release.sh` rewritten (sources `deploy.sh`): all-lane rollback to an earlier
  deploy, per-lane state reconstruction, back = landing → demo → api, forward = api → demo →
  landing, loopback + public checks, automatic undo, target-release units, Celery restart +
  queue check, `--plan` / `--verify`, PASS/FAIL summary, `ROLLBACK-TO` history line and a
  JSON record. Never touches the database. Two follow-ups found while testing: refuse a free
  slot something else still answers on (durable unit after a reboot), and skip releases a
  rollback already moved away from when picking the default target.
- **C** `rollback.yml`: tag `fasttrack-rollback-*` or dispatch from the fast-track ref; no
  `git checkout main`; `ROLLBACK_INTERFACE=2` gate; deploy concurrency group; public check.
- **Found by the simulation:** `deploy.sh`'s `celery_unit_queues` read the `-Q` list from a
  comment in `juli-celery-worker.service`, so only 3 of 6 queues were ever verified (fixed,
  D66.6); `rollback-demo-release.sh` died on a grep miss under pipefail before its
  release-dir fallback (fixed).
- **Proof.** `tests/unit/test_rollback_release_simulation.py` (31 tests, the real scripts on a
  fake release pool with stubbed systemctl / systemd-run / journalctl / nginx / curl; ~100 s
  at load 7–10, so it adds ~1–2 min to `backend-unit`) and `test_rollback_workflow.py` (17,
  incl. the resolve step run with a stub git). shellcheck clean (rollback-release.sh,
  fetch-/refresh-secrets.sh, rollback-demo-release.sh); actionlint clean (rollback.yml,
  fasttrack-deploy.yml).
- **No-database unit suite** (`env -u DATABASE_URL pytest tests/unit -m "not live"`, juli venv,
  laptop shared with two other full suites, load 7–15): first pass aborted at 48 % on a
  pytest-timeout INTERNALERROR (3713 passed); the remaining 3999 ids re-run: 3877 passed,
  120 skipped, 2 failed — `test_juli_app_grants_cover_mutations::test_the_scan_is_not_vacuous`
  (load timeout; 8.9 s alone, passes) and `test_landing_port_is_unique_across_every_infra_surface`
  (real: rollback-release.sh and a demo vhost comment named 3007/3027; fixed in 1251ca33).
  Affected set at HEAD: 183 passed, 2 skipped.
- `fasttrack/check.sh --since origin/main` (throwaway Postgres 16 on :55436, UTC, dropped
  after): migrations PASS (093 head), isolation 12 passed, gitleaks PASS, ruff PASS (515 files),
  pytest PASS (231 files: 3394 passed, 2 skipped, 1 xfailed). **check.sh: OK**.
- Owner steps: runbook §7 (deploy, then delete `juli/web/production` + IAM ARN, remove the
  unit and `/etc/juli/web.env` on the VPS) and the live drill in §6. Not run.

## 2026-10-19 — agent (Claude Opus) — P59 Search Inventory 12019008 wedges bootstrap (D69)

- Branch `fasttrack/inventory-ids` from `fasttrack/optimize-product` `98b36adf` (the deployed
  release, so line numbers match the 11:52 UTC log). P59 / D69 were free.
- **Root cause confirmed.** `orchestrate._synced_product_ids_fn` returned every non-empty
  `tiktok_product_id` from `ProductsRepo.list` with no status check. `sync_products` asks Search
  Products with the default status `ALL`, so deleted and draft products are stored too (their raw
  TikTok `status` lands in `products.status` via the ETL). `sync_inventory` sent them 30 per page.
  Search Inventory refuses the whole request when one id is not accepted (12019008).
  `sync_inventory` re-raises (#1948), the bootstrap fast phase fails, `fast_done_at` stays unset and
  the 15-min fan-out retries forever. The path was first reached after P58 fixed the cipher. The
  bundled OAS lists the product status enum but not which statuses Search Inventory accepts; the
  production shop's rejected ids are unknown (no live calls).
- **Pickling.** `TikTokAPIError.__init__(code, message, request_id)` calls
  `super().__init__("[code] message")`, so `args` is one string and the default reduce replays
  `cls("[code] message")`, a TypeError on unpickle. That is the Celery
  `UnpickleableExceptionWrapper`. `TransportGuardError` and both pagination errors (keyword-only
  constructors) had the same defect; all four now reduce over their constructor arguments.
- Fix per D69. Code: `workers/services/polling/sync.py` (constants + `inventory_searchable_status`
  ~:449–497, `_InventoryFetcher` :499, `sync_inventory` page loop + all-rejected guard ~:1050–1100,
  `SyncOutcome.skipped_product_ids` :106), `orchestrate.py` :445 (status filter + log),
  `integrations/tiktok/exceptions.py` :40 / :90, `client.py` :102 / :142.
- **Rate limit.** Main page calls are unchanged (the step still takes one token for all its
  pages, as before). Isolation calls draw from a separate `...inventory/search:isolate` bucket
  (10 / 60 s) and a 10-call per-step cap. Worst case for one rejected id in 30 is exactly 10 calls
  (checked over all 30 positions); an all-rejected page would need 58 and stops at 10.
- `services/execution/inventory_leakage.py` calls `InventoryResource.search(sku_ids=...)` only, on
  the sandbox write path, no product ids and no poll: not affected, not changed.
- Tests: new `tests/unit/test_inventory_rejected_product_ids.py` (39): status filter (deleted /
  draft out, every other and unknown status kept, the repo-backed id source + its log), one
  rejected id in 30 at five positions and at all 30, mixed pages, an all-rejected page beside a good
  page (skipped, cap honoured), every id rejected still raises, three non-12019008 errors raise
  without bisecting, an error mid-bisection raises, own bucket vs step bucket, exhausted isolation
  bucket (one refused acquire, no extra calls), step-bucket refusal, skip log fields, pickle round
  trips (6 classes + `error_from_response`). #1948's `test_raises_instead_of_swallowing_api_error`
  and `test_raises_instead_of_discarding_a_non_dict_response` unchanged and green.
- Verification: ruff + format clean, mypy clean on the touched modules (33 files). No-DB unit
  suite (`pytest tests/unit -m "not live"`, juli venv, PYTHONPATH pinned): 7689 passed, 245
  skipped, 2 xfailed, 27 failed — all 27 `test_agent_events_contract.py` (fresh worktree had no
  `node_modules`); after `pnpm install` that file alone: 37 passed. Integration
  `test_inventory_poll_etl_upsert.py` + `test_fujiwa_polling_sync_state_e2e.py` on the throwaway
  DB: 4 passed. `fasttrack/check.sh --since origin/main` (Homebrew Postgres 16 on :55441, UTC,
  removed after): migrations PASS (094 head), isolation 12 passed, gitleaks PASS, ruff PASS (543
  files), pytest PASS (242 files: 3580 passed, 2 skipped, 1 xfailed). **check.sh: OK**.
- Owner after deploy: grep the worker journal for `sync_inventory_product_skipped`,
  `sync_inventory_products_excluded_by_status`, `shop_bootstrap_fast_done`,
  `shop_bootstrap_failed` (the event is named that way; the Celery task is `bootstrap_shop`) and
  `12019008` (DEBT P59 first item).

## 2026-10-20 — agent (Claude Opus, lead + 7 sub-agents) — sync main, D70 data platform, P60 ADRs

- Main checkout cleaned: uncommitted TTS Open Toolkit wiring moved here (`c7e620c9`, 8 tests);
  rest stashed in the main checkout ("2026-10-20 main cleanup"). PR #2147 (grill log) merged.
- Merge `origin/main` → this branch (`aa70ce86`): landing + `packages/brand` kept as deployed
  (`fasttrack-deploy-20261019T1407Z`; `/product` 301 → `/san-pham`); #2128 shop-videos fetch
  ported to `services/shop_diagnosis_daily/fetch.py`, called from the manual script only (daily
  rankings job keeps its P8b budget); main's Shopee ISV ADR renumbered 109 → **111** (epic #2139
  updated). Related unit tests: 988 passed, 3 skipped.
- P60-0a `P0_TIKTOK_WEBHOOKS.md`: no webhook for price, SKU add/remove, seller deactivate/delete,
  coupons → `update_time_ge` poll. P60-0b `GAP_MAP_FASTTRACK.md` (one claim corrected by ADR-113:
  the snapshot hash already covers images/status/category/prices).
- ADR-112 (ingestion platform), 113 (shop data), 114 (experiments), 115 (training + model gate),
  ADR-107 accepted + amended; notes on 029, 046, 077, 104, 105. ADR tests: 358 passed, 8 skipped.
- **Owner flags** (written into each ADR; numbers are proposed defaults):
  - 107: `shown` = first display only; nullable `card_id` for card-less `seller_change` /
    `shadow`; new `reverted` event and `mixed` attribution.
  - 112: keep `DEMO_REFERENCE_SHOP_ID` in `api/routes/demo_analytics.py` (Demo binding, ADR-094);
    days 61–90 queued right after connect for L2; old bronze not converted to partitions; N = 7
    days, tolerances (counts exact, GMV ≤ 0.5 %, traffic ≤ 1 %), 20 % P2 reserve; archive in a
    private Supabase Storage bucket.
  - 113: SKU stock out of the version hash (→ `inventory_daily`); `product_changes` poll every
    15 min outside the D27.3 60-min gate; Shopee dimensions decided at P8. Bug found: same-day
    A→B→A revert lost by the day-unique key on `product_snapshots` (fixed by the version chain).
  - 114: Ops groups (D34/P30) need seller consent from now on; consent copy vs D61; control share
    0.5 (was ~1/3); one SECURITY DEFINER `ml` write path for the app role.
  - 115: revoke `UPDATE` on `gold.ml_feature_snapshots`; thresholds (coverage ≥ 0.80, acceptance
    −10 pts, min 30 decisions / 20 readings, shadow 2–8 weeks).
- Next: owner answers the flags → P60-1a `card_events`. Owner: P60-0c DB query, P60-0d depth.

## 2026-10-20 — agent (Claude Opus) — P60-1a `card_events` (branch `fasttrack/p60-card-events`, not merged)

- Migration `095_card_events` (onto 094; deferred phone cleanup re-parented, its 12 pinning tests
  updated): the amendment's columns, CHECKs on `event_type` / `actor` / `source`, `card_id` NULL
  only for `seller_change` / `shadow`, dismiss `reason_code` enum (a column, required on
  `dismissed`), live `proposed` needs `model_version`; unique (`shop_id`, `dedup_key`) + partial
  unique (`card_id`, `event_type`) for once-per-card types; the three ADR indexes; RLS on,
  `juli_app` SELECT/INSERT only; `tenant_direct` in `tenant_scoped_tables.py`. Model
  `models/card_events.py`.
- `services/card_events/` (writer, keys, outcomes, backfill). Live writers run in the caller's
  transaction inside a SAVEPOINT and never raise (`card_event_write_failed`). Wired: `proposed`
  + `superseded` (`persist.emit_scoring_cards`, quick scan), `shown` + `expired`
  (`apply_emission_budget`), `accepted` (`approve_action_card`), `dismissed` ("Từ chối" route),
  `executed` / `not_executed` / `reverted` (beside every `reactivate_card_for_ended_run` caller
  + lever-flow seller decline), `impact_*` (impact reader + both `run_measurement_finals`
  writers). Backfill `backfill_shop` + manual Celery `juli_backend.card_events_backfill(shop)` /
  `..._fanout` (not on beat).
- **Choices where the ADR and the code disagree** (all in DEBT P60-1a): `accepted`,
  `executed`/`not_executed`, impact are once per approval/run, not per card (D47.5 puts a card
  back after a failed run); `dismissed.reason_code = 'unspecified'` with the P10-A reject code in
  the payload (the route's codes are not the five reasons); a run decline / revert is not a
  `dismissed` (it is the run's `not_executed` / `reverted`); `seller_change` left to P60-1b
  (needs §8 attribution; an append-only unattributed row would block the right one);
  `readiness_level` / `feature_snapshot_id` NULL (no D3 levels, no snapshot writer);
  `subject_id` = TikTok product id (card's own in `payload.card_subject_id`); `occurred_at`
  timestamptz as the ADR says.
- Verification: ruff + format clean; mypy clean on 22 touched source files.
  `tests/unit/test_card_events.py` 38 passed. `tests/integration/test_card_events_db.py` on
  Homebrew Postgres 16 :55441 (UTC, removed after): 9 passed, 0 skipped (RLS + grants, two
  tenants, refused write leaves the caller's transaction usable, UPDATE/DELETE denied, CHECKs +
  uniques, backfill twice = same rows, downgrade -1 / upgrade head). No-DB unit suite
  (`pytest tests/unit -m "not live"`, after `pnpm install`): 7763 passed, 245 skipped, 2
  xfailed, 1 failed (`test_test_quality` reconciliation: 4 new pytest.raises-only tests) — fixed
  by adding asserts, that file + touched-area files then 81 / 300 passed.
  `fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS (095 head), isolation
  12 passed, gitleaks PASS, ruff PASS (39 files), pytest PASS (32 files: 531 passed, 0 skipped).
  **check.sh: OK**.
- Next: owner merges into `fasttrack/optimize-product`, deploys, runs
  `celery ... call juli_backend.card_events_backfill_fanout` and checks
  `card_events_backfill_done` lines. Then P60-1b (hashes + attribution + `seller_change`), P60-1e
  (feature snapshot in the `proposed` transaction).

## 2026-10-20 — agent (Claude Opus) — P61-A agent reads per shop (branch `fasttrack/p61-a-agent-read`, not merged)

- Bug (D71.1): `services/agent/composition.py::build_read_resources` resolved the configured
  production merchant (`resolve_production_read_credential` + `PRODUCTION_AUTH_ID`) for every
  non-sandbox shop, so an agent run for shop B read the reference shop's catalogue (callers:
  `agent_workflow._default_read_resources`, `content_runs`, `content_analysis/product_info`).
- Fix: the sandbox-write shop keeps the sandbox resources (#1302); every other shop resolves
  `resolve_read_credential_for_shop` under `with_shop_scope(shop)` and signs with that
  credential's `merchant_authorization_id` / `shop_cipher` / token. `shop_id` required
  (`AgentReadShopRequired`); no credential → `NoReadCredentialForShop` (a `NotFound`); a row not
  owned by the shop / not read-capable / without merchant id → `AgentReadCredentialMismatch`
  before any client is built. `_default_read_resources(session, shop_id)` now requires the shop.
  `analytics_backfill.backfill_analytics_history_auto_topup` resolves the shop's read credential
  (production_read or seller_connect) and signs with its own merchant id (was
  `PRODUCTION_AUTH_ID`); skip reason renamed `missing_read_credential`.
- Tests: `tests/unit/test_agent_read_resources_per_shop.py` (8: shop A, shop B, sandbox shop,
  no credential, `None`, wrong owner, backfill A/B + skip); `test_read_resources_shop_aware_routing`
  None-fallback test → refusal test; `test_agent_workflow_task_wiring` passes a shop.
  `tests/integration/test_agent_read_two_shop.py` (4, real Postgres as `juli_app`, two seeded
  shops — production_read + seller_connect, neither the reference merchant — fake factory captures
  `ClientFactoryConfig`): B's read carries B's token/cipher/merchant and none of A's; A's carries
  A's; unknown shop fails closed; backfill for B signs with B's merchant. Added to
  `_SHARED_STATE_MODULES` in `tests/conftest.py`.
- Verification: ruff + format clean; mypy clean on the 3 touched source modules. Homebrew
  Postgres 16 :55451 (UTC, removed after): `test_agent_read_two_shop.py` 4 passed, 0 skipped.
  `fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS (095 head), isolation
  12 passed, gitleaks PASS, ruff PASS (9 files), pytest PASS (10 files: 69 passed, 0 skipped,
  1 deselected live) — **check.sh: OK**. No-DB unit suite (`tests/unit -m "not live"`): 7769
  passed, 245 skipped, 2 xfailed, 3 failed (`test_credentials_in_url_guard::test_zero_findings...`,
  `test_juli_app_grants_cover_mutations::test_the_scan_is_not_vacuous`,
  `test_ops_d28_costs::test_cap_writes_are_admin_only[operator]`) under load from a concurrent
  suite; all 3 pass re-run alone (3 passed), none touch P61-A code.
- Not changed (DEBT P61-A): `cdp_speed/targeted_fetch_executor.py` still single-tenant.

## 2026-10-20 — agent (Claude Opus) — P60-1b hashes, per-field attribution, `seller_change` (branch `fasttrack/p60-attribution`, not merged)

- Migration `096_change_attribution` (onto 095; deferred phone cleanup re-parented, its pins
  updated): `run_write_values` + `before_hash`, `after_hash`, `before_read_at`,
  `production_write_audit_id` (FK); `external_changes` + `attribution` (CHECK juli /
  seller_revert / seller_change / mixed, NULL only for pre-096 code) and `field_attribution`
  jsonb. Grants unchanged (append-only for `juli_app`). `juli_app` has no UPDATE, so the
  migration's owner-run data step fills existing rows: hashes, the audit link (only when
  exactly one audit row matches run / product / mutation_kind = tool name) and attribution.
  The step carries frozen copies of the rules (`database` may not import `services`), pinned
  equal to the services by unit tests. New `enumerate_history_shops()` (SECURITY DEFINER, ids
  only, EXECUTE juli_app only) for the backfill fan-out.
- One hash helper `product_history.normalize.field_value_hash` / `ProductFields` (the form
  `product_snapshots` hashes; unit-tested equal to snapshot hashing); `attribution.py` (pure
  §8 rules); `store.attribute_fields`; `matches_juli_write` = all `juli` (callers unchanged,
  `juli_write` kept). `record_change` stores attribution and, for a change not entirely
  Juli's, writes `seller_change` via `card_events.natural` (live, never raises): card = the run
  that last wrote the field, else the card with an executed run on the product in the last
  `OPEN_PLAN_WINDOW` (14 d), else NULL (`workflow_key='natural'`). Recorder writes hashes,
  `before_read_at` (executor's before read) and the audit link. Revert check compares hashes
  when both exist, values otherwise (plan carries `expected_hashes`); D13 unchanged.
- Backfill: `card_events_backfill` also writes `seller_change` (source `backfill`, key
  `seller_change:<external_change_id>`, idempotent); the fan-out now iterates shops from data
  (cards, writes, changes; disconnected shops included) plus pollable shops.
- **Spec vs code** (DEBT P60-1b): agent writes record no `production_write_audit` row and audit
  `mutation_kind`s differ from tool names, so the audit link is NULL for all current writes; the
  "plan window" is a 14-day post-execution window (no decision-7 plan yet); one event per
  change row, not per field; price attributed on Juli's `price` (list) field.
- Verification: ruff + format clean; mypy clean on 16 touched source files.
  `tests/unit/test_change_attribution.py` 66 passed. Homebrew Postgres 16 :55442 (UTC, removed
  after): `tests/integration/test_change_attribution_db.py` 12 passed, 0 skipped (two fresh
  tenants: Juli write -> juli / seller_revert / seller_change re-reads -> attribution ->
  `seller_change` rows with card / NULL; tenant B sees none of A; CHECK; append-only; definer
  function; 096 down to 095, pre-096 rows seeded, up -> data step; backfill twice = same rows);
  with `test_card_events_db`, `test_run_changes_two_tenant`, `test_schema_parity`,
  `test_fleet_enumeration_functions`: 32 passed. `test_migrations.py` + RLS suites: 71 passed,
  1 failed (`test_no_public_table_holds_update_beyond_its_call_site`, pre-existing: 18 older
  tables, none of P60-1b's). Full no-DB unit suite after the last code change
  (`pytest tests/unit -m "not live"`): 7821 passed, 245 skipped, 2 xfailed, 1 failed —
  `test_status_record_gate` 30 s timeout under machine load (load avg ~25-32); that file alone:
  50 passed. First full run had also flagged `import_boundaries` (migration imported services:
  fixed by frozen copies) and `test_test_quality` (one assert-less test fixed; corpus figures
  re-derived with `reconcile --write`). `fasttrack/check.sh --since fasttrack/optimize-product`:
  migrations PASS (096 head), isolation 12 passed, gitleaks PASS, ruff PASS (36 files), pytest
  PASS (29 files: 576 passed, 0 skipped). **check.sh: OK**.
- Production steps (owner): merge, deploy (migration 096 runs; its data step fills existing
  rows), then `celery -A juli_backend.workers.celery_app call
  juli_backend.card_events_backfill_fanout`. Check: `card_events_backfill_fanout` (shops /
  enqueued) and per shop `card_events_backfill_done shop_id=... inserted={... 'seller_change': N}`;
  no `card_event_write_failed event=seller_change` lines afterwards; `run_write_values_recorded`
  continues. SQL spot check: `SELECT attribution, count(*) FROM external_changes GROUP BY 1`
  (no NULL after the restart).

## 2026-10-20 — agent (Claude Opus) — P61-C token streaming (branch `fasttrack/p61-c-streaming`, not merged)

- Adapter (`services/agent/llm/openai_adapter.py`): `complete(..., on_text_delta=cb)` sends
  `stream: true` to the Responses API when `LLM_STREAMING` is on (default; `0/false/no/off`
  turns it off), awaits `cb` per `response.output_text.delta`, assembles tool-call arguments from
  `function_call_arguments.delta/.done` + `output_item.done` (the `response.completed` body's
  `output` wins when present) and returns the same complete `AssistantTurn`. `response.failed`,
  `error`, no terminal event, transport error mid-stream, non-JSON frame -> `LLMProviderError`
  (run ends `llm_error`). No callback (card drafts, structured analysis, scoring) -> non-streamed
  as before. `on_text_delta` is not on the `LLMService` protocol; `FakeLLMService` gained
  `stream_chunk_chars`.
- Event: `assistant.text.delta {block_id, chunk_index, text}` added to the union on both sides
  (payloads/envelope, `packages/contracts/src/agent-events.ts`, golden fixture; the "reserved"
  invalid fixture became "missing block_id"). Persisted like every event, no migration.
- Runner: `WorkflowRunner(stream_text=True)` (worker sets it for the real adapter only, never the
  scripted planners) uses `runner/text_stream.py::TextDeltaRelay` — coalesces (48 chars / 100 ms),
  runs `guard_outbound_agent_output` over the whole received text before every emit and releases
  only text 64 chars short of its end; a hit stops the turn's stream. `block_id = b<next_sequence>`.
  A streamed `FinalResponse` is committed with an `assistant.text` before `workflow.completed`.
  Ops run timeline hides deltas.
- Demo: `reduceRunView().liveNarration`, `buildRunTimeline().narrationStreaming`; the run panel's
  running note shows the preview with a blinking caret (`aria-busy`, reduced-motion off), replaced
  by the committed text; replay dedupes by sequence number. Golden scenario
  `optimize_product_streamed.json` captured by the tool from the real runner drives the vitest.
- ADR-071 amendment section added; MODULE.md (agent, agent/llm) updated; DEBT P61-C.
- Verification (after merging `fasttrack/optimize-product` 6856375a, 096 head): ruff + format
  clean; mypy clean on 13 touched source files. New tests: adapter streaming 21, relay + runner 9,
  streamed golden 2, contract/envelope updated (40 / envelope file green), SSE integration on
  Homebrew Postgres 16 :55453 (UTC, removed after) 2 passed (live delta before the final text
  exists in the DB, reconnect via Last-Event-ID with no duplicate ids/text, two shops concurrent
  without crossing + 404 on the other shop's stream). Full no-DB unit suite
  (`tests/unit -m "not live"`, Node 20): 7865 passed, 245 skipped, 2 xfailed, 2 failed —
  `test_action_card_refresh_cooldown::test_slow_backing_store...` and
  `test_agent_run_event_stream::...test_subscribe_failure_degrades_to_postgres_polling`, both
  timing tests under load avg ~50 (other agents' suites); both files alone 26 passed.
  Demo: lint 0 errors (1 pre-existing warning), tsc clean, vitest 122 files / 1208 passed (Node
  20; Node 26 breaks 29 Web Storage files). Contracts: type-check clean, vitest 66 passed.
  `fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS (096 head), isolation
  12 passed, gitleaks PASS, ruff PASS (22 files), pytest PASS (13 files: 187 passed).
  **check.sh: OK**.
- Owner after deploy: one live run; `workflow_run_events` should hold `assistant.text.delta` rows
  followed by `assistant.text`; no new `llm_error` stops. Off switch: `LLM_STREAMING=off` + restart.

## 2026-10-21 — owner + lead — P60-1a/1b production backfill

- Deploys `fasttrack-deploy-20261020T1227Z` (P61-A) and `…T1324Z` (P60-1b, migration 096) green.
- Owner ran `card_events_backfill_fanout` on the VPS (00:15 UTC): 2 shops enqueued, 0
  `card_event_write_failed`. `1862f13b…` (sandbox-write shop, where approved runs execute):
  60 rows — proposed 4, shown 4, accepted 25, not_executed 18, executed 7, impact_preliminary 1,
  impact_final 1. `2b1da87b…` (Fujiwa): 59 rows — proposed 22, shown 11, seller_change 26.
- Note: accepted (25) > proposed (4) on the sandbox shop — `accepted` is per approval and most
  approved cards predate a reconstructable `proposed` (ADR-107 amendment backfill table); not an
  error. No Fujiwa accepted/executed rows because runs execute on the sandbox shop until P5 (P61-B).

## 2026-10-21 — agent (Claude Opus) — P61-B production write per shop, flags off (branch `fasttrack/p61-b-prod-write`, not merged)

- Migration `097_production_write_shops` (onto `096_change_attribution`; deferred phone cleanup
  re-parented, its pins + the 095/096 round-trip tests updated): `production_write_shops`
  (owner-written per-shop enable, `juli_app` SELECT only, RLS tenant-direct) and
  `workflow_runs.write_mode` (`live` | `simulated`).
- TikTok layer: `ProductionWriteClientFactory` / `ProductionWriteResources` behind
  `ProductionWriteGuard` (product detail / SEO / suggestion GETs, listing edit PUT, image upload;
  no price, no create — D13). `resolve_write_credential_for_shop`: the shop's own non-sandbox row.
- Resolver also requires the shop's enable row (else the sandbox, exactly as flag off). Listing
  handler production leg runs on the shop's own resources and records `run_write_values`; price /
  create / run-less executions refused before an authorization is spent; mutation kind is the
  tool's own name. `build_write_resources(session, shop_id, capability)`; agent runs stamp
  `write_mode` (always `simulated` today — the agent leg itself is DEBT P61-B).
- Honest UX: run list `simulated`, card status `simulated`, chips / done panel "Đã chạy thử",
  simulated runs out of Đo lường. Measurement: impact reader skips simulated writes (and does not
  count them as touches); a simulated listing run has no Đo lường.
- Coordinator add: `composition._is_sandbox_shop` catches only `NotFound` now (2 tests).
- Test-infra fixes found on the way: `test_production_write_authorizations_postgres` left the
  shared DB at 044 (now restores head in `finally`, 300 s timeout); 087 pin keeps P60-1b's 096
  column allowance after the merge.
- Verification (Homebrew Postgres 16 :55452, UTC, removed after): `test_p61b_production_write.py`
  38 passed; `test_p61b_production_write_two_shop.py` 3 passed on Postgres as `juli_app`
  (0 skipped); check.sh `--since fasttrack/optimize-product`: migrations / isolation (12) /
  gitleaks / ruff PASS, pytest 852 passed + 1 timeout under machine load average ~30
  (`test_waiting_external_migration`, 19/19 alone). Full unit suite `tests/unit -m "not live"`:
  7908 passed, 245 skipped, 2 xfailed, 1 failed (`test_status_record_gate`, 50/50 alone, load).
  mypy clean on 25 touched source files. Demo (Node 20): tsc + lint clean; vitest flaky
  timeouts under load (~50): full run 1200/1212, every failing file then passed when re-run
  alone (e.g. email-sign-in + demo-landing + simulated-run-p61b 38/38; ops-pages 17/17).

## 2026-10-21 — agent — P62-B scoped reads, `processed_events` retention (D72.2–4)

- **Reads (D72.3).** The three whole-table `analytics_performance_intervals` SELECTs and the
  whole-table `silver.orders` SELECT were ONE code path: `compute_demo_main_kpis_payload` (the
  gold stage of `run_shared_compute_job`: every material webhook and the hourly reconcile; NOT the
  `/v1/demo/analytics` route, which only reads the stored `gold.kpi_envelopes` row — the uptime
  probe never recomputes, so no cache was added; the route and the two retiring beats were not
  touched, per the owner's later instruction). Now: one aggregate row per order day + two
  single-row interval aggregates (values unchanged, all-time by contract). Second path:
  `build_feature_aggregates` (scoring / refresh) read the shop's newest 10,000 interval rows, all
  grains and columns; now the 30-day KPI window and six columns. Third: `load_product_days`
  (optimize-product plan) now column-pruned for product rows and SKU rows summed per product-day
  in SQL. Row counts on real Postgres, two shops, shop B with 120 days of the same shape: gold
  recompute for shop A reads 24 rows (was 60 orders + 270 intervals = 330); scoring interval
  read 210 rows (was all 540 of shop A's); product-day read 240 rows (was 360 + wide).
- **Estimated rows read per day** (production, from the D72 pg_stat_statements; calls spread over
  the ~17-day cycle ≈ 104 interval + 24 order calls/day): before ≈ 400k interval rows + 90k order
  rows/day; after ≈ 3k rows/day. Estimated egress per day, before → after: gold recompute
  interval+orders reads ≈ 60–200 MB → < 1 MB (row widths 0.4–0.7 KB from the seeded table sizes;
  the wide range is the unknown stats window — owner re-checks after deploy).
- **Retention (D72.2).** Migration 098 (on 097): `public.purge_processed_events(days, batch)`
  SECURITY DEFINER (ADR-089 shape; EXECUTE juli_app only; SQL floor 14 days) + index on
  `processed_at`; beat `processed-events-retention` 20:34 UTC; 30-day window, 5,000-row batches,
  ≤ 40 batches/night. Proved on Postgres: `juli_app` cannot DELETE; floor refuses 1 day; two shops'
  old rows deleted in 4 batches, recent rows kept. Egress effect is through dumps only
  (≈ 64 MB → ≈ 40–50 MB of the dump); see DEBT for the larger lever (exclude the table's data
  from the dump).
- **Connection churn (D72.4): not changed.** `NullPool` is forced by `asyncio.run` per task
  (loop-bound asyncpg connections, #871); pooler is Supavisor session mode so a pool would be
  legal, the per-process loop refactor (21 task modules) is the risk; skipped per owner. Report:
  819k `set_config` is already one pair per transaction (re-applied after each of the per-record
  commits); the 661k epoch / claim / shop lookups are per ETL record (3 lookups, 2 savepoints,
  1 commit each) and could be batched per page — DEBT.
- Chain: 098 on `097_production_write_shops`; the deferred phone cleanup re-parented onto 098 and
  its pinned tests updated; `fasttrack/optimize-product` (c15d6b34) merged in.
- Verification: ruff + format clean, mypy clean on touched modules. New tests: unit 6
  (`test_processed_events_retention.py`), Postgres 4 (`tests/integration/test_p62b_scoped_reads_and_retention_db.py`,
  port 55462, all PASSED not skipped); related Postgres tests (batch reconcile gold envelope,
  mock reconcile two-tenant, material shared compute handoff, demo analytics non-owner read,
  ingest two-tenant) 19 passed. Full unit suite `tests/unit -m "not live"` (after `pnpm install`,
  on the merged tree): 7910 passed, 245 skipped, 2 xfailed, 5 failed — 4 were mine and fixed
  (import-boundary deep import, beat minute collision with `shop-poll-fanout`, a connect-event
  role listener and a `type: ignore` in my test; those files re-run: 71 passed) and
  `test_action_card_refresh_cooldown::test_slow_backing_store...` is the known load-timing flake
  (file alone 16 passed). `fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS
  (098 head), isolation 12 passed, gitleaks PASS, ruff PASS (30 files), pytest PASS (21 files:
  562 passed). **check.sh: OK**.

## 2026-10-21 — agent (Claude Opus) — P61-D cleanup + `/v1/demo/analytics` retired (branch `fasttrack/p61-d-cleanup`, not merged)

- **Retired (owner D72.5, egress):** consumer check — `gold.kpi_envelopes` /
  `analytics_kpi_envelopes` are read only by `GET /v1/demo/analytics` (the caches' getters have no
  other caller); the top-up's outputs are re-written per shop by `poll_shop`. So:
  `mock-analytics-hourly-reconcile` + `analytics-backfill-topup` beats, tasks and the
  `DEMO_REFERENCE_SHOP_ID` read deleted (no per-shop replacement); the route answers **410 Gone**
  (no DB/Redis); apps/demo `AnalyticsDataProvider` / `fetchDemoAnalytics` / fallback envelope
  removed ("Làm mới Demo" keeps its resets); `deploy.sh` / `rollback-release.sh` / `uptime.yml`
  probe `/health` only (uptime stays owner-disabled); `check-kpi-freshness.py` + test deleted;
  ADR-094 amendment, ADR-112 §6.5 note. `DEMO_REFERENCE_SHOP_ID` is read nowhere now.
- **Targeted fetch per shop** (owner-approved scope add): `targeted_fetch_executor` resolves the
  job shop's own credential (`resolve_read_credential_for_shop`) and signs with its merchant id.
- **Merchant ids:** no literal defaults; `MerchantIdNotConfigured` (ValueError naming the env var)
  from both factories, the poll guard and the configured-merchant resolvers; test ids in
  `tests/conftest.py`. **Deploy precondition:** both env vars set on API + worker.
- **Loud env:** `core/config/runtime_env.py` — one `runtime_env_missing` WARNING per missing
  variable / off flag at API and worker boot (names only); `GET /v1/ops/runtime-env` (viewer);
  `shop_ingestion_skipped_unconfigured` WARNING with the missing names on every skip.
- **Deleted** `fujiwa_poll_beat` + the `shop_id=None` poll paths; stale docs fixed
  (impact_reader, workers MODULE, restore script requires `SHOP_ID`, obs1 scripts).
- **Reject route** already existed (P10-A; DEBT P7-C and the audit row were stale): made
  idempotent (row lock; repeat = 200, no new rows; another shop still 404).
- Verification (after merging optimize-product c15d6b34, head 097): ruff + format clean; mypy
  clean (728 files). Postgres 16 :55454 (UTC) via check.sh: migrations PASS (097 head),
  isolation 12 passed, gitleaks PASS, ruff PASS (55 files), pytest PASS (58 files: 801 passed,
  1 skipped = the asserted `live_hours` reachability carve-out) — **check.sh: OK**; it covers
  `test_targeted_fetch_two_shop.py`, `test_reject_route_two_tenant.py`,
  `test_fetch_executor_scope.py` on real Postgres. Full no-DB unit suite: 7881 passed,
  245 skipped, 2 xfailed, 0 failed. apps/demo (Node 20 per `.nvmrc`): lint 0 errors, tsc clean,
  vitest 1204 passed / 4 failed under machine load (ops-pages 30 s timeouts, no-shop-sample);
  those files rerun alone: 36 passed. Under load (avg 30-70 from sibling agents) single runs
  also hit pytest's 30 s timeout in Postgres fixture setup; every one passed on rerun.

## 2026-10-21 — agent (Claude Opus) — P62-A fewer dumps (branch `fasttrack/p62-a-dumps`, not merged)

- D72.1. `safe-alembic-upgrade.sh`: pre-migrate dump (and its disk preflight) only when
  `pending-revisions` is non-empty; else logs `no pending migration — pre-migrate dump skipped`.
  Fail-closed unchanged when pending (dump failure / low disk abort before `alembic upgrade`).
  `safe-alembic-upgrade-local.sh` untouched (manual developer tool, no automated caller).
- `fasttrack-deploy.yml`: new `plan` job (SSH reads production `alembic current`; stdlib
  `infra/scripts/migration_heads.py` computes the SHA's head from the migration files' AST) →
  `backup` runs only if `backup=true` (differs / unknown / several heads / force). `force_backup`:
  workflow_dispatch boolean, tag suffix `-force-backup`, or repo variable `FASTTRACK_FORCE_BACKUP`.
  `check` and `deploy` carry explicit `if: !cancelled() && <each need>.result == 'success'` (check
  also accepts backup `skipped` only when plan said false), so a skipped backup passes, a failed or
  cancelled one blocks. P55 gates unchanged. actionlint clean.
- `infra/scripts/backup-database.sh` (dump + verify + rotation, shared by the job and the timer);
  `juli-db-backup.{service,timer}`: timer daily 19:30 UTC, script dumps only if the newest dump is
  >= `BACKUP_MIN_INTERVAL_HOURS` (72) old; logs `DUMP_SIZE label=… bytes=…`.
- Tests: `tests/unit/test_backup_dump_policy.py` 46 (heads vs alembic, decide, workflow
  `if` evaluation, fake-VPS shell runs of both scripts, units). Real Postgres 16 (:55461):
  `tests/integration/test_safe_alembic_upgrade.py` 6 passed (incl. new no-pending-skips-dump; the
  disk-preflight test now makes a migration pending), run with a stub `docker` so the pg16 CLIs are
  native; added a 300 s timeout (30 s default timed out the per-test schema reset).
- Verified: ruff + format clean, mypy --strict on migration_heads.py, shellcheck clean. Full
  `tests/unit -m "not live"` after the P61-B merge: 7953 passed, 245 skipped, 2 xfailed, 1 failed
  (`test_slow_backing_store_does_not_stall_the_event_loop`, known load timing test). check.sh
  (--since fasttrack/optimize-product, 097 head): migrations PASS, isolation 12 passed, gitleaks
  PASS, ruff PASS, pytest 51 passed. Merged P62-B/P61-D (098 head) afterwards; only PROGRESS conflicted.
- Egress estimate: 35–70 MB per full dump (coordinator figure; not measured — first `DUMP_SIZE`
  line will tell). Before: ~2 dumps/deploy x ~4 deploys/day = 8 dumps/day ≈ 280–560 MB/day.
  After: scheduled 1 per 3 days ≈ 12–23 MB/day (≈ 0.35–0.7 GB/month) + 2 dumps only on deploys with
  a migration.

## 2026-10-21 — agent (Claude Sonnet) — P61-G merchant identity from the connect flow (branch `fasttrack/p61-g-merchant-from-credential`, not merged)

Owner decision D71.6: no merchant id hardcoded or configured. Removed `PRODUCTION_AUTH_ID` /
`SANDBOX_AUTH_ID`, `require_*`, `MerchantIdNotConfigured`, `resolve_merchant_context`,
`is_cross_merchant_lookup`, `resolve_production_read_credential` and both `TIKTOK_*_MERCHANT_ID`
env vars (+ P61-D boot-report entries). Factories decide from `credential_capability`; the
sandbox credential is found by capability through migration 099
(`enumerate_sandbox_write_credentials()`, on 098, deferred 074 re-parented onto it) and refused
(`SandboxCredentialRefused`) when it shares a merchant id or shop cipher with a non-sandbox
credential (the 2026-08-18 case, now also at resolve time); read/write resolvers skip a row
holding a merchant a `sandbox_write` row carries. OAuth keeps an existing row's capability.
Merged P62-A (671dc99b) before verification. Verification: unit `tests/unit -m "not live"`
7912 passed, 245 skipped, 2 xfailed, 1 failed (`test_slow_backing_store_does_not_stall_the_event_loop`,
timing under load; 16 passed alone); new tests: 14 unit (credential-derived, no env) + 3 real-Postgres
two-shop/sandbox tests (port 55471, passed not skipped; 32 passed with the touched integration files);
`fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS (head 099), isolation 12 passed,
gitleaks PASS, ruff PASS, pytest 1002 passed. mypy 21 files clean. `eval.quality_detectors
reconcile --write` re-derived the no-assert corpus figure.

## 2026-10-21 — agent (Claude Sonnet) — P63 `get_shop_identity` agent tool (branch `fasttrack/p63-shop-identity-tool`, not merged)

- Owner request: TikTok Get Authorized Shops (`AUTHORIZED_SHOPS_PATH`, already on the production-read
  allowlist) as a READ tool of the OpenAI agent. Product domain (`tools/product.py`, in
  `PRODUCT_READ_TOOL_HANDLERS`) — the smallest change that fits ADR-069/#1704; no new domain, no
  executor/worker/`composition.py`/`factories.py`/`credential_resolver.py` edit (no merge surface with P61-G;
  no `PRODUCTION_AUTH_ID` / `SANDBOX_AUTH_ID` / merchant env used).
- Behaviour: no model input. The handler calls `resources.authorization.list_all_shops()` (the guarded
  client built by `build_read_resources` from the run shop's own credential) and matches the entry whose
  `cipher` equals the cipher that same client was built with (new read-only `TikTokClient.shop_cipher` /
  `AuthorizationResource.bound_shop_cipher`). Output `{status, shop_matches, shop_name (vendor-text
  envelope), region, seller_type, detail}`; region / seller type are machine tokens or dropped
  (`AuthorizedShop` gained `seller_type`). `status`: `verified`; `mismatch` (token reaches another shop:
  nothing about it returned, warning `agent_shop_identity_mismatch` with the cipher redacted);
  `unverifiable` (credential has no stored cipher); `unavailable` (TikTok/guard error, or sandbox
  resources, which have no authorization resource). Never an id, cipher, token or merchant id.
  Rate limiting: same as every other READ tool (the client's own throttle/retry); no extra limiter.
- Playbook: optional step `0.5` after diagnoses (AUTO, not in `required_steps`). The composed v3 prompt
  was 2992 of the 3000-token ADR-072 d.6 ceiling, so three other step intents (1, 4/4.5, 6) were
  tightened (same meaning) to pay for it: 2997 now, headroom 3. The composed goldens of the released
  v1/v2/v3 prompts and the two golden-scenario `prompt_sha256` were regenerated (the playbook is part of
  the composed text; same precedent as the diagnoses step). Worst-case tool-timeout sum 115 → 125 s
  (run bound 445 → 455 s), documented in `runner/termination.py` and pinned in its test.
- Labels: dictionary `run.option_rationale.get_shop_identity` / `qd.step.get_shop_identity` ("Xác nhận
  shop TikTok"); `apps/demo` `TOOL_STEP_LABELS` in `copy.ts` and `timeline.ts` (no new timeline row —
  the step is optional). `packages/contracts` mirrors no tool names. `surface_inventory.json` regenerated.
  `WORKFLOW_TOOL_CATALOG` (`tool_routing.py`) is the legacy Celery routing table and is untouched; the
  agent catalog is the registry + playbook, and the registry↔catalog test mapping got the new line.
- Tests: `tests/unit/test_agent_tool_shop_identity.py` (17: verified, no id/cipher/token in output,
  vendor-text envelope, non-token region dropped, mismatch refusal + warning without ciphers, zero
  shops, unverifiable, TikTok/guard errors, programming errors propagate, sandbox resources, spec,
  dictionary, registration/reachability, playbook membership/optional). `tests/integration/
  test_agent_shop_identity_two_shop.py` (3, real Postgres as `juli_app`, two seeded shops, real
  `AuthorizationResource` over a fake TikTok transport): B's call carries B's token + cipher and returns
  B's name only; A's likewise; a token that reaches the other shop is `mismatch`. Existing catalog,
  spec-description, playbook, golden, budget, wall-clock and inventory tests updated.
- Verification: ruff + format clean; mypy clean on the 4 touched source modules. Homebrew Postgres 16
  :55481 (UTC, removed after): the two-shop file 3 passed, 0 skipped. `fasttrack/check.sh --since
  fasttrack/optimize-product`: migrations PASS (098 head), isolation 12 passed, gitleaks PASS, ruff PASS
  (19 files), pytest PASS (17 files, 310 passed) — **check.sh: OK**. No-DB unit suite (`tests/unit -m
  "not live"`, run alone): 7951 passed, 245 skipped, 2 xfailed, 0 failed. apps/demo on Node 20: tsc
  clean, eslint 0 errors, vitest 1207 passed + 1 timing flake that passed on re-run (the same file also
  failed under load while the unit suite ran). `eval.ratchets check` lists only pre-existing
  unused-TS-export identities (agent-events.ts, apps/landing), none from this branch.

## 2026-10-21 — agent (Claude Sonnet) — P61-G2 sandbox collision is cross-shop only (branch `fasttrack/p61-g2-same-shop`, not merged)

- Why: production fact (owner): the sandbox shop holds `sandbox_write` (merchant A) and its own `seller_connect`
  (OAuth open_id B), one `shop_cipher`. 099's `out_collides` counted ANY non-sandbox row, so
  `resolve_sandbox_write_credential` would refuse and every agent run (sandbox-bound until P61-F) would fail.
- Change: migration `100_sandbox_collision_xshop` (CREATE OR REPLACE, `AND o.shop_id <> c.shop_id`; signature,
  SECURITY DEFINER, search_path, grants as 099; downgrade restores 099's body, checked by function md5 across
  downgrade/upgrade; grants kept). 074 phone cleanup re-parented onto 100 (pinned tests updated). SQLite path in
  `credential_resolver._enumerate_sandbox_write_credentials` gets the same predicate. `credential_binding`
  (seller_connect exempt; only production_read/sandbox_write governed) and the factories' merchant refusal need no
  change: B differs from A, so the sandbox shop's seller_connect row is NOT excluded and the shop stays a normal
  pollable/readable shop exactly as before P61-G (no products; reads only). No dangerous path found.
- Tests: 2 new unit (same-shop seller_connect not a collision; other shop's cipher still refused beside it), 3 new
  real-Postgres (same-shop usable via `juli_app`; cipher and merchant sharing with another shop refused; function
  body/SECURITY DEFINER/search_path pinned). Postgres :55491: integration file 5 passed 0 skipped; unit RLS-scope +
  phone-cleanup 16 passed 0 skipped; `check.sh --since fasttrack/optimize-product` migrations PASS (100 head), isolation 12
  passed, gitleaks PASS, pytest 21 files 529 passed. ruff/mypy/bandit -ll clean.

## 2026-10-21 — lead — deploy `fasttrack-deploy-20261021T0933Z` (8ed0fd95) green

- Ships P61-B (097), P62-B (098), P61-G (099), P61-G2 (100), P61-C was already live, P61-D,
  P62-A, P63. Two earlier tags failed before the VPS: `…0737Z` at bandit B608 on 098's
  constant-only f-string (fixed 8fd31cdd); `…0851Z` at check.sh — the 096 round trip pinned
  head 097 (fixed 8ed0fd95: compares against the script head). Migration 100's SQL was made
  literal (a0beb15d) so `deploy.sh`'s additive-only gate can read it.
- Owner next (VPS): `alembic current` = 100; remove any TIKTOK_*_MERCHANT_ID from
  /etc/juli/api.env; install `juli-db-backup.timer`; `select pg_stat_statements_reset();`;
  re-enable Uptime Check after confirming it probes /health only. Egress checkpoint 2026-10-28.

## 2026-10-21 — agent (Claude Sonnet) — P61-E any-shop end-to-end test (branch `fasttrack/p61-e-e2e`, not merged)

- Why: D71.5 / the 2026-10-20 audit's missing chained test. Nothing proved that a shop connected from scratch,
  not the reference shop, runs connect -> ingest -> cards -> approval -> agent run -> measurement.
- What: ONE module, `tests/integration/test_p61e_any_shop_end_to_end.py` (tests only; no migration, no production
  code change). Real Postgres, every step as `juli_app` under RLS except the OAuth callback (see the finding). Fake
  TikTok at `requests.Session.request`: ADR-101 recorded samples (orders, products, returns, inventory, authorized
  shops, product detail) + contract-shaped analytics; `FakeLLMService` with `stream_chunk_chars`. Shop A (seeded,
  own `seller_connect` credential) and the sandbox shop (the one `sandbox_write` credential) exist throughout.
  Steps for shop B: (1) `begin_tiktok_oauth` + `complete_tiktok_oauth_callback` over the real `TikTokAuth` and the
  vendor-verified binding -> shop, credential (merchant = open_id, cipher = the verified one), bootstrap enqueued
  once after the commit; (2) quick scan -> 1 card, then `run_bootstrap_task` (real `score_and_persist_cards`):
  orders / products / analytics for B only, the weak listing's title + cover-image cards live, `proposed` + `shown`;
  (3) `approve_action_card` -> `accepted`; real `_run_agent_workflow_async` / `_resume_agent_workflow_async` with the
  real read and write composition: `get_shop_identity` `verified` with B's name, `assistant.text.delta` rows then
  `assistant.text`, the one PUT signed with the sandbox token, `write_mode='simulated'`, `list_runs` says
  simulated, `executed` event; (4) `reconcile_products` x2 around a seller title edit -> `external_changes`
  `seller_change` + a `seller_change` card event linked `last_write` to the approved card; (5) the impact reader
  skips the simulated execution (`executions_skipped_simulated == 1`, no `impact_readings` for B; verified red when
  the guard is removed); (6) after every step shop A's and the sandbox shop's row counts (all `shop_id` tables) are
  unchanged, neither A's nor B's scope sees the other's rows, and at the end only B's token, the sandbox token and
  the OAuth host appear in the request log (A's tokens never), B's token never wrote.
- Finding (DEBT, xfail-pinned): the OAuth callback opens no tenant scope, so as `juli_app` it is refused by RLS on
  the first `shops` insert and again on `tiktok_credentials`. Production evidently connects with an RLS-bypassing
  role for this route today (the sandbox shop was connected through it); latent for the day the API runs as
  `juli_app`. Not fixed here (touches `core/security/tiktok_oauth.py`, which P61-H edits; needs the owner's word on
  the API role). `conftest._SHARED_STATE_MODULES` gets the module (own database).
- Surprises worth knowing: the recorded sample product is a free gift ("[Quà Tặng]"), never optimised, so B's weak
  listing is the same capture under another id; the quick card survives the full scoring only when the stored
  analytics show a metric fall (the D39.1 trigger), so the weak product's CTR falls in the last 14 days; a regular
  shop's two live cards for one product are title (agent edit) and cover image (a guided lever flow), and the
  journey approves the title; a 112+ character reply is needed for the relay to emit deltas (64 held back, flush at
  48); the model's FinalResponse with a required step undone arms ADR-088's one forced retry, so the resume leg is
  scripted with two narrations; the seller edit must be stamped after Juli's write (the DB clock).
- Corpus: the test-quality figures moved (`python -m eval.quality_detectors reconcile --write` + the four
  lower layers by hand: functions 7115 -> 7117, modules 683 -> 684, layers 507/130/115/115 -> 508/131/116/116;
  zero-assertion 49 and the helper layer 53 unchanged: the journey test asserts in `_step_*` helpers).
  Other branches adding tests will conflict on the same constants; re-derive at merge.
- Verification: see the report; module 1 passed + 1 xfailed, 0 skipped (~25 s with the migrated database).

## 2026-10-21 — agent (Claude Sonnet) — P61-H OAuth refuses cross-shop sandbox collisions (branch `fasttrack/p61-h-oauth-sandbox-guard`, not merged)

- Why: owner (2026-10-21): the sandbox shop's own `seller_connect` row is harmless after P61-G2; what must never
  be written is another shop's non-sandbox credential carrying the sandbox row's merchant id / cipher, or a
  `sandbox_write` row reaching another shop's. Until now caught only at resolve time (which would fail every run).
- Change (no migration, head stays 100): `core.security.refuse_cross_shop_sandbox_collision` + `SandboxCollisionRefused`
  (an `Unauthorized`, generic text -> the callback's existing 401 connect-error path, no new wording). It reuses
  `_enumerate_sandbox_write_credentials` (migration 100's SECURITY DEFINER predicate; plain query on SQLite) -- one
  predicate, not a copy -- inside a SAVEPOINT: a sandbox credential that collides after the write but did not before
  is attributed to it, rolled back (no partial write, no orphan shop), logged
  (`tiktok_credential_write_refused_sandbox_collision`) and refused. Wired into
  `TikTokOAuthService.provision_shop_and_credentials` (create + update + sandbox_write provisioning) and
  `credential_binding.backfill_shop_cipher` (-> needs_reauth + `ShopCipherUnresolvedError`). Token refresh
  (`mark_refreshed`) never changes merchant/cipher, so it is not a vector; tested as not blocked.
- Tests: unit 10 (SQLite), real-Postgres two-shop 7 as `juli_app`/owner (same-shop allowed; cipher and merchant
  carried by another shop refused, no shop/credential rows; sandbox_write onto another shop's cipher refused; RLS
  does not blind the guard; ordinary reconnect + refresh pass). Postgres :55511: p61h+p61g integration 12 passed
  0 skipped; `check.sh --since fasttrack/optimize-product` OK (migrations at 100, isolation 12, gitleaks, ruff,
  pytest 84). Full `tests/unit -m "not live"`: 7914 passed, 245 skipped, 30 failed -- 29 node contract tests (no
  `pnpm install` in the fresh worktree) + 1 suppression ratchet (my `type: ignore`s); both fixed afterwards and the
  re-run files pass (59). ruff/mypy/bandit -ll clean.


## 2026-10-22 — lead — status

- Live: deploy `fasttrack-deploy-20261021T0933Z` (8ed0fd95, migrations to 100). Merged since,
  not deployed: P61-H (f50133cc, no migration).
- In progress: P61-F (`fasttrack/p61-f-agent-prod-write`, migration 101 — resume leg committed
  696b742f, verification running) and P61-E (`fasttrack/p61-e-e2e`). Both resumed after a
  network error on 2026-10-22; next deploy bundles P61-F + P61-H (+ P61-E test).
- Owner, open: post-deploy VPS steps (alembic current = 100, drop TIKTOK_*_MERCHANT_ID,
  install `juli-db-backup.timer`, `pg_stat_statements_reset()`, re-enable Uptime Check);
  egress checkpoint 2026-10-28 (Pro before 2026-11-16 if > 160 MB/day).

## 2026-10-21 — lead — P64 Shopee reviewer on a live TikTok sandbox connection (D73)

- Why: Shopee rejected the resubmission — the reviewer saw the bundled sample shop with browser
  simulation ("mock version or simulated data alone is not sufficient"). Grill D73 / D73.2a.
- S0 probe (production, read-only, 2026-10-21): the sandbox shop `1862f13b…` holds only its
  `sandbox_write` row (merchant `7658…4781588`, the `seller_connect` row was deleted for P61-G);
  token valid; 2 products (water bottle 49 stock, hot-pot 0); 0 orders in 90 d; Analytics
  endpoints answer (`latest_available_date` 2026-10-20) with all-zero intervals. TTSPC dev shop
  `juliai-test` (`SANDBOX_VN7650204809156740884`, seller `7494751643546977923`, expires in 68 d)
  is that shop (same catalog). Created 6 test orders (11 units) and moved them to Awaiting
  shipment; stock 49 → 38. Further status steps did not apply from Partner Center.
  `tts_open_toolkit` 0.1.7 sees no sandbox shop for developer `7494669148810871808`.
- S1 backend (ca435efa, 472ba55f): reviewer pinned to a `sandbox_write` shop is unmasked, gets
  `/v1/reviewer/shop` (connection, synced_at), `/shop/sync` (60 s limit), real `/approve` +
  `/execute` (listing edit, image upload, read-back) through `SandboxWriteClientFactory` only;
  reviewer scope refused by every production write factory/resolver. D73.2a: the `sandbox_write`
  credential reads and is polled for its own shop only (`own_shop_sandbox_read`; not in
  `READ_CAPABILITIES`). Unit 17 new; real Postgres (`juli_app`, RLS) 5 passed 0 skipped.
- S2 demo (20652600, c4e11f72): sandbox-mode banner, "Kết nối TikTok Shop" card with
  "Đồng bộ ngay", real Duyệt/Thực thi dialog with "TikTok xác nhận lúc …", honest no-traffic
  note; sample replay unchanged for anonymous visitors. vitest 1220 passed (+12), tsc clean.
  Local vitest needs `NODE_OPTIONS=--no-experimental-webstorage` on Node 26.
- Rebased on f50133cc (P61-H): one import conflict in `core/security/__init__.py`, kept both.
  After rebase: 40 related unit files 594 passed 10 skipped; ruff/mypy clean.
- Pre-existing, not P64: `tests/integration/test_change_attribution_db.py`
  `test_each_reread_is_attributed_per_field` and `test_seller_change_events_carry_the_card_or_null`
  fail on f50133cc too (fresh DB; `seller_change` vs `juli`).
- Owner next: restock the hot-pot (0 → ~30) in the sandbox Seller Center; set
  `REVIEWER_SHOP_ID=1862f13b-de2c-4fae-a4ad-70298cead913` in the AWS secret `juli/api/production`
  (fetch-secrets.sh regenerates /etc/juli/api.env from it on every juli-api start; a hand edit is lost),
  then `systemctl restart juli-api`; after
  deploy press "Đồng bộ ngay" once, then the lead walks the reviewer steps in a fresh browser
  before the owner resubmits and replies (texts in `fasttrack/shopee-isv-services-information.md`).
