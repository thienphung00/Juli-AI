export interface ProgressBarProps {
  label: string;
  value: number;
}

export interface RealEstimatedProgressBarProps {
  estimatedValue: number;
  label: string;
  realValue: number;
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

export function ProgressBar({ label, value }: ProgressBarProps) {
  const percent = clampPercent(value);

  return (
    <div className="juli-progress">
      <div className="juli-progress__label">{label}</div>
      <div
        aria-label={label}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percent}
        className="juli-progress__track"
        role="progressbar"
      >
        <div
          className="juli-progress__fill"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

export function RealEstimatedProgressBar({
  estimatedValue,
  label,
  realValue,
}: RealEstimatedProgressBarProps) {
  const realPercent = clampPercent(realValue);
  const totalPercent = clampPercent(realValue + estimatedValue);
  const estimatedPercent = clampPercent(totalPercent - realPercent);

  return (
    <div className="juli-progress juli-progress--real-estimated">
      <div className="juli-progress__label">{label}</div>
      <div
        aria-label={label}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={realPercent}
        className="juli-progress__track"
        role="progressbar"
      >
        <div
          className="juli-progress__fill juli-progress__fill--real"
          style={{ width: `${realPercent}%` }}
        />
        {estimatedPercent > 0 ? (
          <>
            <div
              aria-hidden="true"
              className="juli-progress__marker"
              style={{ left: `${realPercent}%` }}
            />
            <div
              aria-hidden="true"
              className="juli-progress__fill juli-progress__fill--estimated"
              style={{
                left: `${realPercent}%`,
                width: `${estimatedPercent}%`,
              }}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
