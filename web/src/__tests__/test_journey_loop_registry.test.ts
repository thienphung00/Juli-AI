import { VALIDATED_WORKFLOW_IDS } from "@/lib/mock-data/operations/schemas";
import {
  buildDecisionsHighlightLink,
  buildHomeHighlightLink,
  formatAnticipationImpact,
  getJourneyLink,
  parseDecisionsHighlight,
  parseHomeHighlight,
  resolveHomeHighlight,
} from "@/lib/operations/journey-loop";

describe("operations/journey-loop registry", () => {
  it("defines a non-empty journey link for every ADR-026 workflow_id", () => {
    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      const link = getJourneyLink(workflowId);

      expect(link).not.toBeNull();
      expect(link?.reportDomain.length).toBeGreaterThan(0);
      expect(link?.metricKey.length).toBeGreaterThan(0);
      expect(link?.rewardLabel.length).toBeGreaterThan(0);
      expect(link?.reasonTemplate.length).toBeGreaterThan(0);
      expect(link?.anticipationTemplate.length).toBeGreaterThan(0);
    }
  });

  it("maps growth persona workflows to the PRD Home metric anchors", () => {
    expect(getJourneyLink("product_scaling")).toMatchObject({
      reportDomain: "revenue_growth",
      metricKey: "revenue_7d",
    });
    expect(getJourneyLink("budget_optimization")).toMatchObject({
      reportDomain: "advertising",
      metricKey: "roas",
    });
    expect(getJourneyLink("refund_spike_detection")).toMatchObject({
      reportDomain: "refunds",
      metricKey: "refund_rate_7d",
    });
  });

  it("maps new-shop workflows to the PRD Home metric anchors", () => {
    expect(getJourneyLink("npl")).toMatchObject({
      reportDomain: "product_listings",
      metricKey: "product_count",
    });
    expect(getJourneyLink("minimize_violations")).toMatchObject({
      reportDomain: "revenue_protection",
      metricKey: "violation_count",
    });
  });

  it("builds deep links for Decisions and Home highlight navigation", () => {
    expect(buildDecisionsHighlightLink("product_scaling")).toBe(
      "/decisions?highlight=product_scaling",
    );
    expect(buildHomeHighlightLink({ reportDomain: "revenue_growth", metricKey: "revenue_7d" })).toBe(
      "/?highlight=revenue_growth:revenue_7d",
    );
    expect(resolveHomeHighlight("budget_optimization")).toEqual({
      reportDomain: "advertising",
      metricKey: "roas",
    });
  });

  it("formats anticipation impact copy from the registry template", () => {
    const impact = formatAnticipationImpact("product_scaling");
    expect(impact.length).toBeGreaterThan(0);
    expect(impact).toMatch(/doanh thu/i);
  });

  it("returns null for invalid highlight params without throwing", () => {
    expect(parseDecisionsHighlight(null)).toBeNull();
    expect(parseDecisionsHighlight("")).toBeNull();
    expect(parseDecisionsHighlight("not_a_workflow")).toBeNull();

    expect(parseHomeHighlight(undefined)).toBeNull();
    expect(parseHomeHighlight("")).toBeNull();
    expect(parseHomeHighlight("invalid")).toBeNull();
    expect(parseHomeHighlight("revenue_growth")).toBeNull();
    expect(parseHomeHighlight("unknown_domain:metric")).toBeNull();
  });

  it("parses valid highlight params", () => {
    expect(parseDecisionsHighlight("refund_spike_detection")).toBe("refund_spike_detection");
    expect(parseHomeHighlight("refunds:refund_rate_7d")).toEqual({
      reportDomain: "refunds",
      metricKey: "refund_rate_7d",
    });
  });
});
