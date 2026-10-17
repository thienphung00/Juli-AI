/**
 * Competitor registry for the blog (D56 G1 / G2, `fasttrack/content-plan.md`).
 *
 * Three rings decide where a tool may be NAMED; for LINKS the ring does not
 * matter: no post body or source ever links a domain listed here (a source
 * from one of them is cited by name and check date, `checkedAt`, without a
 * URL). `blog.test.tsx` enforces both, and the post page unlinks any such
 * href defensively (`isCompetitorUrl`).
 *
 * - `direct`: overlaps with what Juli does. Named only in posts of category
 *   `tools` (comparison posts), short factual lines, never linked.
 * - `adjacent`: AI chatbots / AI sales agents. Never named in any post; say
 *   "chatbot trả lời tin nhắn" in general terms.
 * - `not-competing`: content / design tools and multichannel sales software.
 *   Named normally, never linked.
 *
 * Names are matched case-sensitively as whole words. Pancake is split by
 * product: its chat inbox is adjacent, Pancake POS (multichannel sales
 * software, in the đa kênh post) is not competing; both share the domain.
 */

export type CompetitorRing = "direct" | "adjacent" | "not-competing";

export interface Competitor {
  /** Names (and product names) as a post would write them. */
  names: readonly string[];
  /** Registrable domains; any subdomain matches. Empty: no own site to link. */
  domains: readonly string[];
  ring: CompetitorRing;
}

export const COMPETITORS: readonly Competitor[] = [
  // Direct (G1): AI product optimisation and TikTok Shop analytics.
  { ring: "direct", names: ["Sapo"], domains: ["sapo.vn"] },
  { ring: "direct", names: ["Tối ưu sản phẩm bởi AI"], domains: [] }, // Shopee's built-in tool
  { ring: "direct", names: ["Atosa"], domains: ["atosa.asia", "atosa.vn"] },
  { ring: "direct", names: ["FastMoss"], domains: ["fastmoss.com"] },
  { ring: "direct", names: ["Kalodata"], domains: ["kalodata.com"] },
  { ring: "direct", names: ["Metric"], domains: ["metric.vn"] },

  // Adjacent (G1): AI chatbots and AI sales agents. Never named.
  { ring: "adjacent", names: ["Preny"], domains: ["preny.ai", "preny.vn"] },
  { ring: "adjacent", names: ["Fchat"], domains: ["fchat.vn"] },
  { ring: "adjacent", names: ["Botcake"], domains: ["botcake.io"] },
  { ring: "adjacent", names: ["AhaChat"], domains: ["ahachat.com"] },
  { ring: "adjacent", names: ["Smax"], domains: ["smax.ai"] },
  { ring: "adjacent", names: ["Hana"], domains: ["hana.ai"] },
  { ring: "adjacent", names: ["Bizfly Chat", "Bizfly"], domains: ["bizfly.vn"] },
  { ring: "adjacent", names: ["Harasocial"], domains: ["harasocial.com"] },
  { ring: "adjacent", names: ["Pancake Inbox", "Pancake inbox"], domains: ["pancake.vn", "pages.fm"] },

  // Not competing (G1): content / design tools, and the multichannel vendors of
  // `phan-mem-quan-ly-ban-hang-da-kenh-2026`. Named normally, never linked.
  { ring: "not-competing", names: ["CapCut"], domains: ["capcut.com"] },
  { ring: "not-competing", names: ["Canva"], domains: ["canva.com"] },
  { ring: "not-competing", names: ["Photoroom"], domains: ["photoroom.com"] },
  { ring: "not-competing", names: ["Higgsfield"], domains: ["higgsfield.ai"] },
  { ring: "not-competing", names: ["Pippit"], domains: ["pippit.ai"] },
  { ring: "not-competing", names: ["KiotViet"], domains: ["kiotviet.vn"] },
  { ring: "not-competing", names: ["Nhanh.vn", "Nhanh.Ecom"], domains: ["nhanh.vn"] },
  { ring: "not-competing", names: ["BigSeller"], domains: ["bigseller.com"] },
  { ring: "not-competing", names: ["Haravan"], domains: ["haravan.com"] },
  { ring: "not-competing", names: ["MISA eShop"], domains: ["misa.vn"] },
  { ring: "not-competing", names: ["Pancake POS"], domains: ["pancake.vn", "pages.fm"] },
];

/** Every registry domain, any ring. */
export const COMPETITOR_DOMAINS: readonly string[] = [...new Set(COMPETITORS.flatMap((c) => c.domains))];

/** True when `href` is an absolute URL on a registry domain or one of its subdomains. */
export function isCompetitorUrl(href: string): boolean {
  let host: string;
  try {
    host = new URL(href).hostname.toLowerCase();
  } catch {
    return false; // relative or malformed: not an external link
  }
  return COMPETITOR_DOMAINS.some((domain) => host === domain || host.endsWith(`.${domain}`));
}

/** Registry names of `ring` that appear in `text` as whole words (case-sensitive). */
export function competitorNamesIn(text: string, ring: CompetitorRing): string[] {
  return COMPETITORS.filter((c) => c.ring === ring).flatMap((c) =>
    c.names.filter((name) => {
      const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(`(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`, "u").test(text);
    }),
  );
}
