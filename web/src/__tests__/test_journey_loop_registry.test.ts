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
import {
  buildDecisionsHighlightLink as exportedBuildDecisionsHighlightLink,
  getJourneyLink as exportedGetJourneyLink,
} from "@/lib/operations";

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

  it("maps growth persona workflows to the consolidated 3-tab anchors", () => {
    expect(getJourneyLink("budget_optimization")).toMatchObject({
      reportDomain: "revenue_growth",
      metricKey: "roas",
    });
    expect(getJourneyLink("refund_spike_detection")).toMatchObject({
      reportDomain: "inventory_refunds",
      metricKey: "refund_rate_7d",
    });
    expect(getJourneyLink("stockout_prevention")).toMatchObject({
      reportDomain: "inventory_refunds",
      metricKey: "low_stock_rate",
    });
  });

  it("maps new-shop workflows to product and shop health anchors", () => {
    expect(getJourneyLink("npl")).toMatchObject({
      reportDomain: "product_listings",
      metricKey: "product_count",
    });
    expect(getJourneyLink("minimize_violations")).toMatchObject({
      reportDomain: "shop_health",
      metricKey: "ahr",
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
      reportDomain: "revenue_growth",
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

  it("parses valid highlight params including shop_health", () => {
    expect(parseDecisionsHighlight("refund_spike_detection")).toBe("refund_spike_detection");
    expect(parseHomeHighlight("inventory_refunds:refund_rate_7d")).toEqual({
      reportDomain: "inventory_refunds",
      metricKey: "refund_rate_7d",
    });
    expect(parseHomeHighlight("shop_health:ahr")).toEqual({
      reportDomain: "shop_health",
      metricKey: "ahr",
    });
  });

  it("exports journey registry helpers from the operations public interface", () => {
    expect(exportedGetJourneyLink("npl")).not.toBeNull();
    expect(exportedBuildDecisionsHighlightLink("npl")).toBe("/decisions?highlight=npl");
  });
});
