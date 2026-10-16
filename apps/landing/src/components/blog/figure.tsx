import type { BlogFigure } from "../../content/blog/types";
import { Picture } from "../picture";
import { Shot } from "../ui";

/** The article column is 720 px from 960 px up; a phone gets its own layout / crop. */
const DIAGRAM_SIZES = "(min-width: 960px) 720px, (min-width: 641px) calc(100vw - 48px), 100vw";
/** A screenshot sits on the 28 px backdrop (14 px on phones). */
const SHOT_SIZES = "(min-width: 960px) 664px, (min-width: 641px) calc(100vw - 104px), 100vw";

/**
 * An inline blog figure (D48 additions 7, P39-C): `<figure>` + visible
 * `<figcaption>`, AVIF/WebP with width/height, a phone variant below 640 px,
 * always lazy (never `priority`: the H1 stays the LCP). Screenshots reuse the
 * product pages' framed `Shot` ("Dữ liệu mẫu" caption); diagrams sit in a
 * hairline frame like the capability-page diagrams.
 */
export function BlogFigureView({ figure }: { figure: BlogFigure }) {
  if (figure.kind === "screenshot") {
    return (
      <Shot
        caption={figure.caption}
        className="lp-blog__figure lp-blog__figure--shot"
        images={{ alt: figure.alt, mobileVariants: figure.mobileVariants, variants: figure.variants }}
        sizes={SHOT_SIZES}
      />
    );
  }
  return (
    <figure className="lp-blog__figure lp-blog__figure--diagram">
      <div className="lp-blog__figure-media">
        <Picture
          alt={figure.alt}
          className="lp-blog__figure-img"
          mobileSizes="calc(100vw - 40px)"
          mobileVariants={figure.mobileVariants}
          sizes={DIAGRAM_SIZES}
          variants={figure.variants}
        />
      </div>
      <figcaption className="lp-blog__figure-caption">{figure.caption}</figcaption>
    </figure>
  );
}
