/**
 * schema.org builders (D43.5). Each returns a plain object without `@context`;
 * `<JsonLd>` adds it. Entities reference the Organization / WebSite by `@id`
 * so Google joins them across pages.
 *
 * No `sameAs` (D43.8: no social links). FAQPage only for questions that are
 * visibly rendered on the same page.
 */
import { COMPANY } from "../site";
import {
  absoluteUrl,
  CONTENT_LANGUAGE,
  DEFAULT_OG_IMAGE,
  ORGANIZATION_LOGO,
  SITE_NAME,
  SITE_URL,
} from "./config";
import { breadcrumbTrail, getRoute } from "./routes";

export type JsonLdObject = { "@type": string } & Record<string, unknown>;

export const ORGANIZATION_ID = `${SITE_URL}/#organization`;
export const WEBSITE_ID = `${SITE_URL}/#website`;
export const SERVICE_ID = `${SITE_URL}/#service`;

/** Monthly list price (D43.5, `/terms` §5). */
export const PRICE_VND = 500000;

export function organizationSchema(): JsonLdObject {
  return {
    "@type": "Organization",
    "@id": ORGANIZATION_ID,
    name: SITE_NAME,
    legalName: COMPANY.name,
    url: SITE_URL,
    logo: {
      "@type": "ImageObject",
      url: absoluteUrl(ORGANIZATION_LOGO.url),
      width: ORGANIZATION_LOGO.width,
      height: ORGANIZATION_LOGO.height,
    },
    email: COMPANY.email,
    taxID: COMPANY.taxId,
    address: { "@type": "PostalAddress", ...COMPANY.postalAddress },
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "customer support",
      email: COMPANY.email,
      areaServed: "VN",
      availableLanguage: ["vi"],
    },
  };
}

export function websiteSchema(): JsonLdObject {
  return {
    "@type": "WebSite",
    "@id": WEBSITE_ID,
    // Google's site-name signal: the home page URL exactly as canonicalised
    // (trailing slash) plus the name and a short alternate.
    url: `${SITE_URL}/`,
    name: SITE_NAME,
    alternateName: "Juli",
    inLanguage: CONTENT_LANGUAGE,
    publisher: { "@id": ORGANIZATION_ID },
  };
}

/** BreadcrumbList from the registry trail (Home → … → page). Inner pages only. */
export function breadcrumbSchema(path: string): JsonLdObject {
  const trail = breadcrumbTrail(path);
  return {
    "@type": "BreadcrumbList",
    itemListElement: trail.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  };
}

/**
 * What Juli sells, as a schema.org `Service` (D48 additions 2). Not
 * `SoftwareApplication`: Google requires `aggregateRating` or `review` on that
 * type, and Juli has no real reviews (D43.3), so none is ever invented.
 */
export interface ServiceInput {
  /** The page that describes the service (registry path). */
  path: string;
  name?: string;
  description?: string;
}

/** Service + Offer (500000 VND / month), provided by the Organization. `/san-pham` only. */
export function serviceSchema(input: ServiceInput): JsonLdObject {
  const route = getRoute(input.path);
  const url = absoluteUrl(route.path);
  return {
    "@type": "Service",
    "@id": SERVICE_ID,
    name: input.name ?? SITE_NAME,
    serviceType: "Phần mềm AI phân tích và vận hành TMĐT",
    description: input.description ?? route.description,
    url,
    provider: { "@id": ORGANIZATION_ID },
    areaServed: { "@type": "Country", name: "Việt Nam" },
    availableChannel: {
      "@type": "ServiceChannel",
      serviceUrl: url,
      availableLanguage: CONTENT_LANGUAGE,
    },
    offers: {
      "@type": "Offer",
      price: PRICE_VND,
      priceCurrency: "VND",
      url,
      availability: "https://schema.org/InStock",
      seller: { "@id": ORGANIZATION_ID },
      priceSpecification: {
        "@type": "UnitPriceSpecification",
        price: PRICE_VND,
        priceCurrency: "VND",
        unitCode: "MON",
        unitText: "tháng",
      },
    },
  };
}

export interface ServicePageInput {
  /** Registry path of the capability page. */
  path: string;
  /** Optional screenshot URL, site-relative or absolute. */
  screenshot?: string;
}

/**
 * WebPage for a capability page: part of the WebSite, `about` the Service of
 * `/san-pham` (by `@id`, so the offer is stated once).
 */
export function servicePageSchema(input: ServicePageInput): JsonLdObject {
  const route = getRoute(input.path);
  const url = absoluteUrl(route.path);
  return {
    "@type": "WebPage",
    "@id": `${url}#webpage`,
    url,
    name: route.title.replace(/ \| Juli AI$/, ""),
    description: route.description,
    inLanguage: CONTENT_LANGUAGE,
    isPartOf: { "@id": WEBSITE_ID },
    about: { "@id": SERVICE_ID },
    ...(input.screenshot
      ? { primaryImageOfPage: { "@type": "ImageObject", url: absoluteUrl(input.screenshot) } }
      : {}),
  };
}

/**
 * Plain WebPage for a page that is not about the paid Service, e.g. a free
 * tool (D49.1): part of the WebSite, published by the Organization. Never
 * `WebApplication` / `SoftwareApplication`: Google wants ratings on those and
 * Juli has none (D43.3, D48 additions 2).
 */
export function webPageSchema(path: string): JsonLdObject {
  const route = getRoute(path);
  const url = absoluteUrl(route.path);
  return {
    "@type": "WebPage",
    "@id": `${url}#webpage`,
    url,
    name: route.title.replace(/ \| Juli AI$/, ""),
    description: route.description,
    inLanguage: CONTENT_LANGUAGE,
    isPartOf: { "@id": WEBSITE_ID },
    publisher: { "@id": ORGANIZATION_ID },
  };
}

export interface FaqItem {
  question: string;
  answer: string;
}

/** FAQPage — pass exactly the questions rendered on the page. */
export function faqPageSchema(items: readonly FaqItem[]): JsonLdObject {
  if (items.length === 0) throw new Error("SEO: faqPageSchema needs at least one rendered FAQ item");
  return {
    "@type": "FAQPage",
    mainEntity: items.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: { "@type": "Answer", text: item.answer },
    })),
  };
}

export interface ArticleInput {
  /** Registry path of the post. */
  path: string;
  headline?: string;
  description?: string;
  /** ISO 8601 (`2026-10-20` or full timestamp). */
  datePublished: string;
  dateModified?: string;
  /** Site-relative or absolute image URL(s); defaults to the branded card. */
  image?: string | string[];
  /** A named person if one wrote it; otherwise the Organization is the author. */
  authorName?: string;
}

export function articleSchema(input: ArticleInput): JsonLdObject {
  const route = getRoute(input.path);
  const url = absoluteUrl(route.path);
  const images = (input.image
    ? Array.isArray(input.image)
      ? input.image
      : [input.image]
    : [route.ogImage?.url ?? DEFAULT_OG_IMAGE.url]
  ).map(absoluteUrl);
  return {
    "@type": "Article",
    headline: input.headline ?? route.title.replace(/ \| Juli AI$/, ""),
    description: input.description ?? route.description,
    url,
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    image: images,
    datePublished: input.datePublished,
    dateModified: input.dateModified ?? input.datePublished,
    inLanguage: CONTENT_LANGUAGE,
    author: input.authorName
      ? { "@type": "Person", name: input.authorName }
      : { "@id": ORGANIZATION_ID },
    publisher: { "@id": ORGANIZATION_ID },
  };
}

export interface VideoObjectInput {
  name: string;
  description: string;
  /** Poster image(s), site-relative or absolute. */
  thumbnailUrl: string | string[];
  /** ISO 8601 date the video was first published. */
  uploadDate: string;
  /** Site-relative or absolute URL of the video file. */
  contentUrl: string;
  /** ISO 8601 duration, e.g. `PT1M4S`. */
  duration?: string;
}

export function videoObjectSchema(input: VideoObjectInput): JsonLdObject {
  const thumbnails = (Array.isArray(input.thumbnailUrl) ? input.thumbnailUrl : [input.thumbnailUrl]).map(
    absoluteUrl,
  );
  return {
    "@type": "VideoObject",
    name: input.name,
    description: input.description,
    thumbnailUrl: thumbnails,
    uploadDate: input.uploadDate,
    contentUrl: absoluteUrl(input.contentUrl),
    ...(input.duration ? { duration: input.duration } : {}),
    inLanguage: CONTENT_LANGUAGE,
    publisher: { "@id": ORGANIZATION_ID },
  };
}
