"use client";

import { useEffect, useMemo, useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import type { ShopProfileType } from "@/lib/mock-data/operations/schemas";
import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";
import {
  REPORT_DOMAIN_IDS,
  buildAllDomainReportSummaries,
  resolveDefaultReportDomain,
  type ReportDomainId,
} from "@/lib/operations/todays-report";

import { TodaysReportDomainCard } from "./TodaysReportDomainCard";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

export function TodaysReportPanel({
  model,
  profile,
  recommendations = [],
  highlightDomain = null,
  highlightedMetricKey = null,
}: {
  model: UnifiedOperationalDataModel;
  profile: ShopProfileType;
  recommendations?: WorkflowRecommendation[];
  highlightDomain?: ReportDomainId | null;
  highlightedMetricKey?: string | null;
}) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const summaries = useMemo(() => buildAllDomainReportSummaries(model), [model]);
  const [activeDomain, setActiveDomain] = useState<ReportDomainId>(() =>
    highlightDomain ?? resolveDefaultReportDomain(profile),
  );

  useEffect(() => {
    if (highlightDomain && highlightDomain !== activeDomain) {
      setActiveDomain(highlightDomain);
    }
  }, [activeDomain, highlightDomain]);

  const activeSummary = summaries.find((summary) => summary.domainId === activeDomain)!;

  return (
    <section className="space-y-3" data-testid="todays-report-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold" style={{ color: "var(--foreground)" }}>
          Báo cáo hôm nay
        </h2>
      </div>

      <div
        className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1"
        role="tablist"
        aria-label="Lĩnh vực báo cáo hôm nay"
        data-testid="todays-report-switcher"
      >
        {REPORT_DOMAIN_IDS.map((domainId) => {
          const summary = summaries.find((item) => item.domainId === domainId)!;
          const isActive = activeDomain === domainId;

          return (
            <button
              key={domainId}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`shrink-0 rounded-full px-3 py-2 text-xs font-semibold sm:text-sm${
                isActive ? " btn-primary" : " btn-secondary"
              }`}
              data-testid={`todays-report-tab-${domainId}`}
              onClick={() => setActiveDomain(domainId)}
            >
              {summary.shortLabel}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" data-testid={`todays-report-panel-${activeDomain}`}>
        <TodaysReportDomainCard
          key={activeDomain}
          summary={activeSummary}
          animate={!prefersReducedMotion}
          recommendations={recommendations}
          highlightedMetricKey={
            activeDomain === highlightDomain ? highlightedMetricKey : null
          }
        />
      </div>
    </section>
  );
}
