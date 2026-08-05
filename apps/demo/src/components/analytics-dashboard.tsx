"use client";

import { FilterChip, LoadingSkeleton, StatusChip } from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef } from "react";

import {
  ANALYTICS_RANGE_LABELS,
  DEFAULT_ANALYTICS_RANGE,
  DEFAULT_METRIC_KEY,
  MAIN_KPI_ORDER,
  type AnalyticsRange,
  type MetricKey,
  getMainKpiDefinition,
  getSelectorMetricKeys,
  isValidMetricKey,
} from "../lib/analytics/main-kpis";
import {
  useAnalyticsBootstrap,
  useAnalyticsData,
} from "../lib/analytics/analytics-data-context";
import {
  buildLiveKpiSnapshot,
  isSelectableMetricKey,
  listSupplementaryCharts,
} from "../lib/analytics/envelope-mapper";
import { analyticsDeltaClass } from "../lib/analytics/visual-polish";
import { useDemoState } from "./demo-state";
import { AnalyticsHeroChart } from "./analytics-charts";
import { AnalyticsKpiCard } from "./analytics-kpi-card";
import { AnalyticsSupplementarySections } from "./analytics-supplementary-sections";

interface AnalyticsDashboardProps {
  metricKey?: string;
}

export function AnalyticsDashboard({ metricKey: routeMetricKey }: AnalyticsDashboardProps) {
  const router = useRouter();
  const heroHeadingId = useId();
  const heroRef = useRef<HTMLElement>(null);
  const { mutableState, updateMutableState } = useDemoState();
  const { envelope, status, loadAnalytics } = useAnalyticsData();

  const range = mutableState.analyticsRange ?? DEFAULT_ANALYTICS_RANGE;
  useAnalyticsBootstrap(range);

  const heroMetricKey = isSelectableMetricKey(mutableState.analyticsMetric, envelope)
    ? (mutableState.analyticsMetric as MetricKey)
    : routeMetricKey && isSelectableMetricKey(routeMetricKey, envelope)
      ? routeMetricKey
      : isSelectableMetricKey(DEFAULT_METRIC_KEY, envelope)
        ? DEFAULT_METRIC_KEY
        : DEFAULT_METRIC_KEY;

  const compareEnabled = mutableState.analyticsComparisonEnabled ?? false;
  const invalidDeepLink =
    Boolean(routeMetricKey) &&
    (!isValidMetricKey(routeMetricKey!) ||
      (status === "ready" &&
        envelope !== null &&
        !isSelectableMetricKey(routeMetricKey!, envelope)));

  useEffect(() => {
    if (routeMetricKey && isSelectableMetricKey(routeMetricKey, envelope)) {
      updateMutableState((current) => {
        if (current.analyticsMetric === routeMetricKey) {
          return current;
        }

        return {
          ...current,
          analyticsMetric: routeMetricKey,
          analyticsComparisonEnabled: false,
        };
      });
    }
  }, [envelope, routeMetricKey, updateMutableState]);

  const heroDefinition = getMainKpiDefinition(heroMetricKey);
  const snapshot =
    status === "error" || !envelope
      ? null
      : buildLiveKpiSnapshot(envelope, heroMetricKey, range);
  const supplementaryCharts = listSupplementaryCharts(envelope);

  // Build trends for all selector candidates to enable downtrend ordering (ADR-049 Decision 1)
  const allTrends = envelope
    ? MAIN_KPI_ORDER.reduce(
        (acc, key) => {
          const snap = buildLiveKpiSnapshot(envelope, key, range);
          if (snap) {
            acc[key] = snap.trend;
          }
          return acc;
        },
        {} as Partial<Record<MetricKey, "negative" | "neutral" | "positive" | "warning">>,
      )
    : undefined;

  const selectorKeys = getSelectorMetricKeys(heroMetricKey, allTrends);
  const dataModeLabel =
    snapshot?.dataMode === "live" ? "Dữ liệu thực" : "Dữ liệu mẫu";

  const focusHeroHeading = () => {
    heroRef.current
      ?.querySelector<HTMLElement>(`#${heroHeadingId}`)
      ?.focus();
  };

  const handleSelectMetric = (metricKey: MetricKey, keyboardInitiated: boolean) => {
    updateMutableState((current) => ({
      ...current,
      analyticsMetric: metricKey,
      analyticsComparisonEnabled: false,
    }));
    router.push(`/analytics/${metricKey}`);

    if (keyboardInitiated) {
      window.requestAnimationFrame(focusHeroHeading);
    }
  };

  const handleRangeChange = (nextRange: AnalyticsRange) => {
    updateMutableState((current) => ({
      ...current,
      analyticsRange: nextRange,
    }));
  };

  const handleComparisonToggle = () => {
    updateMutableState((current) => ({
      ...current,
      analyticsComparisonEnabled: !current.analyticsComparisonEnabled,
    }));
  };

  if (invalidDeepLink) {
    return (
      <section
        aria-labelledby="analytics-invalid-title"
        className="analytics-dashboard analytics-dashboard--invalid"
      >
        <p className="demo-kicker">Phân tích</p>
        <h1 className="demo-title" id="analytics-invalid-title">
          KPI không tìm thấy
        </h1>
        <p className="demo-intro">
          Không tìm thấy KPI này. Đường dẫn có thể đã đổi hoặc không còn tồn
          tại.
        </p>
        <Link className="analytics-dashboard__recovery" href="/analytics/gmv-tiktok">
          Về GMV (TikTok) <span aria-hidden="true">→</span>
        </Link>
      </section>
    );
  }

  if (status === "loading" || status === "idle") {
    return (
      <section
        aria-busy="true"
        aria-labelledby="analytics-title"
        className="analytics-dashboard analytics-dashboard--loading"
      >
        <LoadingSkeleton
          aria-label="Đang tải KPI chính"
          className="analytics-skeleton analytics-skeleton--hero analytics-skeleton--shimmer"
        />
        <div className="analytics-kpi-grid">
          {Array.from({ length: 4 }, (_, index) => (
            <LoadingSkeleton
              className="analytics-skeleton analytics-skeleton--card analytics-skeleton--shimmer"
              key={index}
            />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="analytics-title"
      className="analytics-dashboard"
      ref={heroRef}
    >
      <p className="demo-kicker">Phân tích</p>
      <h1 className="demo-title" id="analytics-title" tabIndex={-1}>
        {heroDefinition.name}
      </h1>
      <p className="demo-intro">{heroDefinition.description}</p>

      <div
        aria-label="Khoảng thời gian"
        className="analytics-range-controls"
        role="tablist"
      >
        {(Object.keys(ANALYTICS_RANGE_LABELS) as AnalyticsRange[]).map(
          (rangeKey) => (
            <FilterChip
              aria-controls="analytics-hero-panel"
              key={rangeKey}
              onClick={() => handleRangeChange(rangeKey)}
              selected={range === rangeKey}
            >
              {ANALYTICS_RANGE_LABELS[rangeKey]}
            </FilterChip>
          ),
        )}
      </div>

      <article
        aria-labelledby={heroHeadingId}
        className="analytics-hero"
        id="analytics-hero-panel"
      >
        <div className="analytics-hero__summary">
          <h2 className="analytics-hero__title" id={heroHeadingId} tabIndex={-1}>
            <span aria-hidden="true">{heroDefinition.icon}</span>{" "}
            {heroDefinition.name}
          </h2>

          {status === "error" ? (
            <>
              <p className="analytics-hero__error">
                Chưa thể tải dữ liệu KPI. Bạn vẫn giữ lựa chọn và khoảng thời gian
                hiện tại.
              </p>
              <button
                className="demo-decisions__retry"
                onClick={() => void loadAnalytics(range)}
                type="button"
              >
                Thử lại
              </button>
            </>
          ) : snapshot ? (
            <>
              <p className="analytics-hero__lead">Shop của bạn hiện đạt</p>
              <p className="analytics-hero__value">{snapshot.formattedValue}</p>
              <p className={analyticsDeltaClass(snapshot.trend)}>{snapshot.delta}</p>
              <p className="analytics-hero__signal">{snapshot.signal}</p>
              <div className="analytics-hero__provenance">
                <p>
                  <strong>Nguồn dữ liệu:</strong> {snapshot.dataSource}
                </p>
                <p>
                  <strong>Cập nhật lần cuối:</strong> {snapshot.lastUpdated}
                </p>
                <p>
                  <strong>Cửa sổ:</strong> {ANALYTICS_RANGE_LABELS[range]} ·{" "}
                  <StatusChip variant="info">{dataModeLabel}</StatusChip>
                </p>
                {snapshot.partialNote ? (
                  <p className="analytics-hero__partial">{snapshot.partialNote}</p>
                ) : null}
              </div>
              <label className="analytics-hero__comparison">
                <input
                  checked={compareEnabled}
                  onChange={handleComparisonToggle}
                  type="checkbox"
                />
                So sánh kỳ trước
              </label>
              {snapshot.workflowId ? (
                <Link
                  className="analytics-hero__decision-link"
                  href={`/decisions?highlight=${snapshot.workflowId}`}
                >
                  {snapshot.decisionLabel}
                </Link>
              ) : null}
            </>
          ) : (
            <StatusChip variant="neutral">Chưa khả dụng</StatusChip>
          )}
        </div>

        {snapshot ? (
          <div
            className="analytics-hero__chart analytics-chart-chrome"
            data-testid="analytics-chart-chrome"
          >
            <AnalyticsHeroChart
              chartKind={heroDefinition.chartKind}
              comparePreviousPeriod={compareEnabled}
              label={heroDefinition.name}
              snapshot={snapshot}
            />
            {compareEnabled ? (
              <p className="analytics-hero__comparison-legend">
                Đường liền: kỳ hiện tại · Đường nét đứt: kỳ trước
              </p>
            ) : heroDefinition.chartKind === "forecast-line" ? (
              <p className="analytics-hero__comparison-legend">
                Đường liền: thực tế · Đường nét đứt: dự báo
              </p>
            ) : null}
          </div>
        ) : null}
      </article>

      <section
        aria-labelledby="analytics-kpi-section-title"
        className="analytics-kpi-section"
      >
        <h2 className="analytics-kpi-section__title" id="analytics-kpi-section-title">
          KPI chính khác
        </h2>
        <div
          aria-label="KPI chính khác"
          className="analytics-kpi-grid"
          role="list"
        >
          {selectorKeys.map((selectorKey) => (
            <div key={selectorKey} role="listitem">
              <AnalyticsKpiCard
                envelope={envelope}
                metricKey={selectorKey}
                onSelect={handleSelectMetric}
                range={range}
              />
            </div>
          ))}
        </div>
      </section>

      <AnalyticsSupplementarySections charts={supplementaryCharts} />
    </section>
  );
}
