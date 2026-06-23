"use client";

import type { DomainReportSummary, TrendDirection } from "@/lib/operations/todays-report";

function statusStyle(tone: DomainReportSummary["statusTone"]): {
  background: string;
  color: string;
} {
  switch (tone) {
    case "healthy":
      return {
        background: "color-mix(in srgb, var(--success) 12%, transparent)",
        color: "var(--success)",
      };
    case "warning":
      return {
        background: "color-mix(in srgb, var(--warning) 12%, transparent)",
        color: "var(--warning)",
      };
    case "critical":
      return {
        background: "color-mix(in srgb, var(--loss) 12%, transparent)",
        color: "var(--loss)",
      };
    case "empty":
      return {
        background: "color-mix(in srgb, var(--muted-foreground) 10%, transparent)",
        color: "var(--muted-foreground)",
      };
    default:
      return {
        background: "color-mix(in srgb, var(--info) 12%, transparent)",
        color: "var(--info)",
      };
  }
}

function trendIcon(direction: TrendDirection): string {
  if (direction === "up") return "↑";
  if (direction === "down") return "↓";
  return "→";
}

function trendColor(direction: TrendDirection): string {
  if (direction === "up") return "var(--success)";
  if (direction === "down") return "var(--loss)";
  return "var(--muted-foreground)";
}

export function TodaysReportDomainCard({
  summary,
  animate,
}: {
  summary: DomainReportSummary;
  animate: boolean;
}) {
  const badgeStyle = statusStyle(summary.statusTone);

  return (
    <article
      className={`card space-y-4 p-4${animate ? " todays-report-card-animate" : ""}`}
      data-testid={`todays-report-card-${summary.domainId}`}
      data-animate={animate ? "true" : "false"}
      aria-labelledby={`todays-report-title-${summary.domainId}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-muted text-xs font-medium uppercase tracking-wide">
            Báo cáo hôm nay
          </p>
          <h3
            id={`todays-report-title-${summary.domainId}`}
            className="mt-1 text-lg font-bold"
            style={{ color: "var(--foreground)" }}
          >
            {summary.title}
          </h3>
        </div>
        <span
          className="rounded-full px-2.5 py-1 text-xs font-semibold"
          style={badgeStyle}
          data-testid={`todays-report-status-${summary.domainId}`}
        >
          {summary.statusLabel}
        </span>
      </div>

      {summary.isEmpty ? (
        <p
          className="rounded-lg border px-3 py-4 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          data-testid={`todays-report-empty-${summary.domainId}`}
        >
          Chưa có đủ dữ liệu cho lĩnh vực này. Juli sẽ cập nhật khi có thêm hoạt động.
        </p>
      ) : (
        <>
          <p
            className="flex items-center gap-2 text-sm font-medium"
            style={{ color: trendColor(summary.trend) }}
            data-testid={`todays-report-trend-${summary.domainId}`}
          >
            <span aria-hidden="true">{trendIcon(summary.trend)}</span>
            {summary.trendLabel}
          </p>

          <dl className="grid gap-3 sm:grid-cols-2">
            {summary.metrics.map((metric) => (
              <div
                key={metric.label}
                className="rounded-lg border px-3 py-2"
                style={{ borderColor: "var(--border)" }}
                data-testid={`todays-report-metric-${summary.domainId}-${metric.label}`}
              >
                <dt className="text-muted text-xs">{metric.label}</dt>
                <dd className="mt-1 text-base font-semibold tabular-nums">{metric.value}</dd>
                {metric.deltaLabel && (
                  <dd
                    className="mt-0.5 text-xs font-medium tabular-nums"
                    style={{ color: trendColor(metric.direction ?? summary.trend) }}
                  >
                    {metric.deltaLabel}
                  </dd>
                )}
              </div>
            ))}
          </dl>
        </>
      )}
    </article>
  );
}
