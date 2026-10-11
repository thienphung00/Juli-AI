import { readAuthSession } from "../supabase-auth";
import type {
  AuditEntry,
  Deltas,
  DisconnectResult,
  Invite,
  OpsMe,
  Overview,
  Scenario,
  ShopSettings,
  ShopSettingsPage,
  SimulationPage,
  ViewSession,
} from "./types";

/**
 * The Juli Ops client (`/v1/ops/*`, P16). Same-origin: on `ops.app-juli.com`
 * nginx proxies `/v1/` to the API, and Cloudflare Access adds the
 * `Cf-Access-Jwt-Assertion` header on the way in — the page never sees it.
 * The Supabase session is the ops host's own (localStorage is per origin).
 */
export const OPS_API = "/v1/ops" as const;

export class OpsApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`Ops API ${status}: ${detail}`);
    this.name = "OpsApiError";
  }
}

export interface OpsRequestOptions {
  readonly token?: string;
  readonly fetchImpl?: typeof fetch;
}

function tokenOf(options?: OpsRequestOptions): string {
  const token = options?.token ?? readAuthSession()?.accessToken;
  if (!token) throw new OpsApiError(401, "not signed in");
  return token;
}

export async function opsRequest<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
  options?: OpsRequestOptions,
): Promise<T> {
  const fetchImpl = options?.fetchImpl ?? fetch;
  const response = await fetchImpl(`${OPS_API}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${tokenOf(options)}`,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : response.statusText;
    throw new OpsApiError(response.status, detail);
  }
  return payload as T;
}

const shopPath = (shopId: string) => `/shops/${encodeURIComponent(shopId)}`;

export const opsApi = {
  me: (o?: OpsRequestOptions) => opsRequest<OpsMe>("/me", {}, o),
  overview: (o?: OpsRequestOptions) => opsRequest<Overview>("/overview", {}, o),
  audit: (shopId: string | null, o?: OpsRequestOptions) =>
    opsRequest<{ data: AuditEntry[] }>(shopId ? `/audit?shop_id=${encodeURIComponent(shopId)}` : "/audit", {}, o),
  staff: (o?: OpsRequestOptions) =>
    opsRequest<{ data: { id: string; email: string; role: string; role_label: string; active: boolean; signed_in: boolean }[] }>(
      "/staff",
      {},
      o,
    ),
  putStaff: (body: { email: string; role: string; active: boolean }, o?: OpsRequestOptions) =>
    opsRequest("/staff", { method: "PUT", body }, o),
  settings: (shopId: string, o?: OpsRequestOptions) => opsRequest<ShopSettingsPage>(`${shopPath(shopId)}/settings`, {}, o),
  putSettings: (shopId: string, changes: Record<string, unknown>, o?: OpsRequestOptions) =>
    opsRequest<{ settings: ShopSettings }>(`${shopPath(shopId)}/settings`, { method: "PUT", body: { changes } }, o),
  resetSettings: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<{ settings: ShopSettings }>(`${shopPath(shopId)}/settings/reset`, { method: "POST" }, o),
  invite: (shopId: string, email: string, keepOpsAccess: boolean, o?: OpsRequestOptions) =>
    opsRequest<{ data: Invite; email_sent: boolean; accept_url: string | null }>(
      `${shopPath(shopId)}/invites`,
      { method: "POST", body: { email, keep_ops_access: keepOpsAccess } },
      o,
    ),
  viewSession: (shopId: string, mode: "view" | "exit", o?: OpsRequestOptions) =>
    opsRequest<ViewSession>(`${shopPath(shopId)}/view-session`, { method: "POST", body: { mode } }, o),
  disconnect: (shopId: string, reason: string, confirmName: string, o?: OpsRequestOptions) =>
    opsRequest<{ data: DisconnectResult }>(
      `${shopPath(shopId)}/disconnect`,
      { method: "POST", body: { reason, confirm_name: confirmName } },
      o,
    ),
  simulation: (shopId: string, window: number, o?: OpsRequestOptions) =>
    opsRequest<SimulationPage>(`${shopPath(shopId)}/simulation?window=${window}`, {}, o),
  createScenario: (shopId: string, name: string, deltas: Deltas, isTarget: boolean, o?: OpsRequestOptions) =>
    opsRequest<{ data: Scenario }>(
      `${shopPath(shopId)}/scenarios`,
      { method: "POST", body: { name, deltas, is_target: isTarget } },
      o,
    ),
  setTarget: (shopId: string, scenarioId: string, o?: OpsRequestOptions) =>
    opsRequest<{ data: Scenario }>(
      `${shopPath(shopId)}/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: "PATCH", body: { is_target: true } },
      o,
    ),
};

export type OpsApi = typeof opsApi;
