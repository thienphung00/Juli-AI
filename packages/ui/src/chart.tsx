import type { KeyboardEvent, ReactNode, ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";

export type ChartTrend = "positive" | "negative" | "neutral" | "warning";

// Brand pink never appears in a chart (ADR-054) — a non-directional series uses the
// dedicated neutral token, not --juli-primary.
export const CHART_SERIES_COLORS: Record<ChartTrend, string> = {
  positive: "var(--juli-success)",
  negative: "var(--juli-destructive)",
  neutral: "var(--juli-chart-neutral)",
  warning: "var(--juli-warning)",
};

// Shared chart chrome — horizontal gridlines and quiet, tick-only axes so the
// data line stays the loudest element (design.md § Data visualization).
const GRID_STROKE = "var(--juli-border)";
const AXIS_TICK = {
  fill: "var(--juli-muted-foreground)",
  fontSize: 10,
} as const;

const TREND_DIRECTION_LABEL: Record<ChartTrend, string> = {
  positive: "xu hướng tăng",
  negative: "xu hướng giảm",
  neutral: "xu hướng ổn định",
  warning: "xu hướng cảnh báo",
};

/**
 * Props passed by Recharts to a custom dot shape component.
 * Typing this prevents the need for `any` casts and maintains type safety.
 */
interface DotProps {
  cx: number;
  cy: number;
  index: number;
  payload?: unknown;
  fill?: string;
  stroke?: string;
}


export interface ChartTextEquivalentProps {
  label: string;
  value: string;
  delta?: string;
  trend?: ChartTrend;
}

export function ChartTextEquivalent({
  label,
  value,
  delta,
  trend,
}: ChartTextEquivalentProps) {
  const parts = [label, value];

  if (delta) {
    parts.push(delta);
  }

  if (trend) {
    parts.push(TREND_DIRECTION_LABEL[trend]);
  }

  return <p className="juli-sr-only">{parts.join(" — ")}</p>;
}

export interface MetricSparklineProps {
  data: readonly number[];
  trend: ChartTrend;
  label: string;
  value: string;
  delta?: string;
  width?: number;
  height?: number;
}

export function MetricSparkline({
  data,
  trend,
  label,
  value,
  delta,
  width = 120,
  height = 40,
}: MetricSparklineProps) {
  const chartData = data.map((point, index) => ({ index, value: point }));
  const stroke = CHART_SERIES_COLORS[trend];

  return (
    <figure className="juli-chart-sparkline">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <div
        aria-hidden="true"
        className="juli-chart-sparkline__visual"
        data-testid="metric-sparkline-visual"
      >
        <LineChart data={chartData} height={height} width={width}>
          <Line
            dataKey="value"
            dot={false}
            isAnimationActive={false}
            stroke={stroke}
            strokeWidth={2}
            type="monotone"
          />
        </LineChart>
      </div>
    </figure>
  );
}

export interface TrendAreaChartProps {
  data: readonly { label: string; value: number }[];
  trend: ChartTrend;
  label: string;
  value: string;
  delta?: string;
  width?: number;
  height?: number;
}

export function TrendAreaChart({
  data,
  trend,
  label,
  value,
  delta,
  width = 280,
  height = 120,
}: TrendAreaChartProps) {
  const stroke = CHART_SERIES_COLORS[trend];
  const fill = `color-mix(in srgb, ${stroke} 12%, transparent)`;

  // Custom dot component that only renders for the last point
  const CustomEndpointDot = (props: DotProps): ReactElement => {
    const { cx, cy, index } = props;

    // Only render for last point
    if (index !== data.length - 1) {
      return <g />;
    }

    const markerRadius = 5; // 10px diameter
    const ringRadius = markerRadius + 2;

    return (
      <g>
        {/* Outer ring (surface-colored) */}
        <circle
          cx={cx}
          cy={cy}
          r={ringRadius}
          fill="none"
          stroke="var(--juli-surface)"
          strokeWidth={2}
          data-chart-marker-ring="true"
        />
        {/* Inner filled marker */}
        <circle
          cx={cx}
          cy={cy}
          r={markerRadius}
          fill={stroke}
          stroke="none"
          data-chart-marker-endpoint="true"
        />
        {/* Value label */}
        <text
          x={cx + 12}
          y={cy + 4}
          fill="var(--juli-foreground)"
          fontSize="12"
          fontWeight="600"
          textAnchor="start"
          data-chart-endpoint-label="true"
        >
          {value}
        </text>
      </g>
    );
  };

  return (
    <figure className="juli-chart-area">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <div
        aria-hidden="true"
        className="juli-chart-area__visual"
        data-testid="trend-area-chart-visual"
      >
        <AreaChart
          data={[...data]}
          height={height}
          margin={{ top: 4, right: 80, bottom: 0, left: 0 }}
          width={width}
        >
          <CartesianGrid
            stroke={GRID_STROKE}
            strokeDasharray="3 3"
            vertical={false}
          />
          <XAxis
            axisLine={false}
            dataKey="label"
            interval="preserveStartEnd"
            tick={AXIS_TICK}
            tickLine={false}
          />
          <Area
            dataKey="value"
            dot={CustomEndpointDot as any}
            fill={fill}
            isAnimationActive={false}
            stroke={stroke}
            strokeWidth={2}
            type="monotone"
          />
        </AreaChart>
      </div>
    </figure>
  );
}

export interface TrendLineChartProps {
  currentData: readonly { label: string; value: number }[];
  previousData?: readonly { label: string; value: number }[];
  trend: ChartTrend;
  label: string;
  value: string;
  delta?: string;
  width?: number;
  height?: number;
}

export function TrendLineChart({
  currentData,
  previousData,
  trend,
  label,
  value,
  delta,
  width = 280,
  height = 120,
}: TrendLineChartProps) {
  const currentStroke = CHART_SERIES_COLORS[trend];
  const mergedData = currentData.map((point, index) => ({
    label: point.label,
    current: point.value,
    previous: previousData?.[index]?.value,
  }));

  // Custom dot component that only renders for the last point
  const CustomEndpointDot = (props: DotProps): ReactElement => {
    const { cx, cy, index } = props;

    // Only render for last point
    if (index !== mergedData.length - 1) {
      return <g />;
    }

    const markerRadius = 5; // 10px diameter
    const ringRadius = markerRadius + 2;

    return (
      <g>
        {/* Outer ring (surface-colored) */}
        <circle
          cx={cx}
          cy={cy}
          r={ringRadius}
          fill="none"
          stroke="var(--juli-surface)"
          strokeWidth={2}
          data-chart-marker-ring="true"
        />
        {/* Inner filled marker */}
        <circle
          cx={cx}
          cy={cy}
          r={markerRadius}
          fill={currentStroke}
          stroke="none"
          data-chart-marker-endpoint="true"
        />
        {/* Value label */}
        <text
          x={cx + 12}
          y={cy + 4}
          fill="var(--juli-foreground)"
          fontSize="12"
          fontWeight="600"
          textAnchor="start"
          data-chart-endpoint-label="true"
        >
          {value}
        </text>
      </g>
    );
  };

  return (
    <figure className="juli-chart-line">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <div
        aria-hidden="true"
        className="juli-chart-line__visual"
        data-testid="trend-line-chart-visual"
      >
        <LineChart
          data={mergedData}
          height={height}
          margin={{ top: 4, right: 80, bottom: 0, left: 0 }}
          width={width}
        >
          <CartesianGrid
            stroke={GRID_STROKE}
            strokeDasharray="3 3"
            vertical={false}
          />
          <XAxis
            axisLine={false}
            dataKey="label"
            interval="preserveStartEnd"
            tick={AXIS_TICK}
            tickLine={false}
          />
          {previousData ? (
            // Previous-period comparison is non-directional — ADR-054 chart-neutral.
            <Line
              dataKey="previous"
              dot={false}
              isAnimationActive={false}
              stroke="var(--juli-chart-neutral)"
              strokeDasharray="4 4"
              strokeWidth={2}
              type="monotone"
            />
          ) : null}
          <Line
            dataKey="current"
            dot={CustomEndpointDot as any}
            isAnimationActive={false}
            stroke={currentStroke}
            strokeWidth={2}
            type="monotone"
          />
        </LineChart>
      </div>
    </figure>
  );
}

export interface TrendBarsChartProps {
  data: readonly { label: string; value: number }[];
  trend: ChartTrend;
  label: string;
  value: string;
  delta?: string;
  width?: number;
  height?: number;
}

export function TrendBarsChart({
  data,
  trend,
  label,
  value,
  delta,
  width = 280,
  height = 120,
}: TrendBarsChartProps) {
  const stroke = CHART_SERIES_COLORS[trend];

  // Custom shape for bars: 4px rounded ends, anchored to baseline
  const CustomBar = (props: any): ReactElement => {
    const { fill, x, y, width: barWidth, height: barHeight, index } = props;

    if (barWidth === undefined || barHeight === undefined) {
      return <g />;
    }

    const radius = 2; // 4px rounded means 2px radius

    return (
      <g data-chart-bar={index}>
        {/* Rounded rectangle for the bar */}
        <rect
          x={x}
          y={y}
          width={barWidth}
          height={barHeight}
          fill={fill}
          rx={radius}
          ry={radius}
        />
      </g>
    );
  };

  return (
    <figure className="juli-chart-bars">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <div
        aria-hidden="true"
        className="juli-chart-bars__visual"
        data-testid="trend-bars-chart-visual"
      >
        <BarChart
          data={[...data]}
          height={height}
          margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
          width={width}
        >
          <CartesianGrid
            stroke={GRID_STROKE}
            strokeDasharray="3 3"
            vertical={false}
          />
          <XAxis
            axisLine={false}
            dataKey="label"
            interval="preserveStartEnd"
            tick={AXIS_TICK}
            tickLine={false}
          />
          {/* Bars start at zero baseline per ADR-060 */}
          <Bar
            dataKey="value"
            fill={stroke}
            isAnimationActive={false}
            radius={[2, 2, 0, 0]}
            shape={<CustomBar />}
          />
        </BarChart>
      </div>
    </figure>
  );
}

export interface BandedLineChartProps {
  data: readonly { label: string; value: number }[];
  label: string;
  value: string;
  target: number;
  bounds: { min: number; max: number };
  withinTolerance: boolean;
  delta?: string;
  width?: number;
  height?: number;
}

export function BandedLineChart({
  data,
  label,
  value,
  target,
  bounds,
  withinTolerance,
  delta,
  width = 280,
  height = 120,
}: BandedLineChartProps) {
  // Series line uses neutral hue; band color reflects tolerance state
  const seriesStroke = CHART_SERIES_COLORS["neutral"];
  const bandFill = withinTolerance
    ? "var(--juli-muted-foreground)"
    : "var(--juli-destructive)";

  const bandOpacity = withinTolerance ? 0.12 : 0.2;

  // Custom dot component that only renders for the last point
  const CustomEndpointDot = (props: DotProps): ReactElement => {
    const { cx, cy, index } = props;

    if (index !== data.length - 1) {
      return <g />;
    }

    const markerRadius = 5; // 10px diameter
    const ringRadius = markerRadius + 2;

    return (
      <g>
        {/* Outer ring (surface-colored) */}
        <circle
          cx={cx}
          cy={cy}
          r={ringRadius}
          fill="none"
          stroke="var(--juli-surface)"
          strokeWidth={2}
          data-chart-marker-ring="true"
        />
        {/* Inner filled marker */}
        <circle
          cx={cx}
          cy={cy}
          r={markerRadius}
          fill={seriesStroke}
          stroke="none"
          data-chart-marker-endpoint="true"
        />
        {/* Value label */}
        <text
          x={cx + 12}
          y={cy + 4}
          fill="var(--juli-foreground)"
          fontSize="12"
          fontWeight="600"
          textAnchor="start"
          data-chart-endpoint-label="true"
        >
          {value}
        </text>
      </g>
    );
  };

  // Custom component for the target line label
  const TargetLineLabel = (): ReactElement => {
    return (
      <text
        x={10}
        y={-5}
        fill="var(--juli-muted-foreground)"
        fontSize="10"
        textAnchor="start"
        data-chart-target-label="true"
      >
        Mục tiêu: {target}
      </text>
    );
  };

  // Screen reader text equivalent
  const toleranceText = withinTolerance ? "Trong ngưỡng" : "Ngoài ngưỡng";

  // Custom shape component for the tolerance band that includes the data attribute
  const BandShape = (props: any): ReactElement => {
    const { x, y, width: bandWidth, height: bandHeight } = props;
    return (
      <rect
        x={x}
        y={y}
        width={bandWidth}
        height={bandHeight}
        fill={bandFill}
        fillOpacity={withinTolerance ? 0.12 : 0.2}
        stroke="none"
        data-chart-tolerance-band="true"
      />
    );
  };

  return (
    <figure className="juli-chart-banded">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        value={`${value} — Mục tiêu: ${target.toFixed(1)} — ${toleranceText}`}
        trend="neutral"
      />
      <div
        aria-hidden="true"
        className="juli-chart-banded__visual"
        data-testid="banded-line-chart-visual"
      >
        <LineChart
          data={[...data]}
          height={height}
          margin={{ top: 4, right: 80, bottom: 0, left: 0 }}
          width={width}
        >
          <CartesianGrid
            stroke={GRID_STROKE}
            strokeDasharray="3 3"
            vertical={false}
          />
          <XAxis
            axisLine={false}
            dataKey="label"
            interval="preserveStartEnd"
            tick={AXIS_TICK}
            tickLine={false}
          />
          <YAxis
            domain={[bounds.min, bounds.max]}
            data-chart-y-axis="true"
            data-domain-min={bounds.min.toString()}
            data-domain-max={bounds.max.toString()}
          />

          {/* Render a shaded band area for tolerance region using ReferenceArea */}
          <ReferenceArea
            y1={bounds.min}
            y2={bounds.max}
            fill={bandFill}
            stroke="none"
            fillOpacity={withinTolerance ? 0.12 : 0.2}
            shape={<BandShape />}
          />

          {/* Render a ReferenceLine for the target */}
          <ReferenceLine
            y={target}
            stroke="var(--juli-muted-foreground)"
            strokeDasharray="4 4"
            data-chart-target-line="true"
            label={<TargetLineLabel />}
          />

          {/* Series line plotted over the band */}
          <Line
            dataKey="value"
            dot={CustomEndpointDot as any}
            isAnimationActive={false}
            stroke={seriesStroke}
            strokeWidth={2}
            type="monotone"
            data-chart-series-line="true"
          />
        </LineChart>
      </div>
    </figure>
  );
}

export interface ChartExpandableTileProps {
  label: string;
  value: string;
  delta?: string;
  trend?: ChartTrend;
  expanded?: boolean;
  onToggle?: () => void;
  children: ReactNode;
}

function activateChartTile(
  event: KeyboardEvent<HTMLButtonElement>,
  onToggle?: () => void,
) {
  if (!onToggle) {
    return;
  }

  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onToggle();
  }
}

export function ChartExpandableTile({
  label,
  value,
  delta,
  trend,
  expanded = false,
  onToggle,
  children,
}: ChartExpandableTileProps) {
  return (
    <div className="juli-chart-tile">
      <button
        aria-expanded={expanded}
        className="juli-chart-tile__trigger"
        onClick={onToggle}
        onKeyDown={(event) => activateChartTile(event, onToggle)}
        type="button"
      >
        <span className="juli-chart-tile__label">{label}</span>
        <span className="juli-chart-tile__value">{value}</span>
        {delta ? <span className="juli-chart-tile__delta">{delta}</span> : null}
      </button>
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <div
        className="juli-chart-tile__chart"
        hidden={!expanded}
        id={`chart-tile-${label}`}
      >
        {children}
      </div>
    </div>
  );
}
