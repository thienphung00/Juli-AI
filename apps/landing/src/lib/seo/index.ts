/**
 * Technical SEO helpers for app-juli.com (D43.5, P33-A). See ./README.md.
 */
export {
  absoluteUrl,
  CONTENT_LANGUAGE,
  DEFAULT_OG_IMAGE,
  DESCRIPTION_MAX_LENGTH,
  OG_LOCALE,
  type OgImage,
  SITE_NAME,
  SITE_URL,
  TITLE_MAX_LENGTH,
  TITLE_SUFFIX,
} from "./config";
export { JsonLd, serializeJsonLd } from "./json-ld";
export {
  buildMetadata,
  type BuildMetadataOptions,
  metadataForRoute,
  ROOT_METADATA,
} from "./metadata";
export { sitemapEntries } from "./sitemap";
export {
  type BreadcrumbItem,
  breadcrumbTrail,
  getRoute,
  hasRoute,
  SITE_ROUTES,
  type SiteRoute,
} from "./routes";
export {
  articleSchema,
  type ArticleInput,
  breadcrumbSchema,
  faqPageSchema,
  type FaqItem,
  type JsonLdObject,
  ORGANIZATION_ID,
  organizationSchema,
  PRICE_VND,
  SERVICE_ID,
  type ServiceInput,
  servicePageSchema,
  type ServicePageInput,
  serviceSchema,
  videoObjectSchema,
  type VideoObjectInput,
  WEBSITE_ID,
  websiteSchema,
} from "./schema";
