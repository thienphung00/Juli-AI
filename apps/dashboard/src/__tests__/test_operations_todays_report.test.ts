import {
  loadAllOperationalFixtures,
  loadOperationalModelForPersona,
} from "@/lib/mock-data/operations";
import {
  REPORT_DOMAIN_IDS,
  buildAllDomainReportSummaries,
  buildDomainReportSummary,
  resolveDefaultReportDomain,
} from "@/lib/operations/todays-report";

describe("operations/todays-report", () => {
  it("builds all three domain summaries from unified operational fixtures", () => {
    for (const model of loadAllOperationalFixtures()) {
      const summaries = buildAllDomainReportSummaries(model);
      expect(summaries).toHaveLength(3);
      expect(summaries.map((summary) => summary.domainId)).toEqual([...REPORT_DOMAIN_IDS]);
    }
  });

  it("includes Real/Estimated values for non-empty domains", () => {
    const leakageModel = loadOperationalModelForPersona("leakage");

    for (const domainId of REPORT_DOMAIN_IDS) {
      const summary = buildDomainReportSummary(domainId, leakageModel);
      expect(summary.statusLabel.length).toBeGreaterThan(0);
      expect(summary.trendLabel.length).toBeGreaterThan(0);

      if (!summary.isEmpty) {
        expect(summary.metrics.length).toBeGreaterThanOrEqual(1);
        for (const metric of summary.metrics) {
          expect(metric.label.length).toBeGreaterThan(0);
          expect(metric.value.length).toBeGreaterThan(0);
          expect(metric.realValue).toBeGreaterThanOrEqual(0);
          expect(metric.estimatedValue).toBeGreaterThanOrEqual(0);
          expect(metric.scaleMax).toBeGreaterThan(0);
        }
      }
    }
  });

  it("includes ROAS on growth tab when campaigns exist", () => {
    const leakageModel = loadOperationalModelForPersona("leakage");
    const growth = buildDomainReportSummary("revenue_growth", leakageModel);
    expect(growth.metrics.some((metric) => metric.metricKey === "roas")).toBe(true);
  });

  it("defaults NEW_SHOP to product listings and MID_LARGE to revenue growth", () => {
    expect(resolveDefaultReportDomain("NEW_SHOP")).toBe("product_listings");
    expect(resolveDefaultReportDomain("MID_LARGE_SHOP")).toBe("revenue_growth");
  });
});
