"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { fetchShopAnalysis } from "../shop-analysis/api-client";
import type { ShopAnalysisEnvelope } from "../shop-analysis/types";
import { readActiveShop } from "../shop-session";
import { readAuthSession } from "../supabase-auth";

/**
 * Who the app is showing, and that shop's latest ADR-108 report — resolved
 * ONCE by the app shell (AC-8.5) so the header ("Juli đang chạy · cập nhật
 * HH:MM") and Home read the same envelope instead of each fetching it.
 *
 * - No stored Supabase session → `anonymous`: the bundled synthetic sample
 *   (the invented cosmetics shop of `phan-tich/sample-data.ts`), loaded lazily so the layout chunk stays small; no
 *   request leaves the origin.
 * - Session but no acting shop → `no-shop`: Home, Phân tích and Quyết định
 *   show the same bundled sample under a "Kết nối TikTok Shop ›" strip (P13).
 * - Session + shop → `GET /v1/demo/analysis` (default ranking) through the
 *   one authenticated client; 404 → `empty`, failure → `error` (never the
 *   sample standing in for the seller's shop).
 *
 * Phân tích (AC-8.6) reads it too; only its rankings are fetched per cell.
 */

export interface ActingShop {
  readonly id: string;
  readonly name: string;
}

export type ShopReportState =
  | { readonly status: "resolving" }
  | { readonly status: "anonymous"; readonly envelope: ShopAnalysisEnvelope | null }
  | { readonly status: "no-shop"; readonly token: string }
  | { readonly status: "loading"; readonly token: string; readonly shop: ActingShop }
  | { readonly status: "empty"; readonly token: string; readonly shop: ActingShop }
  | { readonly status: "error"; readonly token: string; readonly shop: ActingShop }
  | {
      readonly status: "ready";
      readonly token: string;
      readonly shop: ActingShop;
      readonly envelope: ShopAnalysisEnvelope;
    };

export interface ShopReportContextValue {
  readonly state: ShopReportState;
  /** Re-run the signed-in fetch (after an error). No-op when anonymous. */
  readonly reload: () => void;
}

const ShopReportContext = createContext<ShopReportContextValue | null>(null);

/** The bundled sample (P13: the cosmetics shop Phân tích and Quyết định show) — built in memory, never fetched. */
async function loadSample(): Promise<ShopAnalysisEnvelope> {
  const { sampleEnvelope } = await import("../phan-tich/sample-data");
  return sampleEnvelope();
}

interface ShopReportProviderProps {
  readonly children: ReactNode;
  /** Injectable for tests; defaults to the real authenticated client. */
  readonly loadAnalysis?: typeof fetchShopAnalysis;
}

export function ShopReportProvider({
  children,
  loadAnalysis = fetchShopAnalysis,
}: ShopReportProviderProps) {
  const [state, setState] = useState<ShopReportState>({ status: "resolving" });
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Deferred like every other browser-storage read in this app, so the
    // server render and the first client render agree.
    const timer = window.setTimeout(() => {
      const session = readAuthSession();
      if (!session) {
        setState({ status: "anonymous", envelope: null });
        loadSample()
          .then((envelope) => {
            if (!cancelled) setState({ status: "anonymous", envelope });
          })
          .catch(() => undefined);
        return;
      }
      const token = session.accessToken;
      const active = readActiveShop();
      if (!active) {
        setState({ status: "no-shop", token });
        return;
      }
      const shop: ActingShop = { id: active.id, name: active.name };
      setState({ status: "loading", token, shop });
      loadAnalysis({ token, shopId: shop.id })
        .then((envelope) => {
          if (cancelled) return;
          setState(
            envelope
              ? { status: "ready", token, shop, envelope }
              : { status: "empty", token, shop },
          );
        })
        .catch(() => {
          if (!cancelled) setState({ status: "error", token, shop });
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [loadAnalysis, reloadKey]);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);
  const value = useMemo(() => ({ state, reload }), [state, reload]);

  return <ShopReportContext.Provider value={value}>{children}</ShopReportContext.Provider>;
}

export function useShopReport(): ShopReportContextValue {
  const value = useContext(ShopReportContext);
  if (!value) {
    throw new Error("useShopReport must be used inside ShopReportProvider (the app shell).");
  }
  return value;
}

/** The envelope the header and Home show, whichever door the visitor used. */
export function envelopeOf(state: ShopReportState): ShopAnalysisEnvelope | null {
  if (state.status === "ready") return state.envelope;
  if (state.status === "anonymous") return state.envelope;
  return null;
}
