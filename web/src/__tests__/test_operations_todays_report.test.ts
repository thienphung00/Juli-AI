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
  it("builds all five domain summaries from unified operational fixtures", () => {
    for (const model of loadAllOperationalFixtures()) {
      const summaries = buildAllDomainReportSummaries(model);
      expect(summaries).toHaveLength(5);
      expect(summaries.map((summary) => summary.domainId)).toEqual([...REPORT_DOMAIN_IDS]);
    }
  });

  it("includes status, trend, and at least one metric for non-empty domains", () => {
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
        }
      }
    }
  });

  it("marks advertising empty for NEW_SHOP fixture with no campaigns", () => {
    const newShopModel = loadOperationalModelForPersona("new");
    const advertising = buildDomainReportSummary("advertising", newShopModel);

    expect(advertising.isEmpty).toBe(true);
    expect(advertising.statusLabel).toMatch(/Chưa có dữ liệu/);
  });

  it("defaults NEW_SHOP to product listings and MID_LARGE to revenue growth", () => {
    expect(resolveDefaultReportDomain("NEW_SHOP")).toBe("product_listings");
    expect(resolveDefaultReportDomain("MID_LARGE_SHOP")).toBe("revenue_growth");
  });
});
