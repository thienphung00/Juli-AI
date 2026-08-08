import birdGlyph from "../assets/bird-glyph.png";
import logoWordmark from "../assets/logo-wordmark.png";

export type JuliLogoVariant = "full" | "glyph";

export interface JuliLogoProps {
  /** Rendered height in pixels. Width scales with the mark's aspect ratio. */
  size?: number;
  variant?: JuliLogoVariant;
  className?: string;
}

function assetSrc(asset: string | { src: string }): string {
  return typeof asset === "string" ? asset : asset.src;
}

/**
 * Canonical Juli AI lockup (ADR-056) — the retouched wordmark (bird-J + "uli AI")
 * or the standalone bird glyph. One bird, one wordmark, everywhere; do not mix
 * with other bird/wordmark variants from the raw asset set.
 */
export function JuliLogo({ size = 28, variant = "full", className }: JuliLogoProps) {
  const source = variant === "full" ? logoWordmark : birdGlyph;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- framework-agnostic package; a fixed-size logo gains nothing from next/image
    <img
      alt="Juli AI"
      className={className}
      src={assetSrc(source)}
      style={{ display: "block", height: `${size}px`, width: "auto" }}
    />
  );
}
