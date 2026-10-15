import { LOGO_WORDMARK } from "../lib/media";

/**
 * The Juli AI wordmark for the landing header/footer: a 6 KB WebP with
 * intrinsic width/height (the shared `JuliLogo` ships the 50 KB source PNG).
 */
export function SiteLogo({ height }: { height: number }) {
  const width = Math.round((LOGO_WORDMARK.width * height) / LOGO_WORDMARK.height);
  return (
    // eslint-disable-next-line @next/next/no-img-element -- pre-generated WebP (scripts/media.py); a fixed-size logo gains nothing from next/image
    <img
      alt="Juli AI"
      className="lp-logo"
      decoding="async"
      height={height}
      src={LOGO_WORDMARK.src}
      width={width}
    />
  );
}
