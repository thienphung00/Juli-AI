"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { NavPlatform } from "../app-navigation";
import type { ShopeeApi } from "./client";
import type { BuilderApi } from "../shopee-decisions/builder-api";
import type { RecoApi } from "../shopee-decisions/client";
import type { KolApi } from "../shopee-kol/types";
import type { ShopeeLinks } from "./links";
import type { StockApi } from "./stock";

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
  /** The shop's marketplace; picks the label table. Absent = Shopee. */
  readonly platform?: NavPlatform;
  /** Juli Ops: reading only (no copy-to-seller actions). */
  readonly readOnly?: boolean;
  /** P91: the shop's recommendation cards, for the product page's "Đề xuất" tab; absent = the tab is not shown. */
  readonly reco?: RecoApi;
  /** P92 B-2: the builder API, for the product page's "So sánh phân loại" expand; absent = no expand. */
  readonly builder?: BuilderApi;
  /** P91 D-9: KOL × sản phẩm × kênh (flag `NEXT_PUBLIC_P91_KOL`); absent = no KOL screens. */
  readonly kol?: KolApi;
  /** P100 Part S: Tổng quan › Sản phẩm stock rows + "Theo dõi"; absent = not shown (Ops, reviewer). */
  readonly stock?: StockApi;
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

/** The marketplace the screens label for (the platform label table); Shopee unless the host says otherwise. */
export function useHostPlatform(): NavPlatform {
  return useContext(Ctx)?.platform ?? "shopee";
}
