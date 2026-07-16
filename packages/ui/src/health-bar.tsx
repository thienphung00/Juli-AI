export interface HealthBarProps {
  atRiskThreshold?: number;
  label: string;
  statusLabel: string;
  value: number;
}

const SEGMENT_COUNT = 5;

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function filledSegmentCount(value: number): number {
  if (value <= 0) {
    return 0;
  }

  return Math.min(SEGMENT_COUNT, Math.ceil(value / (100 / SEGMENT_COUNT)));
}

export function HealthBar({
  atRiskThreshold = 40,
  label,
  statusLabel,
  value,
}: HealthBarProps) {
  const percent = clampPercent(value);
  const filled = filledSegmentCount(percent);
  const isAtRisk = percent < atRiskThreshold;

  return (
    <div className="juli-health-bar">
      <div className="juli-health-bar__header">
        <span className="juli-health-bar__label">{label}</span>
        <span className="juli-health-bar__status">{statusLabel}</span>
      </div>
      <div
        aria-label={`${label}: ${statusLabel}`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percent}
        className="juli-health-bar__track"
        role="meter"
      >
        {Array.from({ length: SEGMENT_COUNT }, (_, index) => {
          const segmentNumber = index + 1;
          const isFilled = segmentNumber <= filled;
          const segmentTone = isAtRisk && isFilled ? "risk" : "healthy";

          return (
            <div
              className={[
                "juli-health-bar__segment",
                isFilled ? "juli-health-bar__segment--filled" : "",
                isFilled ? `juli-health-bar__segment--${segmentTone}` : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={segmentNumber}
            />
          );
        })}
        <div
          aria-hidden="true"
          className="juli-health-bar__tick"
          style={{ left: `${atRiskThreshold}%` }}
        />
      </div>
    </div>
  );
}
