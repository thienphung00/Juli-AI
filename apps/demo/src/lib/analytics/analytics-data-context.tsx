"use client";

import type { DemoAnalyticsEnvelope } from "@juli/contracts";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { fetchDemoAnalytics } from "./api-client";
import type { AnalyticsRange } from "./main-kpis";

export type AnalyticsDataStatus = "idle" | "loading" | "ready" | "error";

interface AnalyticsDataContextValue {
  envelope: DemoAnalyticsEnvelope | null;
  status: AnalyticsDataStatus;
  refreshAnalytics: (range?: AnalyticsRange) => Promise<void>;
  loadAnalytics: (range?: AnalyticsRange) => Promise<void>;
}

const AnalyticsDataContext = createContext<AnalyticsDataContextValue | null>(
  null,
);

export function AnalyticsDataProvider({ children }: { children: ReactNode }) {
  const [envelope, setEnvelope] = useState<DemoAnalyticsEnvelope | null>(null);
  const [status, setStatus] = useState<AnalyticsDataStatus>("idle");
  const inFlightRef = useRef<Promise<void> | null>(null);

  const loadAnalytics = useCallback(async (range?: AnalyticsRange) => {
    if (inFlightRef.current) {
      await inFlightRef.current;
      return;
    }

    setStatus("loading");

    const request = (async () => {
      try {
        const nextEnvelope = await fetchDemoAnalytics(range);
        setEnvelope(nextEnvelope);
        setStatus("ready");
      } catch {
        setStatus("error");
      } finally {
        inFlightRef.current = null;
      }
    })();

    inFlightRef.current = request;
    await request;
  }, []);

  const refreshAnalytics = useCallback(
    async (range?: AnalyticsRange) => {
      await loadAnalytics(range);
    },
    [loadAnalytics],
  );

  const value = useMemo(
    () => ({
      envelope,
      status,
      refreshAnalytics,
      loadAnalytics,
    }),
    [envelope, loadAnalytics, refreshAnalytics, status],
  );

  return (
    <AnalyticsDataContext.Provider value={value}>
      {children}
    </AnalyticsDataContext.Provider>
  );
}

export function useAnalyticsData(): AnalyticsDataContextValue {
  const context = useContext(AnalyticsDataContext);

  if (!context) {
    throw new Error("useAnalyticsData must be used within AnalyticsDataProvider");
  }

  return context;
}

export function useAnalyticsBootstrap(range: AnalyticsRange): void {
  const { loadAnalytics } = useAnalyticsData();

  useEffect(() => {
    void loadAnalytics(range);
  }, [loadAnalytics, range]);
}
