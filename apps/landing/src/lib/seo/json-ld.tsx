import type { JsonLdObject } from "./schema";

const CONTEXT = "https://schema.org";

/**
 * Serialises JSON-LD safely inside a <script>: `<` is escaped so a string
 * containing `</script>` cannot close the tag.
 */
export function serializeJsonLd(data: JsonLdObject | readonly JsonLdObject[]): string {
  const payload = Array.isArray(data)
    ? { "@context": CONTEXT, "@graph": data }
    : { "@context": CONTEXT, ...(data as JsonLdObject) };
  return JSON.stringify(payload).replace(/</g, "\\u003c");
}

/**
 * Renders one `<script type="application/ld+json">`. Pass one builder result,
 * or an array (emitted as an `@graph`). Server component; no client JS.
 *
 *     <JsonLd data={[breadcrumbSchema("/san-pham"), softwareApplicationSchema({ path: "/san-pham" })]} />
 */
export function JsonLd({ data }: { data: JsonLdObject | readonly JsonLdObject[] }) {
  return (
    <script
      // JSON-LD is data, not executable script; the payload is escaped above.
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
      type="application/ld+json"
    />
  );
}
