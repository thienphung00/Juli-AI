import { ShopeeApiError } from "../shopee-analytics/client";
import type { ChangeSet, PlanApi, PlanResponse } from "./plan-types";

/**
 * Client of the draft plan (routes in `plan-types.ts`). It shares the recommendation base and
 * headers with {@link createRecoApi}; `base` is `DEMO_RECO_BASE` or `opsRecoBase(shopId)`.
 */

export interface PlanClientOptions {
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

/** The plan UI is on; `NEXT_PUBLIC_P91_PLAN=0` switches it off (kept as a kill switch). */
export function planEnabled(): boolean {
  return process.env.NEXT_PUBLIC_P91_PLAN !== "0";
}

/** The KOL screens are on; `NEXT_PUBLIC_P91_KOL=0` switches them off. */
export function kolEnabled(): boolean {
  return process.env.NEXT_PUBLIC_P91_KOL !== "0";
}

export function createPlanApi(options: PlanClientOptions): PlanApi {
  const { base, token, shopId, fetchImpl } = options;
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await (fetchImpl ?? fetch)(`${base}${path}`, {
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
  const card = (cardId: string) => `/plan/cards/${encodeURIComponent(cardId)}`;
  return {
    get: () => call<PlanResponse>("GET", "/plan"),
    add: (cardId, version, ack = false) => call<PlanResponse>("POST", "/plan/cards", { card_id: cardId, chosen_version: version, acknowledge_breaches: ack }),
    remove: (cardId) => call<PlanResponse>("POST", `${card(cardId)}/remove`, {}),
    move: (cardId, position) => call<PlanResponse>("POST", `${card(cardId)}/move`, { position }),
    setVersion: (cardId, version) => call<PlanResponse>("POST", `${card(cardId)}/version`, { version }),
    whatIf: (cardId, inputs) => call<PlanResponse>("POST", `${card(cardId)}/whatif`, { inputs }),
    setWindow: (days, productId) => call<PlanResponse>("POST", "/plan/window", { days, ...(productId ? { product_id: productId } : {}) }),
    setChangeSetWindow: (id, days) => call<ChangeSet>("POST", `/change-sets/${encodeURIComponent(id)}/window`, { days }),
    refreshBase: () => call<PlanResponse>("POST", "/plan/refresh-base", {}),
    confirm: ({ acknowledgeBreaches, plannedDate, note }) => call<PlanResponse>("POST", "/plan/confirm", { acknowledge_breaches: acknowledgeBreaches, ...(plannedDate ? { planned_date: plannedDate } : {}), ...(note ? { note } : {}) }),
    changeSets: async (query) => {
      const qs = new URLSearchParams();
      if (query?.productId) qs.set("product_id", query.productId);
      if (query?.status) qs.set("status", query.status);
      const suffix = qs.toString();
      return (await call<{ change_sets: ChangeSet[] }>("GET", `/change-sets${suffix ? `?${suffix}` : ""}`)).change_sets;
    },
  };
}
