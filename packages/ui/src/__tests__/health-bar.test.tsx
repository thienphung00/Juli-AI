import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthBar } from "../health-bar";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("HealthBar", () => {
  it("renders five segments with a Vietnamese status label", () => {
    render(
      <HealthBar
        label="Sức khỏe cửa hàng"
        statusLabel="Ổn định"
        value={80}
      />,
    );

    expect(screen.getByText("Sức khỏe cửa hàng")).toBeInTheDocument();
    expect(screen.getByText("Ổn định")).toBeInTheDocument();

    const meter = screen.getByRole("meter", { name: "Sức khỏe cửa hàng: Ổn định" });

    expect(meter.querySelectorAll(".juli-health-bar__segment")).toHaveLength(5);
    expect(meter.querySelectorAll(".juli-health-bar__segment--filled")).toHaveLength(
      4,
    );
  });

  it("applies risk tinting below the at-risk threshold", () => {
    render(
      <HealthBar
        atRiskThreshold={40}
        label="AHR"
        statusLabel="Cần chú ý"
        value={20}
      />,
    );

    const meter = screen.getByRole("meter", { name: "AHR: Cần chú ý" });

    expect(
      meter.querySelector(".juli-health-bar__segment--risk"),
    ).toBeInTheDocument();
    expect(meter.querySelector(".juli-health-bar__tick")).toBeInTheDocument();
  });

  it("uses theme tokens for the pink ramp and threshold ticks", () => {
    expect(styles).toContain(".juli-health-bar__segment--healthy");
    expect(styles).toContain("var(--juli-primary-soft)");
    expect(styles).toContain("var(--juli-warning)");
    expect(styles).toContain(".juli-health-bar__tick");
  });
});
