"use client";

import { useEffect, useRef, useState } from "react";

import { fetchOnboardingStatus, type OnboardingStatus } from "./api-client";

/** After a failed read the strip stays hidden and the next try comes this much later. */
export const ONBOARDING_ERROR_RETRY_MS = 60_000;

export interface UseOnboardingStatusOptions {
  readonly token: string;
  readonly shopId: string;
  /** Injectable for tests; defaults to the real client. */
  readonly fetchStatus?: typeof fetchOnboardingStatus;
  /** Called after every successful read (Quyết định re-reads its cards on it). */
  readonly onStatus?: (status: OnboardingStatus) => void;
}

/**
 * Polls `GET /v1/shops/me/onboarding` at the interval the server names
 * (`poll_interval_seconds`: 15 s while steps 1–2 run, 300 s while only the
 * history remains, `null` → stop). A failed read hides the strip (`null`) and
 * retries after {@link ONBOARDING_ERROR_RETRY_MS}.
 */
export function useOnboardingStatus({
  token,
  shopId,
  fetchStatus = fetchOnboardingStatus,
  onStatus,
}: UseOnboardingStatusOptions): OnboardingStatus | null {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStatusRef.current = onStatus;
  }, [onStatus]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const schedule = (ms: number) => {
      timer = window.setTimeout(load, ms);
    };
    function load() {
      fetchStatus({ token, shopId })
        .then((next) => {
          if (cancelled) return;
          setStatus(next);
          onStatusRef.current?.(next);
          const seconds = next.poll_interval_seconds;
          if (typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0) {
            schedule(seconds * 1000);
          }
        })
        .catch(() => {
          if (cancelled) return;
          setStatus(null);
          schedule(ONBOARDING_ERROR_RETRY_MS);
        });
    }
    load();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [fetchStatus, token, shopId]);

  return status;
}
