import type { PredictedOutcome } from "@/lib/api-client";
import { formatVND } from "@/lib/format";

export function PredictedOutcomePanel({
  predicted,
}: {
  predicted: PredictedOutcome;
}) {
  const { low, high } = predicted.gmv_vnd_week;
  const conversionPct = (predicted.conversion_pct * 100).toFixed(1).replace(".", ",");
  const engagementPct = (predicted.engagement_index * 100).toFixed(0);

  return (
    <div
      className="mt-3 rounded-xl p-3 text-sm"
      style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
      data-testid="predicted-outcome-panel"
    >
      <p className="text-xs font-semibold" style={{ color: "var(--muted-foreground)" }}>
        Dự báo kết quả
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-2">
        <div>
          <dt className="text-xs" style={{ color: "var(--muted-foreground)" }}>
            GMV/tuần
          </dt>
          <dd className="font-medium">
            {formatVND(low)} – {formatVND(high)}
          </dd>
        </div>
        <div>
          <dt className="text-xs" style={{ color: "var(--muted-foreground)" }}>
            Chuyển đổi
          </dt>
          <dd className="font-medium">{conversionPct}%</dd>
        </div>
        <div>
          <dt className="text-xs" style={{ color: "var(--muted-foreground)" }}>
            Tương tác
          </dt>
          <dd className="font-medium">{engagementPct}%</dd>
        </div>
      </dl>
      {predicted.risk_factors.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1" data-testid="predicted-risk-chips">
          {predicted.risk_factors.map((risk) => (
            <span
              key={risk}
              className="rounded-full px-2 py-0.5 text-xs font-medium"
              style={{ background: "#f59e0b20", color: "#f59e0b" }}
            >
              {risk}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
