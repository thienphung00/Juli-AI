"use client";

import type { OnboardingStatus, OnboardingStep, fetchOnboardingStatus } from "../../lib/onboarding/api-client";
import { useOnboardingStatus } from "../../lib/onboarding/use-onboarding-status";

/**
 * P17 (D26): while Juli reads a newly connected shop, Trang chủ, Quyết định
 * and Phân tích show "Juli đang đọc dữ liệu shop · bước N/3" with the three
 * steps (quick scan, 60-day backfill + diagnosis, background history). Once
 * only the history remains it becomes a quiet note ("Đang tải lịch sử · còn N
 * ngày"); when everything is done, or the status cannot be read, nothing.
 * Signed-in with a shop only — the sample doors never mount it.
 */

const STEP_STATUS_LABEL: Readonly<Record<string, string>> = {
  pending: "Chờ",
  running: "Đang chạy",
  done: "Xong",
  skipped: "Bỏ qua",
  failed: "Lỗi",
};

export function etaText(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `khoảng ${minutes} phút`;
}

function stepMeta(step: OnboardingStep): string {
  const parts: string[] = [STEP_STATUS_LABEL[step.status] ?? step.status];
  if (step.status === "running" && typeof step.percent === "number" && Number.isFinite(step.percent)) {
    parts.push(`${Math.round(step.percent)} %`);
  }
  const eta = step.status === "running" ? etaText(step.eta_seconds) : null;
  if (eta) parts.push(eta);
  return parts.join(" · ");
}

export function OnboardingStrip({ status }: { readonly status: OnboardingStatus | null }) {
  if (!status || !status.label) return null;
  if (!status.active) {
    if (status.current_step !== 3) return null;
    return (
      <p className="onboarding-note" data-testid="onboarding-note" role="status">
        {status.label}
      </p>
    );
  }
  return (
    <div aria-live="polite" className="onboarding-strip" data-testid="onboarding-strip" role="status">
      <p className="onboarding-strip__label">{status.label}</p>
      <ol className="onboarding-strip__steps">
        {status.steps.map((step, index) => (
          <li
            className={`onboarding-strip__step onboarding-strip__step--${step.status}`}
            data-status={step.status}
            data-testid="onboarding-step"
            key={step.key}
          >
            <span className="onboarding-strip__step-name">
              {index + 1}. {step.label}
            </span>
            <span className="onboarding-strip__step-meta">{stepMeta(step)}</span>
            {step.status === "running" && typeof step.percent === "number" ? (
              <span aria-hidden="true" className="onboarding-strip__bar">
                <span
                  className="onboarding-strip__bar-fill"
                  style={{ width: `${Math.min(100, Math.max(0, step.percent))}%` }}
                />
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** The strip with its own polling (`useOnboardingStatus`), for a signed-in seller with a shop. */
export function ShopOnboardingStrip({
  token,
  shopId,
  onStatus,
  fetchStatus,
}: {
  readonly token: string;
  readonly shopId: string;
  readonly onStatus?: (status: OnboardingStatus) => void;
  readonly fetchStatus?: typeof fetchOnboardingStatus;
}) {
  const status = useOnboardingStatus({ token, shopId, onStatus, fetchStatus });
  return <OnboardingStrip status={status} />;
}
