"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { MarketScope } from "../shopee-analytics/market-price";
import type { ShopeeLinks } from "../shopee-analytics/links";
import type { KolCandidate } from "../../components/shopee-decisions/kol-builder";
import type { BuilderApi } from "./builder-api";
import type { BuilderP98Api } from "./builder-p98-api";
import type { RecoApi } from "./client";
import type { DecisionTab } from "./model";
import type { PlanApi } from "./plan-types";

/** A product the builder can put in a combo (id and name, from the product list). */
export interface ProductChoice {
  readonly id: string;
  readonly name: string;
}

/** P91 D-6 (wave 1b): the draft plan. Absent while the plan backend is off (`NEXT_PUBLIC_P91_PLAN`). */
export interface PlanHost {
  readonly api: PlanApi;
}

/** The views a host links between. */
export interface DecisionView {
  readonly tab?: DecisionTab;
  readonly the?: string | null;
  readonly from?: string | null;
  /** P91: Tự tạo phương án / So sánh phương án. */
  readonly builder?: boolean;
  /** The product the builder opens for (a product page or Quyết định). */
  readonly productId?: string | null;
  /** P91: the Kế hoạch panel. */
  readonly plan?: boolean;
}

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
  readonly href: (view: DecisionView) => string;
  /** The shop's products (id, name) for the builder; absent: the builder asks for ids. */
  readonly products?: () => Promise<readonly ProductChoice[]>;
  /** P92: the builder API (picker, evaluate / compare / choose, drafts). Absent: the P91 builder runs. */
  readonly builder?: BuilderApi;
  /** P98: combo / KOL / Quảng cáo builders (same base, token and shop as `builder`); absent: those tabs are not shown. */
  readonly p98?: BuilderP98Api;
  /** P98: the shop's KOL rows (from the KOL report) for the KOL builder. */
  readonly kols?: () => Promise<readonly KolCandidate[]>;
  /** P92 B-10: where the Giá thị trường marker of the builder price panels reads (seller or Ops base). */
  readonly market?: MarketScope;
  /** The draft plan (P91 D-6); absent while the plan backend is not there. */
  readonly plan?: PlanHost;
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

/** The host when there is one (a builder tab can render without the plan/choose actions). */
export function useRecoMaybe(): RecoHost | null {
  return useContext(Ctx);
}

/** `?tab=…&the=…` appended to a base path. */
export function decisionsQuery(view: DecisionView, extra?: URLSearchParams): URLSearchParams {
  const p = new URLSearchParams(extra);
  if (view.tab && view.tab !== "de-xuat") p.set("tab", view.tab);
  if (view.the) p.set("the", view.the);
  if (view.from) p.set("from", view.from);
  if (view.builder) p.set("tu-tao", "1");
  if (view.productId) p.set("sp", view.productId);
  if (view.plan) p.set("ke-hoach", "1");
  return p;
}
