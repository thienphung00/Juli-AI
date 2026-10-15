# `components/ui` — the landing's shared UI (D44, P34-A)

The building blocks for the public-site redesign. Spec: the approved mockups in
`fasttrack/design/p34/*.dc.html`. P34-B…E build pages from these without reading
the component code; if something is missing, add it here (component + test +
this README) rather than restyling it locally.

```tsx
import { Section, SectionIntro, LinkButton, Shot, FeatureRow /* … */ } from "../components/ui";
// from src/app/<route>/page.tsx: "../../components/ui", etc.
```

- **Styles**: `ui.css` (imported once in `app/layout.tsx`), classes `ui-*`.
  Page-specific CSS goes in a CSS module next to the page, using the tokens below.
- **Tokens**: `src/styles/tokens.css`, the ONLY file in the landing allowed to hold
  a raw colour (`design-tokens.test.ts` enforces it). Use `var(--lp-*)` everywhere else.
- **Font**: Be Vietnam Pro 400/500/600/700 (Latin + Vietnamese), self-hosted via
  `next/font/local` (`app/fonts.ts`), applied to `<html>`. Nothing to do per page.
- **Server components** everywhere except `HeaderNav`/`HeaderMenu` (tiny client
  parts of the header). No page needs `"use client"` to use them.
- **SEO rules still apply** (`src/lib/seo/README.md`): one `<h1>` per page, no
  skipped heading level; header and footer carry no headings; every image has
  width/height (they do via `<Picture>`/`<Shot>`).

---

## Tokens (`src/styles/tokens.css`)

| Group | Tokens |
| --- | --- |
| Text colour | `--lp-ink` #121214 (headings, primary button) · `--lp-body` #4a4a52 · `--lp-strong` #2a2a30 (lists, legal) · `--lp-nav` #3f3f46 · `--lp-muted` #6b6b74 (captions, meta) |
| Surfaces | `--lp-bg` white · `--lp-alt` #fbfbfc (alt sections, footer) · `--lp-backdrop` #f6f4f6 (screenshot backdrop, signup aside) · `--lp-segment-bg` #f4f4f6 (VN/EN switch) |
| Lines | `--lp-hairline` #ececf0 · `--lp-hairline-soft` #f0f0f3 · `--lp-border` #dcdce2 (outline button, chips) · `--lp-border-input` #cfcfd6 · `--lp-chrome-dot` #e4e4e8 |
| Pink | `--lp-pink` #f86ba5 **accent only, never text** (2.75:1) · `--lp-pink-text` #b0386a (eyebrows, links) · `--lp-pink-text-hover` · `--lp-pink-tint` #fff7fa · `--lp-pink-line` #f3d3df |
| Status | `--lp-live-fg/-bg` (green, "Đang hoạt động") · `--lp-integrating-fg/-bg` (amber, "Đang tích hợp") |
| Dark band | `--lp-dark` · `--lp-dark-raised` (card on dark) · `--lp-dark-line` · `--lp-dark-line-strong` · `--lp-on-dark` · `--lp-on-dark-body` #c9c9d1 · `--lp-on-dark-list` · `--lp-on-dark-pink` #f9a8c8 |
| Blog categories | `--lp-cat-{metrics,optimize,tools,guide}-{bg,text,accent}` (Blog.dc.html covers) |
| Type | `--lp-font-sans` · `--lp-text-display` (h1 home 34→56) · `--lp-text-h1-page` (34→50) · `--lp-text-h2` (26→42) · `--lp-text-h2-feature` (26→36) · `--lp-text-h2-article` (24→34) · `--lp-text-h3` 19 · `--lp-text-h3-small` 18 · `--lp-text-lead` 16→19 · `--lp-text-body` 17 · `--lp-leading-body` 1.65 · `--lp-text-body-small` 15 · `--lp-text-label` 14 · `--lp-text-caption` 13 · `--lp-text-micro` 12 · `--lp-weight-{regular,medium,semibold,bold}` · `--lp-tracking-display` −1.8 % · `--lp-tracking-heading` −1.2 % (never tighter than −2 %) |
| Spacing | `--lp-space-1…26` (4 px base: 1=4, 2=8, 3=12, 4=16, 5=20, 6=24, 7=28, 8=32, 10=40, 12=48, 14=56, 16=64, 18=72, 22=88, 26=104) · `--lp-section-y` 56→104 · `--lp-section-y-compact` 40→72 |
| Layout | `--lp-container` 1200 px · `--lp-reading` 720 px · `--lp-gutter` 20→24 px · `--lp-touch` 44 px |
| Radii | `--lp-radius-sm` 10 · `-md` 12 · `-frame` 14 · `-lg` 16 · `-xl` 22 · `-2xl` 24 · `-pill` |
| Shadows | `--lp-shadow-frame` (screenshot) · `--lp-shadow-hero` (home hero shot) · `--lp-shadow-float` (overlapping card) · `--lp-shadow-menu` |

All text pairs measured ≥ 4.5:1 (list in the token file header). Breakpoints used
by `ui.css`: **640** (phone), **900** (header), **960** (two columns).

---

## Components

### `SiteHeader` — every page
```tsx
<SiteHeader />                    // logo · Sản phẩm · Kết nối TikTok Shop · Blog · Giới thiệu · Đăng nhập · [Dùng thử miễn phí]
<SiteHeader variant="signup" />   // /dang-ky: logo · "Đã có tài khoản? Đăng nhập"
```
Sticky, white, hairline bottom. Active item (`aria-current="page"`) from the router
(`/san-pham/*` lights "Sản phẩm"). Below 900 px: logo · "Dùng thử" · menu button
(`<details>`, no JS needed; it closes itself after navigation). Test ids:
`header-login-link` (→ `LOGIN_URL`, the Demo), `header-trial-cta` (→ `SIGNUP_URL`),
`menu-login-link`. Both are tracked by `TikTokTracking` (StartDemo, by test id).

### `SiteFooter` — every page
`<SiteFooter />`. Brand + "Trợ lý AI vận hành cho nhà bán TikTok Shop." + company ·
MST · address · email (`data-testid="footer-company"`), columns Sản phẩm / Công ty
(+ Xem demo) / Pháp lý (+ Cài đặt cookie). No social links (D43.8), no headings.

### `LinkButton`, `Button`, `TextLink`
```tsx
<LinkButton href={SIGNUP_URL} data-testid="hero-trial-cta">Dùng thử miễn phí 3 tháng</LinkButton>
<LinkButton href="#video" variant="secondary" icon="play">Xem video 1 phút</LinkButton>
<LinkButton href={SIGNUP_URL} variant="on-dark">Đăng ký dùng thử</LinkButton>          // dark band
<LinkButton href={DEMO_URL} variant="on-dark-secondary">Xem demo với dữ liệu mẫu</LinkButton>
<LinkButton href="/dang-ky" size="md">…</LinkButton>   // 15 px / 44 px (header size)
<LinkButton href="/dang-ky" blockOnMobile>…</LinkButton> // full width ≤ 640 px (HomeMobile)
<Button type="submit">Đăng ký dùng thử</Button>          // a real <button>, same looks
<TextLink href={PRODUCT_PAGES.analysis.href}>Xem Phân tích shop</TextLink>   // pink, "→" appended
<TextLink href="…" tone="on-dark" arrow={false}>…</TextLink>
```
| prop | values | default |
| --- | --- | --- |
| `variant` | `primary` (ink) · `secondary` (outline) · `on-dark` (white) · `on-dark-secondary` (outline on dark) | `primary` |
| `size` | `md` (header) · `lg` (52 px, hero/bands) | `lg` |
| `icon` | any `IconName` (leading, decorative) | — |
| `blockOnMobile` | full width ≤ 640 px | false |

Internal paths use `next/link`; the Demo / `mailto:` a plain `<a>`. **Keep a
`data-testid` on every CTA** — the TikTok listener reports it as `content_name`.
`buttonClassName({ variant, size })` gives the classes for anything else (e.g. a
form's submit built elsewhere).

### `Section`, `Container`
```tsx
<Section labelledBy="loop">…</Section>                       // white, 56→104 px padding, 1200 px container
<Section tone="alt" spacing="compact" labelledBy="san">…</Section>   // #fbfbfc + hairlines (marketplace strip, data safety)
<Section tone="dark" labelledBy="price">…</Section>          // the ONE dark band per page
<Section width="reading">…</Section>                         // 720 px column
<Section width="none" spacing="none">…</Section>             // bring your own layout
<Container width="reading">…</Container>                     // just the centred column + gutters
```
`labelledBy` = the heading's id → the section becomes a named landmark (as in the
mockups' `aria-labelledby`). `innerClassName` styles the inner container (e.g. a
grid from your CSS module).

### `Eyebrow`, `Heading`, `SectionIntro`
```tsx
<Eyebrow>Cách Juli làm việc</Eyebrow>                              // pink 14/600
<Eyebrow variant="muted">Pháp lý</Eyebrow>
<Eyebrow variant="badge">Kết nối chính thức qua TikTok Shop Open API</Eyebrow>   // hero pill with dot

<Heading level={1}>…</Heading>                      // display 56→34 (home)
<Heading level={1} size="page">…</Heading>         // inner pages 50→34 (product, legal 44 ≈ page)
<Heading level={2} size="feature" id="cap1">…</Heading>   // 36→26
<Heading level={2} size="article">…</Heading>      // capability page H2 34→24
<Heading level={3}>…</Heading>                      // card 19
<Heading level={2} onDark>…</Heading>

<SectionIntro eyebrow="Cách Juli làm việc" title="Năm bước, và bạn luôn là người quyết định." titleId="loop"
  lead="…" />                                        // eyebrow + h2 (max 720 px) + lead
<SectionIntro title="Dùng thử miễn phí 3 tháng." titleId="price" onDark lead="…" />
<SectionIntro level={1} size="page" eyebrow="Pháp lý" eyebrowVariant="muted" title="Chính sách bảo mật" />
```
`Heading` sizes: `display` · `page` · `section` (42→26, default for h2) · `feature` ·
`article` · `card` (default for h3). The level is the outline, the size is the look.
Body text classes: `ui-lead` (19→16), `ui-body` (17/1.65).

### `Card`, `CheckList`
```tsx
<Card><Icon name="shield-check" size={28} strokeWidth={1.8} /><Heading level={3} size="card">Kết nối chính thức</Heading><p>…</p></Card>
<Card tone="highlight" as="li">…</Card>     // default · alt · highlight (pink) · dark (pricing card)
<CheckList items={["So 30 ngày gần nhất với 30 ngày trước", "…"]} />   // pink checks
```

### `Shot` — framed screenshot
```tsx
import { CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, CAP_PT_XEP_HANG } from "../components/product/screens";

<Shot images={{ variants: CAP_PT_LUONG, mobileVariants: CAP_PT_LUONG_MOBILE,
                alt: "GMV chia theo 5 luồng truy cập (dữ liệu mẫu)" }} />
<Shot chrome="Phân tích · Juli" padding="lg" layout="joined" priority
      caption="Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai"
      images={[{ variants: CAP_PT_LUONG, alt: "…" }, { variants: CAP_PT_PHEU, alt: "…" }]} />
<Shot images={{ variants: CAP_DX_THE, alt: "…", crop: 4 / 3 }} />   // crop from the top to 4:3
<Shot backdrop={false} caption={null} images={…} />
```
| prop | meaning | default |
| --- | --- | --- |
| `images` | one `ShotImage` or an array: `{ variants, alt, mobileVariants?, crop? }` | — |
| `layout` | several images: `stacked` (one frame each, 16 px gap — home cap1) · `joined` (one frame, hairline between — product hero) | `stacked` |
| `chrome` | browser bar title ("Quyết định · Juli"); omit for a plain frame | — |
| `backdrop` | #f6f4f6 tinted backdrop | `true` |
| `padding` | backdrop padding `sm` 14 · `md` 28 · `lg` 32 (mobile always 14) | `md` |
| `caption` | `figcaption`; `null` hides | `"Dữ liệu mẫu"` |
| `elevation` | `frame` · `hero` (bigger shadow, radius 18) | `frame` |
| `sizes` | desktop `sizes` | `(min-width:1200px) 640px, (min-width:768px) 55vw, 100vw` |
| `priority` | LCP image: eager + high priority (hero only) | false |

Alt text ends with "(dữ liệu mẫu)". `mobileVariants` is served at ≤ 640 px through
`<picture><source media>` with its own width/height (no CLS); `crop` is not
applied to it. **Mobile crops available** (`screens.ts`, `*_MOBILE`): every
`cap-dl-*`, `cap-pt-*`, `cap-kn-dang-nhap/ket-noi/quet-nhanh`,
`cap-dx-luot-chay/quy-tac/xac-nhan`. Shots with large text need none:
`cap-dx-hang-cho/hoan-tac/tu-choi/seller-center/the`, `cap-kn-ghi`.
Regenerate / add crops: `MOBILE_CROPS` in `scripts/media.py`, then
`python apps/landing/scripts/media.py mobile-crops` (new names, never overwrite).

`ShotFrame` is the bare frame for custom compositions — the home hero's
overlapping pair:
```tsx
<div className={styles.heroMedia}>                 {/* position: relative */}
  <ShotFrame chrome="Quyết định · Juli" elevation="hero" priority
             images={{ variants: CAP_DX_THE, alt: "…", crop: 5 / 4 }} />
  <ShotFrame as="figure" elevation="float" caption="Dữ liệu mẫu" className={styles.heroFloat}
             images={{ variants: CAP_PT_PHEU, alt: "…" }} />   {/* position: absolute; left:-36px; bottom:-40px; width:62% */}
</div>
```

### `FeatureRow` — zig-zag text + shot
```tsx
<FeatureRow titleId="cap1" eyebrow="Phân tích shop"
  title="Biết GMV tăng hay giảm vì luồng nào, chỉ số nào."
  bullets={["So 30 ngày gần nhất với 30 ngày trước", "…"]}
  link={{ href: PRODUCT_PAGES.analysis.href, label: "Xem Phân tích shop" }}
  media={<Shot images={…} caption="Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai" />}>
  Juli tách GMV thành 5 luồng truy cập và đọc phễu …
</FeatureRow>
<FeatureRow reverse … />           // media on the left at ≥ 960 px (cap2)
<FeatureRow as="div" level={3} … /> // inside your own <Section>
```
Text 5fr / media 7fr, gap 56. Mobile: text first, then media. A string child
becomes one `<p class="ui-body">`; pass elements for more paragraphs. Default
`as="section"` with `aria-labelledby={titleId}` — wrap rows in a `Container`
(or `<Section width="wide" spacing="compact">`) for the gutters and rhythm.

### `StatusPill`
```tsx
<StatusPill status="live" />          // "Đang hoạt động" (green)
<StatusPill status="integrating" />   // "Đang tích hợp" (amber)
```

### `StepList` — the 5-step loop
```tsx
<StepList />                      // LOOP_STEPS (Main.dc.html copy), "03 · bạn" on Duyệt
<StepList steps={[{ title, body, you? }]} level={4} />
```
5-up cards ≥ 760 px; ruled rows on phones (HomeMobile). Titles are `<h3>` by default.

### `FunnelDiagram`
```tsx
<FunnelDiagram />                         // neutral formula
<FunnelDiagram highlight="ctor" />        // pink "Đang nghẽn" box: impressions | ctr | ctor | aov
<FunnelDiagram highlight="aov" highlightLabel="Juli gợi ý" caption={null} />
```
Built in markup; `role="img"` + a full-sentence `aria-label`.

### `FaqList`
```tsx
<FaqList items={HOME_FAQ} />                // and keep faqPageSchema(HOME_FAQ) in the page's <JsonLd>
<FaqList items={FAQ} schema openFirst />    // or let it emit the FAQPage JSON-LD itself
```
`items: FaqItem[]` (`{ question, answer }`, same type as `faqPageSchema`). Use
**either** `schema` **or** the page-level `faqPageSchema`, never both (check:seo
flags duplicate/mismatched FAQPage).

### `TocNav` + `.ui-toc-layout`
```tsx
<div className="ui-toc-layout">                     {/* TOC left (Product.dc.html) */}
  <TocNav items={[{ id: "nam-luong", label: "Năm luồng truy cập" }, …]} activeId="nam-luong" />
  <article>…<h2 id="nam-luong">…</h2>…</article>
</div>
<div className="ui-toc-layout ui-toc-layout--end">  {/* TOC right with hairline (Legal.dc.html) */}
  <TocNav variant="rule" items={…} />
  <article className="ui-container--reading">…</article>
</div>
```
≥ 960 px: sticky list "Trên trang này". Below: a `<details>` disclosure at the top
of the content. `activeId` is static (no scroll-spy).

### `Breadcrumb`
```tsx
<Breadcrumb items={[{ href: "/san-pham", label: "Sản phẩm" }]} current="Phân tích shop" />
// + breadcrumbSchema(path) in the page's <JsonLd>
```

### `Icon`
```tsx
<Icon name="shield-check" size={28} strokeWidth={1.8} />   // decorative (aria-hidden)
<Icon name="alert" label="Cảnh báo" />                      // meaningful: role="img" + name
```
Names: `shield-check`, `check-square`, `undo`, `mail`, `play`, `menu`, `close`,
`chevron-down`, `chevron-right`, `arrow-right`, `alert`, `check`. Stroke =
`currentColor` (set colour on the parent).

### `BirdGlyph`, `BrandMark`
```tsx
<BirdGlyph height={39} loading="eager" className={styles.heroBird} />  // hero flourish (44×39)
<BrandMark />                                                           // glyph + "Juli AI" (header uses it)
```
The dashed flight path in the hero is page markup (inline SVG, stroke
`var(--lp-pink)`, `stroke-dasharray="2 9"`), not a component.

---

## Page recipes (mockup → components)

**Main.dc.html (home, P34-B)** — `SiteHeader` · hero: `Section` with a 2-column grid
(your module): `Eyebrow variant="badge"`, `Heading level={1}`, `p.ui-lead`,
`LinkButton` ×2 (`hero-trial-cta` primary → `SIGNUP_URL`, `secondary icon="play"`
video), note `p` in `--lp-muted` 14 px; media = bird + flight path + `ShotFrame`
pair (recipe above, `priority`). · marketplace strip: `Section tone="alt"
spacing="compact"`, `h2` 14 px muted (`Eyebrow`-sized, but a real `<h2>` for the
outline), names + `StatusPill`. · loop: `Section` + `SectionIntro` + `StepList`. ·
cap1–3: three `FeatureRow` (cap2 `reverse`) inside `Container`, each a `Shot`. ·
data safety: `Section tone="alt"` + `SectionIntro` + 4 `Card`s with `Icon`
(`shield-check`, `check-square`, `undo`, `mail`) in an auto-fit grid
(min 240 px). · audiences: two-column grid, `Heading level={3} size="card"` + `p`.
· transparency: `Card` (radius 24 → your class) with text + `TextLink`, and a `dl`
on `--lp-alt` with `COMPANY`. · pricing: `Section tone="dark"` + `SectionIntro
onDark` + `LinkButton variant="on-dark"` / `"on-dark-secondary"` + `Card
tone="dark"` (500.000đ, `--lp-on-dark-pink` note). · FAQ: two-column grid,
`Heading level={2} size="feature"` + "Liên hệ Juli" link, `FaqList`. · `SiteFooter`.

**HomeMobile.dc.html** — same DOM; the components already switch: header compact +
menu, `blockOnMobile` on the hero CTAs, `Shot` with `mobileVariants`, `StepList`
rows, `Section` rhythm. Marketplace strip on phones = a bordered card (your module).

**Product.dc.html (P34-C)** — `SiteHeader` · `Container` + `Breadcrumb` · split hero:
`Eyebrow` + `Heading level={1} size="page"` | `p.ui-lead` + `LinkButton` ×2 · hero
`Shot chrome="Phân tích · Juli" layout="joined" padding="lg" priority` · body
`.ui-toc-layout` with `TocNav` + `<article>`: each H2 `Heading level={2}
size="article"` + `p.ui-body` (max 720) + one `Shot` (with `*_MOBILE`) or
`FunnelDiagram highlight=…`; streams = 5 `Card`s · FAQ `Heading level={2}
size="article"` + `FaqList` · "next" links = `Card as="article"` links in a grid ·
final CTA `Section tone="dark" spacing="compact"`: `Heading level={2} onDark` +
`LinkButton variant="on-dark"`.

**Blog.dc.html (P34-D)** — `SiteHeader` · `Heading level={1} size="page"` + lead ·
category chips (your module, `--lp-border`, active = ink) · featured card + 3-up
grid (`Card`-like links; covers from `--lp-cat-*` tokens) · posts: `Container
width="reading"`, `Heading level={2} size="article"`, optional `TocNav`.

**Legal.dc.html (P34-E)** — `SiteHeader` · `Container`: `SectionIntro level={1}
size="page" eyebrow="Pháp lý" eyebrowVariant="muted"` + updated line + VN/EN switch (`--lp-segment-bg`) ·
`.ui-toc-layout ui-toc-layout--end`: `<article>` (720 px; summary = `Card
tone="alt"`; sections `Heading level={2}` 24 px → your class) + `TocNav
variant="rule"` · `SiteFooter`.

**Signup.dc.html (P34-E)** — `SiteHeader variant="signup"` · two columns: `Eyebrow`
+ `Heading level={1} size="page"` + lead + the form (inputs `--lp-border-input`,
radius `--lp-radius-md`, 48 px; submit = `Button blockOnMobile` or
`buttonClassName()`) | aside on `--lp-backdrop`, radius 24: numbered steps (your
markup, ink circles) + `ShotFrame as="figure" caption="Dữ liệu mẫu"` (no backdrop).

**Auth.dc.html / AuthMobile.dc.html** are the Demo's (P34-F, `apps/demo`); these
components are landing-only.
