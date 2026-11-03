"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { ShopeeLinks } from "../shopee-analytics/links";
import type { RecoApi } from "./client";
import type { DecisionTab } from "./model";

/**
 * What a Shopee Quyết định screen needs from its host: the card API (seller or Ops base), the
 * analytics links (for "Xem phân tích ›"), whether it is read-only (Ops "Xem như shop"), whether
 * staff actions show (the Ops "Đề xuất" tab), and the hrefs of its own two views.
 */
export interface RecoHost {
  readonly reco: RecoApi;
  readonly links: ShopeeLinks;
  /** Stable id of the shop, part of every request key. */
  readonly shopKey: string;
  readonly shopName?: string;
  /** Juli Ops "Xem như shop": reading and what-if only; every control that writes is disabled. */
  readonly readOnly?: boolean;
  /** Juli Ops "Đề xuất" tab: generate, publish, withdraw, "Đã làm" by staff. */
  readonly staff?: boolean;
  /** The list (a tab) or one card of this host. */
  readonly href: (view: { readonly tab?: DecisionTab; readonly the?: string | null; readonly from?: string | null }) => string;
  /** Follow an in-page href without a full navigation, when the host has a router of its own. */
  readonly navigate?: (href: string) => void;
  /** The clock, for the measurement countdown (tests). */
  readonly now?: () => Date;
}

const Ctx = createContext<RecoHost | null>(null);

export function RecoHostProvider({ host, children }: { readonly host: RecoHost; readonly children: ReactNode }) {
  return <Ctx.Provider value={host}>{children}</Ctx.Provider>;
}

export function useReco(): RecoHost {
  const host = useContext(Ctx);
  if (!host) throw new Error("useReco must be used inside RecoHostProvider");
  return host;
}

/** `?tab=…&the=…` appended to a base path. */
export function decisionsQuery(view: { readonly tab?: DecisionTab; readonly the?: string | null; readonly from?: string | null }, extra?: URLSearchParams): URLSearchParams {
  const p = new URLSearchParams(extra);
  if (view.tab && view.tab !== "de-xuat") p.set("tab", view.tab);
  if (view.the) p.set("the", view.the);
  if (view.from) p.set("from", view.from);
  return p;
}
