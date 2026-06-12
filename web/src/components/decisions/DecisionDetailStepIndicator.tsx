"use client";

import {
  DECISION_DETAIL_STEP_LABELS,
  DECISION_DETAIL_STEPS,
  type DecisionDetailStep,
} from "@/lib/decisions/detail-steps";

export function DecisionDetailStepIndicator({ currentStep }: { currentStep: DecisionDetailStep }) {
  const currentIndex = DECISION_DETAIL_STEPS.indexOf(currentStep);

  return (
    <>
      <ol
        className="flex items-center justify-between gap-1 sm:hidden"
        data-testid="decision-detail-step-indicator"
        aria-label="Tiến trình quyết định"
      >
        {DECISION_DETAIL_STEPS.map((step, index) => (
          <li
            key={step}
            className="flex flex-1 flex-col items-center gap-1"
            data-testid={`decision-detail-step-indicator-${step}`}
            aria-current={step === currentStep ? "step" : undefined}
          >
            <span
              className="flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              title={DECISION_DETAIL_STEP_LABELS[step]}
              style={{
                background: index <= currentIndex ? "var(--primary)" : "var(--muted)",
                color: index <= currentIndex ? "#fff" : "var(--muted-foreground)",
                outlineColor: "var(--primary)",
              }}
            >
              {index + 1}
            </span>
          </li>
        ))}
      </ol>

      <ol
        className="hidden gap-1 sm:flex"
        aria-label="Tiến trình quyết định"
        data-testid="decision-detail-step-indicator-labels"
      >
        {DECISION_DETAIL_STEPS.map((step, index) => (
          <li
            key={step}
            className="flex-1"
            aria-current={step === currentStep ? "step" : undefined}
          >
            <span
              className="block rounded-lg px-2 py-1.5 text-center text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{
                background:
                  index <= currentIndex
                    ? "color-mix(in srgb, var(--primary) 12%, transparent)"
                    : "var(--muted)",
                color: index <= currentIndex ? "var(--primary)" : "var(--muted-foreground)",
                outlineColor: "var(--primary)",
              }}
            >
              {DECISION_DETAIL_STEP_LABELS[step]}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
