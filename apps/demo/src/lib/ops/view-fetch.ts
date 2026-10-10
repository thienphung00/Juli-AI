/**
 * "Xem như shop" (D25.3): the seller screens run unchanged, but their requests
 * are re-pointed from the seller API (`/v1/demo/*`, which only answers the
 * shop's OWNER) to the ops view API, which answers staff with exactly the same
 * payloads for that shop. Reads are mapped; writes are refused here unless the
 * page is in "Làm thay seller" mode AND the write is one the act API supports
 * (approve, reject, rules). The server checks the same thing again.
 */

export const READ_ONLY_DETAIL = "Chỉ xem: bật \"Làm thay seller\" để thao tác";

interface Mapped {
  readonly url: string;
  readonly write: boolean;
}

function mapPath(path: string, search: string, method: string, shopBase: string): Mapped | null {
  const m = method.toUpperCase();
  if (m === "GET") {
    if (path === "/v1/demo/decisions") return { url: `${shopBase}/view/decisions`, write: false };
    if (path === "/v1/demo/analysis") return { url: `${shopBase}/view/analysis${search}`, write: false };
    if (path === "/v1/demo/analysis/rankings") return { url: `${shopBase}/view/analysis/rankings${search}`, write: false };
    if (path === "/v1/demo/rules") return { url: `${shopBase}/view/rules`, write: false };
    return null;
  }
  let match = /^\/v1\/demo\/decisions\/([^/]+)\/(approve|reject)$/.exec(path);
  if (m === "POST" && match) return { url: `${shopBase}/act/decisions/${match[1]}/${match[2]}`, write: true };
  match = /^\/v1\/demo\/rules\/([^/?]+)$/.exec(path);
  if ((m === "PUT" || m === "DELETE") && match) return { url: `${shopBase}/act/rules/${match[1]}${search}`, write: true };
  return null;
}

function refuse(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });
}

export function createOpsViewFetch(options: {
  readonly shopId: string;
  readonly act: boolean;
  readonly baseFetch?: typeof fetch;
}): typeof fetch {
  const base = options.baseFetch ?? fetch;
  const shopBase = `/v1/ops/shops/${encodeURIComponent(options.shopId)}`;
  const viewFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(raw, "http://ops.local");
    const method = init?.method ?? (typeof input === "object" && "method" in input ? input.method : "GET");
    const mapped = mapPath(url.pathname, url.search, method, shopBase);
    if (mapped === null) {
      return method.toUpperCase() === "GET" ? refuse(404, "Không có trong Xem như shop") : refuse(403, READ_ONLY_DETAIL);
    }
    if (mapped.write && !options.act) return refuse(403, READ_ONLY_DETAIL);
    const headers = new Headers(init?.headers);
    headers.delete("X-Shop-Id");
    return base(mapped.url, { ...init, headers });
  };
  return viewFetch as typeof fetch;
}
