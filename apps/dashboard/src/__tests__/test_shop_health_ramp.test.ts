/**
 * Shop Health SPS/AHR — 5-segment pink ramp + threshold ticks (P1.8-10)
 */
import {
  AHR_SCALE_MAX,
  SPS_SCALE_MAX,
  ahrRampColor,
  formatSpsThresholdLabel,
  healthRampColor,
  spsRampColor,
} from "@/lib/metrics/shop-health-metrics";

describe("shop-health ramp colors", () => {
  it("maps SPS scores to 1.0-point bands", () => {
    expect(spsRampColor(0)).toBe("#FCE8EE");
    expect(spsRampColor(0.99)).toBe("#FCE8EE");
    expect(spsRampColor(1)).toBe("#F7CDDD");
    expect(spsRampColor(1.99)).toBe("#F7CDDD");
    expect(spsRampColor(2)).toBe("#F2B2CC");
    expect(spsRampColor(2.99)).toBe("#F2B2CC");
    expect(spsRampColor(3)).toBe("#EE98BB");
    expect(spsRampColor(3.99)).toBe("#EE98BB");
    expect(spsRampColor(4)).toBe("#E97DAA");
    expect(spsRampColor(5)).toBe("#E97DAA");
  });

  it("maps AHR scores to 200-point bands with default gate at 200", () => {
    expect(ahrRampColor(0)).toBe("#FCE8EE");
    expect(ahrRampColor(199)).toBe("#FCE8EE");
    expect(ahrRampColor(200)).toBe("#F7CDDD");
    expect(ahrRampColor(399)).toBe("#F7CDDD");
    expect(ahrRampColor(400)).toBe("#F2B2CC");
    expect(ahrRampColor(599)).toBe("#F2B2CC");
    expect(ahrRampColor(600)).toBe("#EE98BB");
    expect(ahrRampColor(799)).toBe("#EE98BB");
    expect(ahrRampColor(800)).toBe("#E97DAA");
    expect(ahrRampColor(1000)).toBe("#E97DAA");
  });

  it("routes healthRampColor through scale-specific bands", () => {
    expect(healthRampColor(2.8, SPS_SCALE_MAX)).toBe("#F2B2CC");
    expect(healthRampColor(250, AHR_SCALE_MAX)).toBe("#F7CDDD");
  });

  it("labels SPS threshold ticks for business gates", () => {
    expect(formatSpsThresholdLabel(3.5)).toBe("Mega-campaign");
    expect(formatSpsThresholdLabel(4.5)).toBe("Star Shop");
  });
});
