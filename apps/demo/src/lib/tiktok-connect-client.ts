/**
 * `GET /v1/auth/tiktok/start` — the seller-initiated TikTok Shop connect
 * (issue #1970). Same-origin relative path, matching `shops-client.ts` and the
 * existing `apps/demo` contract (#397): no client-side API base env var. The
 * demo vhost proxies `/v1/` to the API upstream
 * (`infra/nginx/demo.app-juli.com.conf`).
 *
 * The response carries the partner authorize URL with a signed `state` already
 * embedded — the state names the signed-in user and is what binds the connected
 * shop to them. The browser only navigates; it never constructs the URL, and it
 * never sees or handles the state as a separate value.
 *
 * Why a fetch-then-navigate instead of a plain link: the route requires the
 * Supabase bearer token, and a bearer token cannot ride a top-level navigation.
 */

/**
 * Named `CONNECT_START_PATH`, and deliberately not after the vendor.
 * `tests/unit/test_issue_397_demo_workspace_contract.py` bans that vendor
 * prefix, in the screaming-snake env-name shape, anywhere in `apps/demo`
 * source — it is the shape of a TikTok app-credential environment variable,
 * and demo source is compiled into a public browser bundle. The guard is
 * textual and cannot tell a path constant from an env read, which is the right
 * side to err on. Do not rename this back.
 */
export const CONNECT_START_PATH = "/v1/auth/tiktok/start" as const;

export interface TikTokOAuthStart {
  authorize_url: string;
  state_expires_in: number;
}

export class TikTokConnectError extends Error {
  constructor(
    public readonly status: number,
    detail?: string,
  ) {
    super(detail ?? `TikTok connect start failed (${status})`);
    this.name = "TikTokConnectError";
  }
}

export async function startTikTokConnect(
  accessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<TikTokOAuthStart> {
  const response = await fetchImpl(CONNECT_START_PATH, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail: string | undefined;

    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail;
    } catch {
      detail = undefined;
    }

    throw new TikTokConnectError(response.status, detail);
  }

  return (await response.json()) as TikTokOAuthStart;
}
