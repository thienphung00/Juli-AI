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

// ---------------------------------------------------------------------------
// Selector-card preview marks (#885, ADR-060)
//
// A KPI selector card shows a 96×32 preview that is a simplified, low-contrast
// member of the same graph family as its hero (Components/charts.md). Treatment
// decisions, made once here so every preview stays subordinate to the hero:
//
// - Amplitude normalization: line series are min–max scaled into a 26px band
//   (3px padding) so real variation always fills the mark. This — not extra
//   ink — is what separates a preview from a hairline rule at thumbnail size.
// - Marks are thin (1.5px stroke) and carry no axes, gridlines, endpoint
//   marker, label, tooltip, or comparison overlay; the hero keeps all of those.
// - The identity hue is structurally neutral: the preview accepts no trend
//   prop at all (ADR-060 § 5 / #865). Direction lives in the card's delta chip.
// - `bounded-ratio` plots against its fixed bounds (never min–max, so the
//   spatial relation to the target stays honest) and shows the target as a
//   1px dashed reference line; the dash pattern gives the threshold a second
//   line character so the two strokes cannot fuse into one rule at 32px. The
//   status palette touches that line only on a genuine breach (#864).
// - `count` renders zero-baselined 4px-pitched bars, never a continuous line.
// ---------------------------------------------------------------------------

const PREVIEW_AMPLITUDE_PAD = 3;
const PREVIEW_STROKE_WIDTH = 1.5;
const PREVIEW_FILL_OPACITY = 0.14;
const PREVIEW_BAR_OPACITY = 0.7;
const PREVIEW_BAR_GAP = 2;

export type SparklinePreviewForm =
  | "filled-line"
  | "plain-line"
  | "bars"
  | "bounded-ratio";

export interface SparklinePreviewBoundedRatio {
  target: number;
  bounds: { min: number; max: number };
  withinTolerance: boolean;
}

interface MetricSparklinePreviewBaseProps {
  data: readonly number[];
  label: string;
  value: string;
  delta?: string;
  width?: number;
  height?: number;
}

// Discriminated on `form`: a bounded-ratio preview without its target is not a
// smaller version of the chart, it is a different chart — so the payload is
// required at the type level rather than defaulted away at runtime.
export type MetricSparklinePreviewProps = MetricSparklinePreviewBaseProps &
  (
    | { form: Exclude<SparklinePreviewForm, "bounded-ratio"> }
    | { form: "bounded-ratio"; boundedRatio: SparklinePreviewBoundedRatio }
  );

function previewXAt(index: number, count: number, width: number): number {
  if (count <= 1) {
    return width / 2;
  }
  return (index / (count - 1)) * width;
}

function previewYScale(
  min: number,
  max: number,
  height: number,
): (value: number) => number {
  const top = PREVIEW_AMPLITUDE_PAD;
  const bottom = height - PREVIEW_AMPLITUDE_PAD;
  const span = max - min;

  return (value: number) => {
    if (span === 0) {
      return (top + bottom) / 2;
    }
    const clamped = Math.min(Math.max(value, min), max);
    return bottom - ((clamped - min) / span) * (bottom - top);
  };
}

function previewLinePoints(
  data: readonly number[],
  width: number,
  yFor: (value: number) => number,
): string {
  return data
    .map(
      (value, index) =>
        `${previewXAt(index, data.length, width)},${yFor(value)}`,
    )
    .join(" ");
}

function PreviewLineMark({
  data,
  width,
  height,
  filled,
}: {
  data: readonly number[];
  width: number;
  height: number;
  filled: boolean;
}): ReactElement {
  const yFor = previewYScale(Math.min(...data), Math.max(...data), height);
  const points = previewLinePoints(data, width, yFor);
  const neutral = CHART_SERIES_COLORS.neutral;
  const firstX = previewXAt(0, data.length, width);
  const lastX = previewXAt(data.length - 1, data.length, width);

  return (
    <g>
      {filled ? (
        // Solid low-opacity silhouette down to the mark's bottom edge — a
        // gradient vanishes at 32px, a silhouette still reads as an area.
        <path
          d={`M ${firstX},${height} L ${points.replaceAll(" ", " L ")} L ${lastX},${height} Z`}
          data-preview-fill="true"
          fill={neutral}
          fillOpacity={PREVIEW_FILL_OPACITY}
          stroke="none"
        />
      ) : null}
      <polyline
        data-preview-line="true"
        fill="none"
        points={points}
        stroke={neutral}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={PREVIEW_STROKE_WIDTH}
      />
    </g>
  );
}

function PreviewBarsMark({
  data,
  width,
  height,
}: {
  data: readonly number[];
  width: number;
  height: number;
}): ReactElement {
  // Counts anchor to a zero baseline — bars must never be min–max rescaled.
  const maxValue = Math.max(...data, 0);
  const pitch = width / data.length;
  const gap = pitch >= PREVIEW_BAR_GAP * 2 ? PREVIEW_BAR_GAP : 1;
  const barWidth = Math.max(1.5, pitch - gap);
  const neutral = CHART_SERIES_COLORS.neutral;

  return (
    <g>
      {data.map((value, index) => {
        const scaled =
          maxValue > 0
            ? (value / maxValue) * (height - PREVIEW_AMPLITUDE_PAD)
            : 0;
        // A zero-value period keeps a 1px slot so the period stays visible.
        const barHeight = Math.max(scaled, 1);

        return (
          <rect
            data-preview-bar={index}
            fill={neutral}
            height={barHeight}
            key={index}
            opacity={PREVIEW_BAR_OPACITY}
            rx={1}
            ry={1}
            width={barWidth}
            x={index * pitch + (pitch - barWidth) / 2}
            y={height - barHeight}
          />
        );
      })}
    </g>
  );
}

function PreviewBoundedRatioMark({
  data,
  width,
  height,
  boundedRatio,
}: {
  data: readonly number[];
  width: number;
  height: number;
  boundedRatio: SparklinePreviewBoundedRatio;
}): ReactElement {
  const { target, bounds, withinTolerance } = boundedRatio;
  const yFor = previewYScale(bounds.min, bounds.max, height);
  // Status palette is reserved for a genuine breach (#864); otherwise the
  // threshold stays in the muted reference ink.
  const targetStroke = withinTolerance
    ? "var(--juli-muted-foreground)"
    : "var(--juli-destructive)";

  return (
    <g>
      <line
        data-preview-target="true"
        stroke={targetStroke}
        strokeDasharray="3 3"
        strokeWidth={1}
        x1={0}
        x2={width}
        y1={yFor(target)}
        y2={yFor(target)}
      />
      <polyline
        data-preview-line="true"
        fill="none"
        points={previewLinePoints(data, width, yFor)}
        stroke={CHART_SERIES_COLORS.neutral}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={PREVIEW_STROKE_WIDTH}
      />
    </g>
  );
}

// Exhaustive over every preview form — no default branch, so a new form
// cannot silently fall back to a line (same idiom as the hero's switch, #863).
function renderPreviewMark(
  props: MetricSparklinePreviewProps,
  width: number,
  height: number,
): ReactElement {
  switch (props.form) {
    case "filled-line":
    case "plain-line":
      return (
        <PreviewLineMark
          data={props.data}
          filled={props.form === "filled-line"}
          height={height}
          width={width}
        />
      );
    case "bars":
      return <PreviewBarsMark data={props.data} height={height} width={width} />;
    case "bounded-ratio":
      return (
        <PreviewBoundedRatioMark
          boundedRatio={props.boundedRatio}
          data={props.data}
          height={height}
          width={width}
        />
      );
  }
}

export function MetricSparklinePreview(props: MetricSparklinePreviewProps) {
  const { label, value, delta, width = 96, height = 32 } = props;

  return (
    <figure className="juli-chart-sparkline-preview">
      <ChartTextEquivalent delta={delta} label={label} value={value} />
      <svg
        aria-hidden="true"
        className="juli-chart-sparkline-preview__visual"
        data-preview-form={props.form}
        data-testid="metric-sparkline-preview"
        focusable="false"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        width={width}
      >
        {renderPreviewMark(props, width, height)}
      </svg>
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
        {/* Value label only for endpoint */}
        {isEndpoint ? (
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
        ) : null}
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
        {/* Value label only for endpoint */}
        {isEndpoint ? (
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
        ) : null}
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
