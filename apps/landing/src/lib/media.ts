/**
 * Pre-generated media in `public/media/` (scripts/media.py). Every entry
 * carries its intrinsic width/height so the page reserves space (no CLS) and
 * Lighthouse's "unsized images" audit passes. Files there are cached
 * `immutable` — a changed image gets a new `-vN` name, never an overwrite.
 */

export interface MediaSource {
  avif?: string;
  webp: string;
  width: number;
  height: number;
}

/** Header/footer wordmark: 183×60 WebP rendered at 30px / 26px height. */
export const LOGO_WORDMARK = {
  src: "/media/juli-logo-wordmark-v1.webp",
  width: 183,
  height: 60,
} as const;

/**
 * Sales demo video (hero): poster + click-to-load (D43.6, `HeroVideo`) and
 * `videoObjectSchema(HERO_VIDEO_SCHEMA)` on `/`. The poster is the video's
 * "GMV = Hiển thị × CTR × CTOR × AOV" frame (t = 19 s), chosen because it
 * carries no outcome figure (D43.3); the old `juli-demo-poster-v1-*` brand card
 * showed "+1–3% GMV mỗi tháng" and is no longer referenced.
 */
export const HERO_VIDEO = {
  src: "/videos/juli-demo.mp4",
  durationIso: "PT1M4S",
  /** First published on app-juli.com (git: added 2026-10-09). */
  uploadDate: "2026-10-09",
  poster: {
    small: {
      avif: "/media/home-demo-poster-v1-640.avif",
      webp: "/media/home-demo-poster-v1-640.webp",
      width: 640,
      height: 360,
    },
    large: {
      avif: "/media/home-demo-poster-v1-1280.avif",
      webp: "/media/home-demo-poster-v1-1280.webp",
      width: 1280,
      height: 720,
    },
  },
} as const;

/** Ready-made input for `videoObjectSchema()`. */
export const HERO_VIDEO_SCHEMA = {
  name: "Juli AI — trợ lý tăng trưởng cho người bán TikTok Shop",
  description:
    "Video giới thiệu Juli: cách Juli theo dõi shop, phân tích GMV theo từng luồng truy cập và đề xuất hành động.",
  thumbnailUrl: [HERO_VIDEO.poster.large.webp],
  uploadDate: HERO_VIDEO.uploadDate,
  contentUrl: HERO_VIDEO.src,
  duration: HERO_VIDEO.durationIso,
};

/**
 * The bird glyph (D44.3): logo mark in the header/footer and the single hero
 * flourish. 512×451 source → 64/96 px AVIF + WebP (`media.py glyph`).
 */
export const BIRD_GLYPH = {
  ratio: 512 / 451,
  variants: [
    { avif: "/media/bird-glyph-v1-64.avif", webp: "/media/bird-glyph-v1-64.webp", width: 64, height: 56 },
    { avif: "/media/bird-glyph-v1-96.avif", webp: "/media/bird-glyph-v1-96.webp", width: 96, height: 85 },
  ],
} as const;
