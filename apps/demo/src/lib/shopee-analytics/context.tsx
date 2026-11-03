"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { ShopeeApi } from "./client";
import type { ShopeeLinks } from "./links";

/**
 * What a Shopee shop screen needs from its host: the API (seller or Ops base), the links it
 * writes, whether it is the read-only Ops view, and the shop's name.
 */
export interface ShopeeHost {
  readonly api: ShopeeApi;
  readonly links: ShopeeLinks;
  /** Stable id of the API's shop, part of every request key. */
  readonly shopKey: string;
  readonly shopName?: string;
  /** Juli Ops: reading only (no copy-to-seller actions). */
  readonly readOnly?: boolean;
}

const Ctx = createContext<ShopeeHost | null>(null);

export function ShopeeHostProvider({ host, children }: { readonly host: ShopeeHost; readonly children: ReactNode }) {
  return <Ctx.Provider value={host}>{children}</Ctx.Provider>;
}

export function useShopee(): ShopeeHost {
  const host = useContext(Ctx);
  if (!host) throw new Error("useShopee must be used inside ShopeeHostProvider");
  return host;
}
