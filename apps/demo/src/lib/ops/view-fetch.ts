/**
 * "Xem như shop" (D25.3, amended 2026-10-10: ALWAYS read-only). The seller
 * screens run unchanged, but their GETs are re-pointed from the seller API
 * (`/v1/demo/*`, which only answers the shop's OWNER) to the ops view API,
 * which answers staff with exactly the same payloads for that shop. Every write
 * is refused here; the server refuses it again (any non-GET under `/view/` is a
 * 403).
 */

export const READ_ONLY_DETAIL = "Xem như shop chỉ xem, không ghi được";

const READS: readonly [RegExp, (m: RegExpExecArray) => string][] = [
  [/^\/v1\/demo\/decisions$/, () => "/view/decisions"],
  [/^\/v1\/demo\/analysis$/, () => "/view/analysis"],
  [/^\/v1\/demo\/analysis\/rankings$/, () => "/view/analysis/rankings"],
  [/^\/v1\/demo\/rules$/, () => "/view/rules"],
  [/^\/v1\/demo\/runs$/, () => "/view/runs"],
  [/^\/v1\/demo\/runs\/([^/]+)$/, (m) => `/view/runs/${m[1]}`],
  [/^\/v1\/demo\/runs\/([^/]+)\/(changes|instructions|measurement)$/, (m) => `/view/runs/${m[1]}/${m[2]}`],
  [/^\/v1\/demo\/revert-questions$/, () => "/view/revert-questions"],
];

function refuse(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });
}

export function createOpsViewFetch(options: { readonly shopId: string; readonly baseFetch?: typeof fetch }): typeof fetch {
  const base = options.baseFetch ?? fetch;
  const shopBase = `/v1/ops/shops/${encodeURIComponent(options.shopId)}`;
  const viewFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(raw, "http://ops.local");
    const method = (init?.method ?? (typeof input === "object" && "method" in input ? input.method : "GET")).toUpperCase();
    if (method !== "GET") return refuse(403, READ_ONLY_DETAIL);
    for (const [pattern, to] of READS) {
      const match = pattern.exec(url.pathname);
      if (match) {
        const headers = new Headers(init?.headers);
        headers.delete("X-Shop-Id");
        return base(`${shopBase}${to(match)}${url.search}`, { ...init, headers });
      }
    }
    return refuse(404, "Không có trong Xem như shop");
  };
  return viewFetch as typeof fetch;
}
