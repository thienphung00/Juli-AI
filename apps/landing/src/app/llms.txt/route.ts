import { llmsTxt, SITE_ROUTES } from "../../lib/seo";

/** `/llms.txt` (D48 additions 4), prerendered from the route registry. */
export const dynamic = "force-static";

export function GET(): Response {
  return new Response(llmsTxt(SITE_ROUTES), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
