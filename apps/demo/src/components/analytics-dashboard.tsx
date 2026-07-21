"use client";

import { FilterChip, LoadingSkeleton, StatusChip } from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import {
  ANALYTICS_RANGE_LABELS,
  DEFAULT_ANALYTICS_RANGE,
  DEFAULT_METRIC_KEY,
  type AnalyticsRange,
  type MetricKey,
  getMainKpiDefinition,
  getSelectorMetricKeys,
  isAvailableMetricKey,
  isValidMetricKey,
} from "../lib/analytics/main-kpis";
import { getKpiSnapshot } from "../lib/analytics/mock-data";
import { useDemoState } from "./demo-state";
import { AnalyticsHeroChart } from "./analytics-charts";
import { AnalyticsKpiCard } from "./analytics-kpi-card";

export type AnalyticsLoadState = "ready" | "loading" | "partial" | "error";

interface AnalyticsDashboardProps {
  metricKey?: string;
  initialLoadState?: AnalyticsLoadState;
}

export function AnalyticsDashboard({
  metricKey: routeMetricKey,
  initialLoadState = "ready",
}: AnalyticsDashboardProps) {
  const router = useRouter();
  const heroHeadingId = useId();
  const heroRef = useRef<HTMLElement>(null);
  const { mutableState, updateMutableState } = useDemoState();
  const [loadState, setLoadState] = useState<AnalyticsLoadState>(initialLoadState);

  const heroMetricKey = isAvailableMetricKey(mutableState.analyticsMetric)
    ? mutableState.analyticsMetric
    : routeMetricKey && isAvailableMetricKey(routeMetricKey)
      ? routeMetricKey
      : DEFAULT_METRIC_KEY;
  const range = mutableState.analyticsRange ?? DEFAULT_ANALYTICS_RANGE;
  const compareEnabled = mutableState.analyticsComparisonEnabled ?? false;
  const invalidDeepLink =
    Boolean(routeMetricKey) &&
    (!isValidMetricKey(routeMetricKey!) ||
      !isAvailableMetricKey(routeMetricKey!));

  useEffect(() => {
    if (routeMetricKey && isAvailableMetricKey(routeMetricKey)) {
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
  }, [routeMetricKey, updateMutableState]);

  useEffect(() => {
    if (initialLoadState !== "loading") {
      return;
    }

    const timer = window.setTimeout(() => setLoadState("ready"), 0);
    return () => window.clearTimeout(timer);
  }, [initialLoadState]);

  const heroDefinition = getMainKpiDefinition(heroMetricKey);
  const snapshot =
    loadState === "error"
      ? null
      : getKpiSnapshot(
          heroMetricKey,
          range,
          loadState === "partial" ? { partial: true } : undefined,
        );
  const selectorKeys = getSelectorMetricKeys(heroMetricKey);

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
          Không có KPI chính nào khớp với đường dẫn{" "}
          <code>{routeMetricKey}</code>. Juli giữ nguyên URL để bạn hiểu lỗi này.
        </p>
        <Link className="analytics-dashboard__recovery" href="/analytics/net-revenue">
          Xem Doanh thu thuần
        </Link>
      </section>
    );
  }

  if (loadState === "loading") {
    return (
      <section
        aria-busy="true"
        aria-labelledby="analytics-title"
        className="analytics-dashboard analytics-dashboard--loading"
      >
        <LoadingSkeleton aria-label="Đang tải KPI chính" className="analytics-skeleton analytics-skeleton--hero" />
        <div className="analytics-kpi-grid">
          {Array.from({ length: 5 }, (_, index) => (
            <LoadingSkeleton
              className="analytics-skeleton analytics-skeleton--card"
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

          {loadState === "error" ? (
            <>
              <p className="analytics-hero__error">
                Chưa thể tải dữ liệu KPI. Bạn vẫn giữ lựa chọn và khoảng thời gian
                hiện tại.
              </p>
              <button
                className="demo-decisions__retry"
                onClick={() => setLoadState("ready")}
                type="button"
              >
                Thử lại
              </button>
            </>
          ) : snapshot ? (
            <>
              <p className="analytics-hero__value">{snapshot.formattedValue}</p>
              <p className="analytics-hero__delta">{snapshot.delta}</p>
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
                  <StatusChip variant="info">Dữ liệu mẫu</StatusChip>
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
          ) : null}
        </div>

        {snapshot ? (
          <div className="analytics-hero__chart">
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

      <div
        aria-label="KPI chính khác"
        className="analytics-kpi-grid"
        role="list"
      >
        {selectorKeys.map((selectorKey) => (
          <div key={selectorKey} role="listitem">
            <AnalyticsKpiCard
              metricKey={selectorKey}
              onSelect={handleSelectMetric}
              range={range}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
