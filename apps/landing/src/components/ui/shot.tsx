import type { CSSProperties, ReactNode } from "react";

import type { MediaSource } from "../../lib/media";
import { Picture } from "../picture";

/** D44.3: every product screenshot is sample data and says so. */
export const SAMPLE_DATA_CAPTION = "Dữ liệu mẫu";

export interface ShotImage {
  /** Desktop variants (`screens.ts`, e.g. `CAP_PT_LUONG`). */
  variants: readonly MediaSource[];
  /** Describe what the shot shows and end with "(dữ liệu mẫu)". */
  alt: string;
  /** Mobile crop (`screens.ts` `*_MOBILE`), served at ≤ 640 px. */
  mobileVariants?: readonly MediaSource[];
  /**
   * Crop the desktop image to this aspect ratio (width / height) from the top,
   * e.g. `4 / 3` — the mockup's "height: 420px; object-fit: cover; top".
   * Not applied to the mobile crop.
   */
  crop?: number;
}

const DEFAULT_SIZES = "(min-width: 1200px) 640px, (min-width: 768px) 55vw, 100vw";

function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}

function ShotPicture({
  image,
  sizes,
  priority,
  divided,
}: {
  image: ShotImage;
  sizes: string;
  priority: boolean;
  divided: boolean;
}) {
  const style = image.crop ? ({ "--shot-crop": String(image.crop) } as CSSProperties) : undefined;
  return (
    <div
      className={cx(
        "ui-shot__media",
        image.crop ? "ui-shot__media--crop" : null,
        image.mobileVariants && "ui-shot__media--has-mobile",
        divided && "ui-shot__media--divided",
      )}
      style={style}
    >
      <Picture
        alt={image.alt}
        className="ui-shot__img"
        mobileSizes="calc(100vw - 40px)"
        mobileVariants={image.mobileVariants}
        priority={priority}
        sizes={sizes}
        variants={image.variants}
      />
    </div>
  );
}

export interface ShotFrameProps {
  /** One image, or several joined in one frame with hairline dividers. */
  images: ShotImage | readonly ShotImage[];
  /** Browser-chrome bar title, e.g. "Phân tích · Juli". Omit for a plain frame. */
  chrome?: string;
  /** Caption INSIDE the frame, under a hairline (the hero's floating funnel card). */
  caption?: ReactNode;
  /** `float` = smaller radius + stronger shadow (an overlapping second shot). */
  elevation?: "frame" | "hero" | "float";
  sizes?: string;
  priority?: boolean;
  className?: string;
  /** `figure` for a standalone frame (then `caption` is its `<figcaption>`). Default `div`. */
  as?: "div" | "figure";
}

/**
 * The white hairline frame around a screenshot. Use `<Shot>` unless you are
 * composing something custom (the home hero's overlapping pair).
 */
export function ShotFrame({
  images,
  chrome,
  caption,
  elevation = "frame",
  sizes = DEFAULT_SIZES,
  priority = false,
  className,
  as: Tag = "div",
}: ShotFrameProps) {
  const list: readonly ShotImage[] = Array.isArray(images) ? images : [images as ShotImage];
  const CaptionTag = Tag === "figure" ? "figcaption" : "p";
  return (
    <Tag className={cx("ui-shot__frame", `ui-shot__frame--${elevation}`, className)}>
      {chrome ? (
        <div className="ui-shot__chrome">
          <span aria-hidden="true" className="ui-shot__dot" />
          <span aria-hidden="true" className="ui-shot__dot" />
          <span aria-hidden="true" className="ui-shot__dot" />
          <span className="ui-shot__title">{chrome}</span>
        </div>
      ) : null}
      {list.map((image, index) => (
        <ShotPicture
          divided={index > 0}
          image={image}
          key={image.variants[0]?.webp ?? index}
          priority={priority && index === 0}
          sizes={sizes}
        />
      ))}
      {caption ? <CaptionTag className="ui-shot__inner-caption">{caption}</CaptionTag> : null}
    </Tag>
  );
}

export interface ShotProps {
  /** One image, or several. */
  images: ShotImage | readonly ShotImage[];
  /**
   * Several images: `stacked` = one frame each with a 16 px gap (home
   * "Phân tích shop"), `joined` = one frame, hairline between (product hero).
   */
  layout?: "stacked" | "joined";
  /** Browser-chrome bar title on the (first) frame. */
  chrome?: string;
  /** Tinted #f6f4f6 backdrop around the frame. Default true. */
  backdrop?: boolean;
  /** Backdrop padding: `md` 28 px (default) · `lg` 32 px (product hero) · `sm` 14 px. Mobile always 14 px. */
  padding?: "sm" | "md" | "lg";
  /** Default "Dữ liệu mẫu". Pass e.g. "Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai"; `null` hides it. */
  caption?: ReactNode | null;
  /** Frame shadow: `frame` (default) or `hero` (the big home hero shot). */
  elevation?: "frame" | "hero";
  /** `sizes` for the desktop srcset. */
  sizes?: string;
  /** The LCP image (home / product hero only). */
  priority?: boolean;
  className?: string;
}

/**
 * A framed product screenshot (D44.3): hairline frame + shadow, optional
 * browser chrome, on an optional tinted backdrop, captioned "Dữ liệu mẫu",
 * with an optional mobile crop. AVIF/WebP with width/height via `<Picture>`.
 */
export function Shot({
  images,
  layout = "stacked",
  chrome,
  backdrop = true,
  padding = "md",
  caption = SAMPLE_DATA_CAPTION,
  elevation = "frame",
  sizes = DEFAULT_SIZES,
  priority = false,
  className,
}: ShotProps) {
  const list: readonly ShotImage[] = Array.isArray(images) ? images : [images as ShotImage];
  const frames: ReadonlyArray<readonly ShotImage[]> =
    layout === "joined" ? [list] : list.map((image) => [image]);
  return (
    <figure
      className={cx(
        "ui-shot",
        backdrop ? `ui-shot--backdrop ui-shot--pad-${padding}` : "ui-shot--bare",
        className,
      )}
    >
      <div className="ui-shot__frames">
        {frames.map((group, index) => (
          <ShotFrame
            chrome={index === 0 ? chrome : undefined}
            elevation={elevation}
            images={group}
            key={group[0]?.variants[0]?.webp ?? index}
            priority={priority && index === 0}
            sizes={sizes}
          />
        ))}
      </div>
      {caption ? <figcaption className="ui-shot__caption">{caption}</figcaption> : null}
    </figure>
  );
}
