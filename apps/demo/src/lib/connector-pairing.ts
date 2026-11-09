/**
 * The seller's side of the Juli Connector pairing (P96, owner 2026-11-06): `/v1/ingest/*` with the
 * seller's session and `X-Shop-Id`, the same endpoints the extension's pairing code is exchanged
 * against. A code is single-use and short-lived; a token's secret never comes back to the page.
 */

export interface SellerPairingCode {
  readonly code: string;
  readonly expires_at: string;
  readonly ttl_seconds: number;
}

export interface SellerIngestToken {
  readonly id: string;
  readonly client_label: string | null;
  readonly last_used_at: string | null;
  readonly active: boolean;
}

export class PairingRequestError extends Error {
  constructor(public readonly status: number) {
    super(`pairing request failed (${status})`);
  }
}

interface Auth {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

async function call(auth: Auth, path: string, method: "GET" | "POST" | "DELETE"): Promise<Response> {
  const response = await (auth.fetchImpl ?? fetch)(path, {
    method,
    headers: { Accept: "application/json", Authorization: `Bearer ${auth.token}`, "X-Shop-Id": auth.shopId },
    cache: "no-store",
  });
  if (!response.ok) throw new PairingRequestError(response.status);
  return response;
}

export async function createSellerPairingCode(auth: Auth): Promise<SellerPairingCode> {
  return (await (await call(auth, "/v1/ingest/pairing-codes", "POST")).json()) as SellerPairingCode;
}

export async function listSellerIngestTokens(auth: Auth): Promise<readonly SellerIngestToken[]> {
  const body = (await (await call(auth, "/v1/ingest/tokens", "GET")).json()) as { data?: SellerIngestToken[] };
  return body.data ?? [];
}

export async function revokeSellerIngestToken(auth: Auth, tokenId: string): Promise<void> {
  await call(auth, `/v1/ingest/tokens/${encodeURIComponent(tokenId)}`, "DELETE");
}
