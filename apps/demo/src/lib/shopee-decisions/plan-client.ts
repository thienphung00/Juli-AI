import { ShopeeApiError } from "../shopee-analytics/client";
import type { Plan, PlanApi, PlanWindowBody } from "./plan-types";

/**
 * Client of the draft plan (assumed routes, see `plan-types.ts`). It shares the recommendation
 * base and headers with {@link createRecoApi}; `base` is `DEMO_RECO_BASE` or `opsRecoBase(shopId)`.
 */

export interface PlanClientOptions {
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

/** Feature flag: the plan UI shows only where the backend is there (`NEXT_PUBLIC_P91_PLAN=1`). */
export function planEnabled(): boolean {
  return process.env.NEXT_PUBLIC_P91_PLAN === "1";
}

/** Feature flag for the KOL screens (`NEXT_PUBLIC_P91_KOL=1`). */
export function kolEnabled(): boolean {
  return process.env.NEXT_PUBLIC_P91_KOL === "1";
}

export function createPlanApi(options: PlanClientOptions): PlanApi {
  const { base, token, shopId, fetchImpl } = options;
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await (fetchImpl ?? fetch)(`${base}/plan${path}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      cache: "no-store",
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const detail = (payload as { detail?: unknown } | null)?.detail;
      if (detail && typeof detail === "object") {
        const d = detail as { code?: unknown; message?: unknown };
        throw new ShopeeApiError(response.status, typeof d.code === "string" ? d.code : "", typeof d.message === "string" ? d.message : `HTTP ${response.status}`, detail as Record<string, unknown>);
      }
      throw new ShopeeApiError(response.status, "", typeof detail === "string" ? detail : `HTTP ${response.status}`);
    }
    return payload as T;
  }
  const id = (cardId: string) => `/cards/${encodeURIComponent(cardId)}`;
  return {
    get: () => call<Plan>("GET", ""),
    add: (cardId, version, ack = false) => call<Plan>("POST", "/cards", { card_id: cardId, chosen_version: version, acknowledge_breaches: ack }),
    remove: (cardId) => call<Plan>("DELETE", id(cardId)),
    setVersion: (cardId, version, ack = false) => call<Plan>("PUT", id(cardId), { chosen_version: version, acknowledge_breaches: ack }),
    setWindow: (body: PlanWindowBody) => call<Plan>("PUT", "/window", body),
    mde: async (days) => (await call<{ days: number; by_product: Record<string, number> }>("GET", `/mde?days=${days}`)).by_product,
    confirm: (ack) => call<Plan>("POST", "/confirm", { acknowledge_breaches: ack }),
  };
}
