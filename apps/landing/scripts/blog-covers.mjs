#!/usr/bin/env node
/**
 * Blog cover generator (D44.3, P34-D). Renders a flat, text-free HTML cover per
 * post with Playwright and writes, under `public/media/`:
 *
 *   blog-<name>-600.avif/.webp, blog-<name>-1200.avif/.webp   (16:9, 1200×675 master)
 *   blog-<name>-og.png                                        (1200×630 Open Graph)
 *
 * The template follows Blog.dc.html: one category tint, one simple object drawn
 * in ink with a 3 px outline (at card size) and exactly ONE accent colour, no
 * text. Colours are read from `src/styles/tokens.css` (`--lp-cat-*`, `--lp-ink`),
 * so a token change and a re-render stay in sync.
 *
 * Usage (from the repo root; Node 20, Playwright's Chromium installed):
 *
 *   PYTHON=juli/.venv/bin/python node apps/landing/scripts/blog-covers.mjs
 *   node apps/landing/scripts/blog-covers.mjs --samples <dir>   # one PNG per motif, nothing in public/
 *
 * New cover: add an entry to COVERS (name ends in -v1), run the command, then
 * point the post's `cover` at it in `src/content/blog/posts.ts` (`blogCover()`).
 * Files in `public/media/` are cached `immutable`: an existing file is never
 * overwritten (the script skips it); change a cover by bumping `-vN`.
 * AVIF/WebP encoding reuses `media.py optimize` (Pillow with AVIF, the repo venv).
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MEDIA = join(LANDING, "public", "media");
const TOKENS = join(LANDING, "src", "styles", "tokens.css");
const PYTHON = process.env.PYTHON ?? "python3";

/**
 * One entry per published cover. `motif` defaults to the category's; `accent`
 * picks which element carries the accent colour (vary it so two posts in one
 * category do not share an image).
 */
export const COVERS = [
  { name: "chi-so-ctr-ctor-aov-v1", category: "metrics", motif: "bars", accent: 2 },
  { name: "the-san-pham-v1", category: "optimize", motif: "card" },
  { name: "cong-cu-2026-v1", category: "tools", motif: "tiles", accent: 4 },
  { name: "gmv-la-gi-v1", category: "metrics", motif: "bars", accent: 0 },
  { name: "khong-ra-don-v1", category: "guide", motif: "checklist", accent: 0 },
  { name: "doanh-thu-giam-v1", category: "metrics", motif: "bars", accent: 3 },
  { name: "da-kenh-2026-v1", category: "tools", motif: "tiles", accent: 0 },
  { name: "phan-tich-2026-v1", category: "tools", motif: "tiles", accent: 2 },
  { name: "ai-anh-video-v1", category: "tools", motif: "tiles", accent: 5 },
  { name: "luot-hien-thi-v1", category: "guide", motif: "checklist", accent: 1 },
  { name: "thue-ban-hang-v1", category: "guide", motif: "checklist", accent: 2 },
  { name: "video-view-v1", category: "guide", motif: "checklist", accent: 1 },
  { name: "live-it-don-v1", category: "guide", motif: "checklist", accent: 2 },
  { name: "hoan-hang-v1", category: "metrics", motif: "bars", accent: 1 },
  { name: "phi-san-2026-v1", category: "guide", motif: "tiles", accent: 1 },
  { name: "khach-xem-khong-mua-v1", category: "metrics", motif: "checklist", accent: 1 },
  { name: "gia-tri-don-v1", category: "metrics", motif: "bars", accent: 1 },
];

const MOTIF_BY_CATEGORY = { metrics: "bars", optimize: "card", tools: "tiles", guide: "checklist" };

/** Design units are CSS px of a 400-wide card (≈ the 3-up grid), rendered at 3× → 1200 px. */
const SCALE = 3;
const SIZES = { cover: { width: 400, height: 225 }, og: { width: 400, height: 210 } };

function readTokens() {
  const css = readFileSync(TOKENS, "utf8");
  const value = (name) => {
    const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(css);
    if (!match) throw new Error(`token --${name} not found in ${TOKENS}`);
    return match[1].trim();
  };
  const category = (key) => ({
    bg: value(`lp-cat-${key}-bg`),
    accent: value(`lp-cat-${key}-accent`),
  });
  return {
    ink: value("lp-ink"),
    paper: value("lp-bg"),
    categories: {
      metrics: category("metrics"),
      optimize: category("optimize"),
      tools: category("tools"),
      guide: category("guide"),
    },
  };
}

/** The object, in the mockup's proportions (Blog.dc.html). `a` = accent index. */
const MOTIFS = {
  // Featured "Chỉ số" cover: four bars from the bottom edge, one accented.
  bars: (a = 2) => {
    const heights = [64, 50, 28, 41];
    return `<div class="bars">${heights
      .map((h, i) => `<div class="bar${i === a ? " accent outlined" : " ink"}" style="height:${h}%"></div>`)
      .join("")}</div>`;
  },
  // "Tối ưu sản phẩm": a product card — image block, title line, accent line.
  card: () =>
    `<div class="card outlined"><div class="card-img ink"></div><div class="line ink" style="width:80%"></div><div class="line accent" style="width:50%"></div></div>`,
  // "Công cụ": 3×2 tiles, outlined / filled, one accented.
  tiles: (a = 4) => {
    const filled = [false, true, false, true, false, true];
    return `<div class="tiles">${filled
      .map((f, i) =>
        i === a ? `<div class="tile accent outlined"></div>` : `<div class="tile ${f ? "ink" : "paper outlined"}"></div>`,
      )
      .join("")}</div>`;
  },
  // "Hướng dẫn": a checklist sheet, the first box ticked (the accent).
  checklist: (a = 0) =>
    `<div class="sheet outlined">${[0, 1, 2]
      .map(
        (i) =>
          `<div class="row"><div class="box ${i === a ? "accent" : "paper"} outlined"></div><div class="line ink" style="width:${[70, 55, 62][i]}%"></div></div>`,
      )
      .join("")}</div>`,
};

function coverHtml({ category, motif, accent }, tokens) {
  const tint = tokens.categories[category];
  if (!tint) throw new Error(`unknown category ${category}`);
  const draw = MOTIFS[motif ?? MOTIF_BY_CATEGORY[category]];
  if (!draw) throw new Error(`unknown motif ${motif}`);
  return `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%}
body{background:${tint.bg};display:flex;align-items:center;justify-content:center;overflow:hidden}
.ink{background:${tokens.ink}}
.paper{background:${tokens.paper}}
.accent{background:${tint.accent}}
.outlined{border:3px solid ${tokens.ink}}
.bars{position:absolute;inset:0;display:flex;align-items:flex-end;justify-content:center;gap:12px;padding:0 48px}
.bar{width:46px;border-radius:7px 7px 0 0;border-bottom:0}
.card{width:46%;height:62%;background:${tokens.paper};border-radius:12px;display:flex;flex-direction:column;gap:8px;padding:12px}
.card-img{height:48%;border-radius:6px}
.line{height:10px;border-radius:4px;flex:none}
.tiles{width:52%;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.tile{aspect-ratio:1;border-radius:10px}
.tile.ink{border:3px solid ${tokens.ink}}
.sheet{width:42%;height:66%;background:${tokens.paper};border-radius:12px;display:flex;flex-direction:column;justify-content:center;gap:16px;padding:16px 18px}
.row{display:flex;align-items:center;gap:12px}
.box{width:22px;height:22px;border-radius:6px;flex:none}
.row .line{flex:none}
</style></head><body>${draw(accent)}</body></html>`;
}

async function render(browser, html, size, file) {
  const page = await browser.newPage({ viewport: size, deviceScaleFactor: SCALE });
  await page.setContent(html);
  await page.screenshot({ path: file, type: "png" });
  await page.close();
}

function outputs(name) {
  const stem = join(MEDIA, `blog-${name}`);
  return {
    stem,
    files: [600, 1200].flatMap((w) => [`${stem}-${w}.avif`, `${stem}-${w}.webp`]).concat(`${stem}-og.png`),
  };
}

async function main() {
  const args = process.argv.slice(2);
  const samplesAt = args.indexOf("--samples");
  const tokens = readTokens();
  const browser = await chromium.launch();
  try {
    if (samplesAt !== -1) {
      const dir = resolve(args[samplesAt + 1] ?? ".");
      mkdirSync(dir, { recursive: true });
      for (const category of Object.keys(MOTIF_BY_CATEGORY)) {
        const file = join(dir, `blog-cover-sample-${category}.png`);
        await render(browser, coverHtml({ category }, tokens), SIZES.cover, file);
        console.log(`sample ${file}`);
      }
      return;
    }
    const tmp = mkdtempSync(join(tmpdir(), "blog-covers-"));
    for (const cover of COVERS) {
      const { stem, files } = outputs(cover.name);
      const existing = files.filter((f) => existsSync(f));
      if (existing.length === files.length) {
        console.log(`skip ${cover.name} (exists; bump -vN to change it)`);
        continue;
      }
      if (existing.length > 0) {
        throw new Error(`${cover.name}: partial output exists (${existing.join(", ")}); remove it or bump -vN`);
      }
      const html = coverHtml(cover, tokens);
      const master = join(tmp, `${cover.name}.png`);
      await render(browser, html, SIZES.cover, master);
      execFileSync(PYTHON, [join(LANDING, "scripts", "media.py"), "optimize", master, "--out", stem, "--widths", "600,1200"], {
        stdio: "inherit",
      });
      await render(browser, html, SIZES.og, `${stem}-og.png`);
      console.log(`wrote ${cover.name}: ${files.map((f) => f.slice(LANDING.length + 1)).join(", ")}`);
    }
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
