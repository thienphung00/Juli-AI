import { handleTikTokRelayRequest, type TikTokRelayOptions } from "./handler";

/**
 * Nothing legitimate reaches this size: four event names, one id, a URL, a
 * referrer, two digests. Rejecting on the declared length costs nothing and
 * means an oversized body is never parsed.
 */
const MAX_BODY_BYTES = 8192;

/**
 * Read the client address the edge resolved.
 *
 * `X-Real-IP` is set by both public vhosts, and nginx has already rewritten
 * `$remote_addr` from `CF-Connecting-IP` (infra/scripts/cloudflare-origin-lockdown.sh),
 * so this is the visitor's address and not Cloudflare's. `X-Forwarded-For` is
 * the fallback, first hop only — the later entries are client-supplied.
 */
function clientIp(headers: Headers): string | null {
  const realIp = headers.get("x-real-ip");

  if (realIp) {
    return realIp;
  }

  return headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null;
}

/**
 * Build the POST handler each app mounts at `TIKTOK_RELAY_PATH`.
 *
 * It lives here rather than being written out twice because the two copies
 * would differ only in their allowed origins, and the half that is worth
 * getting right — what counts as the client address, what is refused before
 * parsing — is the half that would drift.
 */
export function createTikTokRelayRoute(
  options: Pick<TikTokRelayOptions, "allowedOrigins"> &
    Partial<Omit<TikTokRelayOptions, "allowedOrigins">>,
): (request: Request) => Promise<Response> {
  return async function POST(request: Request): Promise<Response> {
    if (Number(request.headers.get("content-length") ?? "0") > MAX_BODY_BYTES) {
      return Response.json({ status: "rejected" }, { status: 413 });
    }

    let body: unknown;

    try {
      body = await request.json();
    } catch {
      return Response.json({ status: "rejected" }, { status: 400 });
    }

    const result = await handleTikTokRelayRequest(
      {
        body,
        cookieHeader: request.headers.get("cookie"),
        ip: clientIp(request.headers),
        origin: request.headers.get("origin"),
        referer: request.headers.get("referer"),
        userAgent: request.headers.get("user-agent"),
      },
      options,
    );

    return Response.json(result.body, { status: result.status });
  };
}
