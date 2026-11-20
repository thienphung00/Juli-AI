"use client";

/**
 * Is the Juli tab on for the acting shop? `GET /v1/demo/juli/enabled` -> `{enabled: bool}`
 * (auth + `X-Shop-Id`). Anything but `{enabled: true}` -- 403, 404, a network error, a bad body --
 * means hidden: no error UI and no retry; one fetch per shop (cached for the page's lifetime).
 */
import { useEffect, useState } from "react";

import type { ShopReportState } from "../shop-report/shop-report-context";
import { JULI_BASE } from "./client";

const known = new Map<string, boolean>();
const inflight = new Map<string, Promise<boolean>>();

export function resetJuliEnabledCache(): void {
  known.clear();
  inflight.clear();
}

export function fetchJuliEnabled(token: string, shopId: string, fetchImpl?: typeof fetch, signal?: AbortSignal): Promise<boolean> {
  if (typeof window === "undefined" || signal?.aborted) return Promise.resolve(false);
  const cached = known.get(shopId);
  if (cached !== undefined) return Promise.resolve(cached);
  const pending = inflight.get(shopId);
  if (pending) return pending;
  const request = (async () => {
    let enabled = false;
    try {
      const response = await (fetchImpl ?? fetch)(`${JULI_BASE}/enabled`, {
        headers: { Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
        signal,
      });
      if (response.ok) {
        const body = (await response.json()) as { enabled?: unknown };
        enabled = body.enabled === true;
      }
    } catch {
      enabled = false;
    }
    inflight.delete(shopId);
    // An abort (unmount) is not an answer: never cache it, and touch nothing else after it.
    if (signal?.aborted) return false;
    known.set(shopId, enabled);
    return enabled;
  })();
  inflight.set(shopId, request);
  return request;
}

/** `true` / `false` once known; `null` while the answer is pending (or there is no shop to ask for). */
export function useJuliEnabled(state: ShopReportState | null, fetchImpl?: typeof fetch): boolean | null {
  const shopId = state && "shop" in state ? state.shop.id : null;
  const token = state && "token" in state ? state.token : null;
  const [answer, setAnswer] = useState<{ shopId: string; enabled: boolean } | null>(null);
  useEffect(() => {
    if (!shopId || !token || known.has(shopId)) return;
    let live = true;
    const controller = new AbortController();
    void fetchJuliEnabled(token, shopId, fetchImpl, controller.signal).then((enabled) => {
      if (live && !controller.signal.aborted) setAnswer({ shopId, enabled });
    });
    return () => {
      live = false;
      controller.abort();
    };
  }, [shopId, token, fetchImpl]);
  if (!shopId || !token) return false;
  return known.get(shopId) ?? (answer && answer.shopId === shopId ? answer.enabled : null);
}
