import type { Metadata } from "next";

import {
  absoluteUrl,
  DEFAULT_OG_IMAGE,
  OG_LOCALE,
  type OgImage,
  SITE_NAME,
  SITE_URL,
} from "./config";
import { getRoute } from "./routes";

export interface BuildMetadataOptions {
  /** Override the registry's social image (1200×630). */
  ogImage?: OgImage;
  /** Articles only: ISO dates for `article:published_time` / `modified_time`. */
  publishedTime?: string;
  modifiedTime?: string;
  /** Articles only: author names for `article:author`. */
  authors?: string[];
}

/**
 * Next `Metadata` for a registered page: unique title (absolute, no template),
 * description, absolute self canonical, Open Graph (vi_VN, 1200×630 image) and
 * a large Twitter card. Usage in a page:
 *
 *     export const metadata = buildMetadata("/san-pham");
 *
 * No `alternates.languages` (hreflang) — the site is Vietnamese only (D43.8).
 */
export function buildMetadata(path: string, options: BuildMetadataOptions = {}): Metadata {
  const route = getRoute(path);
  const url = absoluteUrl(route.path);
  const image = options.ogImage ?? route.ogImage ?? DEFAULT_OG_IMAGE;
  const imageEntry = {
    url: absoluteUrl(image.url),
    width: image.width,
    height: image.height,
    alt: image.alt,
  };
  const common = {
    title: route.title,
    description: route.description,
    url,
    siteName: SITE_NAME,
    locale: OG_LOCALE,
    images: [imageEntry],
  };

  return {
    title: { absolute: route.title },
    description: route.description,
    alternates: { canonical: url },
    openGraph:
      route.ogType === "article"
        ? {
            ...common,
            type: "article",
            publishedTime: options.publishedTime,
            modifiedTime: options.modifiedTime ?? options.publishedTime,
            authors: options.authors,
          }
        : { ...common, type: "website" },
    twitter: {
      card: "summary_large_image",
      title: route.title,
      description: route.description,
      images: [{ url: imageEntry.url, alt: image.alt }],
    },
  };
}

/** Site-wide defaults for the root layout; every page overrides with `buildMetadata`. */
export const ROOT_METADATA: Metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
  // A page that forgets `buildMetadata` still gets a sane title; the SEO check
  // flags it anyway because the title would not be unique.
  title: SITE_NAME,
  formatDetection: { telephone: false, email: false, address: false },
};
