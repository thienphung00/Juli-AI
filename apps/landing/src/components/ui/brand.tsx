import { BIRD_GLYPH } from "../../lib/media";

export interface BirdGlyphProps {
  /** Rendered height in px; width follows the glyph's 512×451 ratio. */
  height: number;
  /** Eager by default: it is in the header. Pass `lazy` below the fold. */
  loading?: "eager" | "lazy";
  className?: string;
}

/**
 * The bird glyph as AVIF/WebP with width/height (no CLS). Decorative (`alt=""`):
 * the link or text next to it carries the name.
 */
export function BirdGlyph({ height, loading = "eager", className }: BirdGlyphProps) {
  const width = Math.round(height * BIRD_GLYPH.ratio);
  const [small, large] = BIRD_GLYPH.variants;
  return (
    <picture>
      <source srcSet={`${small.avif} 64w, ${large.avif} 96w`} sizes={`${width}px`} type="image/avif" />
      <source srcSet={`${small.webp} 64w, ${large.webp} 96w`} sizes={`${width}px`} type="image/webp" />
      {/* eslint-disable-next-line @next/next/no-img-element -- pre-generated AVIF/WebP (scripts/media.py glyph) */}
      <img
        alt=""
        className={["ui-bird", className].filter(Boolean).join(" ")}
        decoding="async"
        height={height}
        loading={loading}
        src={large.webp}
        width={width}
      />
    </picture>
  );
}

export interface BrandMarkProps {
  /** `header` 26 px glyph + 20 px wordmark · `footer` 25 px + 18 px · `compact` (mobile header) 23 px + 18 px. */
  size?: "header" | "footer" | "compact";
}

/** Bird glyph + "Juli AI" set in Be Vietnam Pro 700 (the mockups' logo). */
export function BrandMark({ size = "header" }: BrandMarkProps) {
  const height = size === "header" ? 26 : size === "footer" ? 25 : 23;
  return (
    <span className={`ui-brand ui-brand--${size}`}>
      <BirdGlyph height={height} loading={size === "footer" ? "lazy" : "eager"} />
      <span className="ui-brand__name">Juli AI</span>
    </span>
  );
}
