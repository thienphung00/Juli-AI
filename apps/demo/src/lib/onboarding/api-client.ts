/**
 * `GET /v1/shops/me/onboarding` (fast track P17, `fasttrack/contracts/p17-onboarding-speed.md` §2):
 * where Juli is in reading a newly connected shop — quick scan, 60-day backfill +
 * full diagnosis, background history. Bearer + `X-Shop-Id`, like every other
 * signed-in `/v1/*` read. Read-only; signed-in door only (the sample doors never
 * import this module's callers' fetch path — they render no strip).
 */

export const ONBOARDING_API_PATH = "/v1/shops/me/onboarding" as const;

export type OnboardingStepKey = "quick_scan" | "backfill_diagnosis" | "history";
export type OnboardingStepStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface OnboardingStep {
  readonly key: OnboardingStepKey | string;
  readonly label: string;
  readonly status: OnboardingStepStatus;
  readonly percent: number | null;
  readonly eta_seconds: number | null;
  readonly detail: string | null;
}

export interface OnboardingStatus {
  readonly shop_id: string;
  /** Steps 1–2 still running: show the strip and poll fast. */
  readonly active: boolean;
  readonly current_step: number | null;
  readonly total_steps: number;
  /** "Juli đang đọc dữ liệu shop · bước N/3", "Đang tải lịch sử · còn N ngày", or null when done. */
  readonly label: string | null;
  /** 15 while active, 300 while only history remains, null when done (stop polling). */
  readonly poll_interval_seconds: number | null;
  readonly steps: readonly OnboardingStep[];
  readonly history_days_available: number;
  readonly history_target_days: number;
  readonly history_days_remaining: number;
  readonly history_complete: boolean;
  readonly window_90d_available: boolean;
}

export class OnboardingFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Onboarding status fetch failed (${status})`);
    this.name = "OnboardingFetchError";
  }
}

export interface OnboardingRequestOptions {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

function isStatus(value: unknown): value is OnboardingStatus {
  if (!value || typeof value !== "object") return false;
  const body = value as Partial<OnboardingStatus>;
  return typeof body.active === "boolean" && Array.isArray(body.steps);
}

export async function fetchOnboardingStatus(options: OnboardingRequestOptions): Promise<OnboardingStatus> {
  const { token, shopId, fetchImpl = fetch } = options;
  const response = await fetchImpl(ONBOARDING_API_PATH, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "X-Shop-Id": shopId,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new OnboardingFetchError(response.status);
  }
  const payload: unknown = await response.json();
  if (!isStatus(payload)) {
    throw new OnboardingFetchError(response.status);
  }
  return payload;
}

/** The first diagnosis report exists once step 2 (60 days + full diagnosis) is done. */
export function onboardingReportReady(status: OnboardingStatus): boolean {
  return status.steps.some((step) => step.key === "backfill_diagnosis" && step.status === "done");
}
