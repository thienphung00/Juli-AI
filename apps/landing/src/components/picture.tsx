import type { MediaSource } from "../lib/media";

export interface PictureProps {
  /** One entry per width (from `scripts/media.py optimize`), any order. */
  variants: readonly MediaSource[];
  alt: string;
  /** `sizes` for the srcset, e.g. "(min-width: 960px) 880px, 100vw". */
  sizes?: string;
  /** The LCP image: eager + high fetch priority. Everything else lazy-loads. */
  priority?: boolean;
  className?: string;
  /**
   * Art direction (D44.3): a separate, usually taller and narrower crop served
   * below `mobileMedia`. Its own width/height go on the `<source>` so the
   * browser reserves the right box on phones too (no CLS).
   */
  mobileVariants?: readonly MediaSource[];
  /** Media query for `mobileVariants`. Default `(max-width: 640px)`. */
  mobileMedia?: string;
  /** `sizes` for the mobile crop. Default `100vw`. */
  mobileSizes?: string;
}

function srcSet(variants: readonly MediaSource[], format: "avif" | "webp"): string | undefined {
  const entries = variants.filter((v) => v[format]).map((v) => `${v[format]} ${v.width}w`);
  return entries.length > 0 ? entries.join(", ") : undefined;
}

/**
 * AVIF → WebP `<picture>` with explicit width/height (D43.4). Server component.
 * Use for screenshots and posters; the logo has its own `SiteLogo`.
 */
export function Picture({
  variants,
  alt,
  sizes = "100vw",
  priority = false,
  className,
  mobileVariants,
  mobileMedia = "(max-width: 640px)",
  mobileSizes = "100vw",
}: PictureProps) {
  const sorted = [...variants].sort((a, b) => a.width - b.width);
  const largest = sorted[sorted.length - 1];
  if (!largest) throw new Error("Picture needs at least one variant");
  const avif = srcSet(sorted, "avif");
  const mobile = mobileVariants ? [...mobileVariants].sort((a, b) => a.width - b.width) : [];
  const mobileLargest = mobile[mobile.length - 1];
  const mobileAvif = mobileLargest ? srcSet(mobile, "avif") : undefined;
  return (
    <picture>
      {mobileLargest && mobileAvif ? (
        <source
          height={mobileLargest.height}
          media={mobileMedia}
          sizes={mobileSizes}
          srcSet={mobileAvif}
          type="image/avif"
          width={mobileLargest.width}
        />
      ) : null}
      {mobileLargest ? (
        <source
          height={mobileLargest.height}
          media={mobileMedia}
          sizes={mobileSizes}
          srcSet={srcSet(mobile, "webp")}
          type="image/webp"
          width={mobileLargest.width}
        />
      ) : null}
      {avif ? <source sizes={sizes} srcSet={avif} type="image/avif" /> : null}
      <source sizes={sizes} srcSet={srcSet(sorted, "webp")} type="image/webp" />
      <img
        alt={alt}
        className={className}
        decoding="async"
        fetchPriority={priority ? "high" : "auto"}
        height={largest.height}
        loading={priority ? "eager" : "lazy"}
        src={largest.webp}
        width={largest.width}
      />
    </picture>
  );
}
