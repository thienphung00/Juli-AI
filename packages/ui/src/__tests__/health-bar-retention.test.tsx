import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthBar } from "../health-bar";

describe("Issue #867: HealthBar meter primitive retention (P2-CHART-RETIRE)", () => {
  describe("AC3: HealthBar component remains exported and renders", () => {
    it("RED: HealthBar is a defined export from health-bar.tsx", () => {
      // This test ensures the component itself is exported
      expect(typeof HealthBar).toBe("function");
      expect(HealthBar.name).toBe("HealthBar");
    });

    it("RED: HealthBar renders without crashing", () => {
      const { container } = render(
        <HealthBar
          label="Test Meter"
          statusLabel="Healthy"
          value={75}
        />
      );

      // Should render something
      expect(container.firstChild).toBeInTheDocument();
      expect(container.querySelector(".juli-health-bar")).toBeInTheDocument();
    });

    it("MUTATION: Removing the HealthBar component should fail this test", () => {
      // This test is designed to fail if HealthBar is deleted.
      // It serves as a safeguard against the "predictable mistake"
      // mentioned in the spec.

      // The test passes if:
      // 1. HealthBar is a function (the export exists)
      // 2. We can render it
      // 3. It produces DOM output

      const { container } = render(
        <HealthBar
          label="Guard"
          statusLabel="Active"
          value={50}
        />
      );

      // If HealthBar is deleted, the import will fail before this line
      expect(container.querySelector(".juli-health-bar__track")).toBeInTheDocument();
    });

    it("RED: HealthBar renders the five-segment meter structure", () => {
      const { container } = render(
        <HealthBar
          label="Shop Health"
          statusLabel="Good"
          value={60}
        />
      );

      const track = container.querySelector(".juli-health-bar__track");
      expect(track).toBeInTheDocument();

      const segments = track?.querySelectorAll(".juli-health-bar__segment");
      expect(segments?.length).toBe(5);
    });

    it("RED: HealthBar uses semantic role='meter' for accessibility", () => {
      const { getByRole } = render(
        <HealthBar
          label="Accessibility"
          statusLabel="Checked"
          value={80}
        />
      );

      const meter = getByRole("meter");
      expect(meter).toBeInTheDocument();
      expect(meter.getAttribute("aria-valuenow")).toBe("80");
    });
  });
});
