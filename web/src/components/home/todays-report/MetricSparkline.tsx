"use client";

import { Line, LineChart } from "recharts";

const CHART_WIDTH = 120;
const CHART_HEIGHT = 40;

export function MetricSparkline({
  series,
  color,
  domainId,
  metricKey,
  animate,
}: {
  series: number[];
  color: string;
  domainId: string;
  metricKey: string;
  animate: boolean;
}) {
  const data = series.map((value, index) => ({ index, value }));

  return (
    <div
      className="shrink-0"
      data-testid={`report-metric-sparkline-${domainId}-${metricKey}`}
      data-animate={animate ? "true" : "false"}
      style={{ width: CHART_WIDTH, height: CHART_HEIGHT }}
      aria-hidden="true"
    >
      <LineChart width={CHART_WIDTH} height={CHART_HEIGHT} data={data}>
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={animate}
        />
      </LineChart>
    </div>
  );
}
