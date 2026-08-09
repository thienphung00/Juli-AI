import type { KeyboardEvent, ReactNode, ReactElement } from "react";
import { useCallback, useState } from "react";
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

// Density threshold: below ~10 points, no scrub is needed
const SCRUB_DENSITY_THRESHOLD = 10;

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

// ---------------------------------------------------------------------------
// Endpoint label fit (issue #886)
//
// The endpoint label is placed by *measuring first*: estimate the formatted
// value's rendered width, then decide where the text goes. The 80px right
// margin (#862) is kept as-is — it is not widened, because widening it shrinks
// the plot, which is exactly what removing the y-axis reclaimed.
//
// - If the estimated text fits between the endpoint marker and the chart's
//   right edge, it keeps its rightward `start`-anchored placement.
// - If it would clip (e.g. GMV's "420.000.000 ₫"), the label flips to an
//   `end` anchor pinned at the chart's right edge and grows *leftward* into
//   the plot, lifted above the marker so it does not sit on the series
//   stroke (or dropped below when the endpoint is near the top edge). This
//   generalises: an arbitrarily long value still ends at the right edge and
//   extends left over the plot instead of clipping.
// ---------------------------------------------------------------------------

const ENDPOINT_LABEL_FONT_SIZE = 12;
// Average glyph advance for the 12px/600 label. Digits are ~0.6em in the UI
// font; thousands separators and spaces are narrower, "₫" wider. 0.62em/char
// slightly over-estimates real width (~10%), erring toward flipping the label
// inward early rather than ever clipping it.
const ENDPOINT_LABEL_CHAR_WIDTH = ENDPOINT_LABEL_FONT_SIZE * 0.62;
// Gap between the marker center and a start-anchored label (marker ring is 7px).
const ENDPOINT_LABEL_GAP = 12;
// Breathing room kept between the label and the chart's right edge.
const ENDPOINT_LABEL_EDGE_PADDING = 4;

/** Deterministic character-count estimate of the endpoint label's width. */
export function estimateEndpointLabelWidth(value: string): number {
  return Math.ceil(value.length * ENDPOINT_LABEL_CHAR_WIDTH);
}

export interface EndpointLabelLayout {
  x: number;
  y: number;
  textAnchor: "start" | "end";
  /** Estimated rendered width, also authored onto the label element. */
  estimatedWidth: number;
}

/**
 * Decide the endpoint label's position so its rendered *extent* — not just
 * its origin — stays inside the chart width.
 */
export function getEndpointLabelLayout(
  cx: number,
  cy: number,
  value: string,
  chartWidth: number,
): EndpointLabelLayout {
  const estimatedWidth = estimateEndpointLabelWidth(value);
  const rightRoom =
    chartWidth - ENDPOINT_LABEL_EDGE_PADDING - (cx + ENDPOINT_LABEL_GAP);

  if (estimatedWidth <= rightRoom) {
    // Fits in the reserved right margin — keep #862's rightward placement.
    return {
      x: cx + ENDPOINT_LABEL_GAP,
      y: cy + 4,
      textAnchor: "start",
      estimatedWidth,
    };
  }

  // Too wide for the margin: pin to the right edge and grow leftward, above
  // the marker. If the endpoint sits near the top of the chart (its glyphs
  // would poke past y=0), drop below the marker instead.
  const aboveBaseline = cy - ENDPOINT_LABEL_GAP;
  return {
    x: chartWidth - ENDPOINT_LABEL_EDGE_PADDING,
    y:
      aboveBaseline >= ENDPOINT_LABEL_FONT_SIZE
        ? aboveBaseline
        : cy + ENDPOINT_LABEL_GAP + ENDPOINT_LABEL_FONT_SIZE - 4,
    textAnchor: "end",
    estimatedWidth,
  };
}

/**
 * useScrubState manages the selected point index during chart scrubbing.
 * Returns the current selected index or -1 if no scrub is active.
 */
export function useScrubState() {
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);

  return {
    selectedIndex,
    setSelectedIndex,
  };
}

/**
 * ChartScrubController handles pointer events to select data points.
 * Only renders for data with ≥10 points (ADR-060 § 6).
 */
export interface ChartScrubControllerProps {
  dataLength: number;
  onIndexChange?: (index: number) => void;
  children: ReactNode;
}

export function ChartScrubController({
  dataLength,
  onIndexChange,
  children,
}: ChartScrubControllerProps) {
  // No scrub for low-density data
  if (dataLength < SCRUB_DENSITY_THRESHOLD) {
    return <>{children}</>;
  }

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!event.isPrimary) return;

      const target = event.currentTarget;
      const rect = target.getBoundingClientRect();
      const relativeX = event.clientX - rect.left;
      const proportion = Math.max(0, Math.min(1, relativeX / rect.width));

      // Select the nearest point based on horizontal position
      const selectedIndex = Math.round(proportion * (dataLength - 1));
      onIndexChange?.(selectedIndex);
    },
    [dataLength, onIndexChange],
  );

  const handlePointerLeave = useCallback(() => {
    // Clear selection on pointer leave
    onIndexChange?.(-1);
  }, [onIndexChange]);

  return (
    <div
      data-chart-scrub-controller
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        cursor: "pointer",
      }}
    >
      {children}
    </div>
  );
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
  onScrubIndexChange?: (index: number, point?: { label: string; value: number }) => void;
}

export function TrendAreaChart({
  data,
  trend,
  label,
  value,
  delta,
  width = 280,
  height = 120,
  onScrubIndexChange,
}: TrendAreaChartProps) {
  const stroke = CHART_SERIES_COLORS[trend];
  const fill = `color-mix(in srgb, ${stroke} 12%, transparent)`;
  const { selectedIndex, setSelectedIndex } = useScrubState();

  const handleIndexChange = useCallback(
    (index: number) => {
      setSelectedIndex(index);
      if (onScrubIndexChange) {
        onScrubIndexChange(index, index >= 0 && index < data.length ? data[index] : undefined);
      }
    },
    [data, onScrubIndexChange, setSelectedIndex],
  );

  // Custom dot component that renders endpoint marker and optional scrub marker
  const CustomEndpointDot = (props: DotProps): ReactElement => {
    const { cx, cy, index } = props;

    // Check if this is the selected scrub point
    const isSelected = selectedIndex === index;
    // Only render endpoint marker for last point unless scrubbing
    const isEndpoint = index === data.length - 1 && selectedIndex === -1;

    if (!isEndpoint && !isSelected) {
      return <g />;
    }

    const isScrubbedPoint = isSelected && selectedIndex !== -1;
    // Scrubbed marker is emphasis through size: 6px radius (endpoint is 5px)
    // Endpoint marker: 5px inner, 7px outer ring
    // Scrubbed marker: 6px inner, 8px outer ring (structurally distinct, no status color)
    const markerRadius = isScrubbedPoint ? 6 : 5;
    const ringRadius = markerRadius + 2;

    return (
      <g data-chart-scrub-marker-selected={isScrubbedPoint || undefined}>
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
        {/* Inner filled marker — series color for both endpoint and scrubbed (ADR-060 § 5) */}
        <circle
          cx={cx}
          cy={cy}
          r={markerRadius}
          fill={stroke}
          stroke="none"
          data-chart-marker-endpoint={isEndpoint || undefined}
        />
        {/* Value label only for endpoint — placed by measured fit (#886) */}
        {isEndpoint
          ? (() => {
              const labelLayout = getEndpointLabelLayout(cx, cy, value, width);
              return (
                <text
                  x={labelLayout.x}
                  y={labelLayout.y}
                  fill="var(--juli-foreground)"
                  fontSize={ENDPOINT_LABEL_FONT_SIZE}
                  fontWeight="600"
                  textAnchor={labelLayout.textAnchor}
                  data-chart-endpoint-label="true"
                  data-chart-endpoint-label-width={labelLayout.estimatedWidth}
                >
                  {value}
                </text>
              );
            })()
          : null}
      </g>
    );
  };

  // Render scrub line at selected point
  const scrubLineX =
    selectedIndex >= 0 && selectedIndex < data.length
      ? ((selectedIndex / (data.length - 1)) * (width - 80)) // Account for right margin
      : null;

  return (
    <figure className="juli-chart-area">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <ChartScrubController
        dataLength={data.length}
        onIndexChange={handleIndexChange}
      >
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
            {scrubLineX !== null && (
              <line
                x1={scrubLineX}
                y1={0}
                x2={scrubLineX}
                y2={height}
                stroke="var(--juli-muted-foreground)"
                strokeWidth={1}
                data-chart-scrub-line="true"
                pointerEvents="none"
              />
            )}
          </AreaChart>
        </div>
      </ChartScrubController>
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
  onScrubIndexChange?: (index: number, point?: { label: string; value: number }) => void;
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
  onScrubIndexChange,
}: TrendLineChartProps) {
  const currentStroke = CHART_SERIES_COLORS[trend];
  const mergedData = currentData.map((point, index) => ({
    label: point.label,
    current: point.value,
    previous: previousData?.[index]?.value,
  }));
  const { selectedIndex, setSelectedIndex } = useScrubState();

  const handleIndexChange = useCallback(
    (index: number) => {
      setSelectedIndex(index);
      if (onScrubIndexChange) {
        onScrubIndexChange(index, index >= 0 && index < currentData.length ? currentData[index] : undefined);
      }
    },
    [currentData, onScrubIndexChange, setSelectedIndex],
  );

  // Custom dot component that renders endpoint marker and optional scrub marker
  const CustomEndpointDot = (props: DotProps): ReactElement => {
    const { cx, cy, index } = props;

    // Check if this is the selected scrub point
    const isSelected = selectedIndex === index;
    // Only render endpoint marker for last point unless scrubbing
    const isEndpoint = index === mergedData.length - 1 && selectedIndex === -1;

    if (!isEndpoint && !isSelected) {
      return <g />;
    }

    const isScrubbedPoint = isSelected && selectedIndex !== -1;
    // Scrubbed marker is emphasis through size: 6px radius (endpoint is 5px)
    // Endpoint marker: 5px inner, 7px outer ring
    // Scrubbed marker: 6px inner, 8px outer ring (structurally distinct, no status color)
    const markerRadius = isScrubbedPoint ? 6 : 5;
    const ringRadius = markerRadius + 2;

    return (
      <g data-chart-scrub-marker-selected={isScrubbedPoint || undefined}>
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
        {/* Inner filled marker — series color for both endpoint and scrubbed (ADR-060 § 5) */}
        <circle
          cx={cx}
          cy={cy}
          r={markerRadius}
          fill={currentStroke}
          stroke="none"
          data-chart-marker-endpoint={isEndpoint || undefined}
        />
        {/* Value label only for endpoint — placed by measured fit (#886) */}
        {isEndpoint
          ? (() => {
              const labelLayout = getEndpointLabelLayout(cx, cy, value, width);
              return (
                <text
                  x={labelLayout.x}
                  y={labelLayout.y}
                  fill="var(--juli-foreground)"
                  fontSize={ENDPOINT_LABEL_FONT_SIZE}
                  fontWeight="600"
                  textAnchor={labelLayout.textAnchor}
                  data-chart-endpoint-label="true"
                  data-chart-endpoint-label-width={labelLayout.estimatedWidth}
                >
                  {value}
                </text>
              );
            })()
          : null}
      </g>
    );
  };

  // Render scrub line at selected point
  const scrubLineX =
    selectedIndex >= 0 && selectedIndex < mergedData.length
      ? ((selectedIndex / (mergedData.length - 1)) * (width - 80)) // Account for right margin
      : null;

  return (
    <figure className="juli-chart-line">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <ChartScrubController
        dataLength={mergedData.length}
        onIndexChange={handleIndexChange}
      >
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
            {scrubLineX !== null && (
              <line
                x1={scrubLineX}
                y1={0}
                x2={scrubLineX}
                y2={height}
                stroke="var(--juli-muted-foreground)"
                strokeWidth={1}
                data-chart-scrub-line="true"
                pointerEvents="none"
              />
            )}
          </LineChart>
        </div>
      </ChartScrubController>
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
  onScrubIndexChange?: (index: number, point?: { label: string; value: number }) => void;
}

export function TrendBarsChart({
  data,
  trend,
  label,
  value,
  delta,
  width = 280,
  height = 120,
  onScrubIndexChange,
}: TrendBarsChartProps) {
  const stroke = CHART_SERIES_COLORS[trend];
  const { selectedIndex, setSelectedIndex } = useScrubState();

  const handleIndexChange = useCallback(
    (index: number) => {
      setSelectedIndex(index);
      if (onScrubIndexChange) {
        onScrubIndexChange(index, index >= 0 && index < data.length ? data[index] : undefined);
      }
    },
    [data, onScrubIndexChange, setSelectedIndex],
  );

  // Custom shape for bars: 4px rounded ends, anchored to baseline
  const CustomBar = (props: any): ReactElement => {
    const { fill, x, y, width: barWidth, height: barHeight, index } = props;

    if (barWidth === undefined || barHeight === undefined) {
      return <g />;
    }

    const radius = 2; // 4px rounded means 2px radius
    const isSelected = selectedIndex === index;
    // Scrubbed bar emphasis through opacity: selected bars are more opaque
    // No status-palette color (ADR-060 § 5)
    const barOpacity = isSelected ? 1.0 : 0.8;

    return (
      <g data-chart-bar={index} data-chart-scrub-marker-selected={isSelected || undefined}>
        {/* Rounded rectangle for the bar — series color, emphasis via opacity */}
        <rect
          x={x}
          y={y}
          width={barWidth}
          height={barHeight}
          fill={fill}
          opacity={barOpacity}
          rx={radius}
          ry={radius}
        />
      </g>
    );
  };

  // Render scrub line at selected point
  const scrubLineX =
    selectedIndex >= 0 && selectedIndex < data.length
      ? ((selectedIndex / (data.length - 1)) * width)
      : null;

  return (
    <figure className="juli-chart-bars">
      <ChartTextEquivalent
        delta={delta}
        label={label}
        trend={trend}
        value={value}
      />
      <ChartScrubController
        dataLength={data.length}
        onIndexChange={handleIndexChange}
      >
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
            {scrubLineX !== null && (
              <line
                x1={scrubLineX}
                y1={0}
                x2={scrubLineX}
                y2={height}
                stroke="var(--juli-muted-foreground)"
                strokeWidth={1}
                data-chart-scrub-line="true"
                pointerEvents="none"
              />
            )}
          </BarChart>
        </div>
      </ChartScrubController>
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
        {/* Value label — placed by measured fit (#886) */}
        {(() => {
          const labelLayout = getEndpointLabelLayout(cx, cy, value, width);
          return (
            <text
              x={labelLayout.x}
              y={labelLayout.y}
              fill="var(--juli-foreground)"
              fontSize={ENDPOINT_LABEL_FONT_SIZE}
              fontWeight="600"
              textAnchor={labelLayout.textAnchor}
              data-chart-endpoint-label="true"
              data-chart-endpoint-label-width={labelLayout.estimatedWidth}
            >
              {value}
            </text>
          );
        })()}
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
