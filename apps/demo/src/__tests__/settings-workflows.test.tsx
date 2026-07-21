import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { SettingsView } from "../components/settings-view";
import {
  PRODUCT_DOMAIN_ORDER,
  workflowTemplateFixtures,
} from "../lib/settings/fixtures";

function renderSettings() {
  return render(
    <DemoStateProvider>
      <SettingsView />
    </DemoStateProvider>,
  );
}

describe("Settings — workflow templates", () => {
  it("groups workflow templates by product domain with stable keys and capability badges", () => {
    renderSettings();

    for (const domain of PRODUCT_DOMAIN_ORDER) {
      expect(
        screen.getByRole("region", { name: domain.label }),
      ).toBeInTheDocument();
    }

    const rows = screen.getAllByTestId(/^settings-workflow-row-/);
    expect(rows.map((row) => row.getAttribute("data-workflow-key"))).toEqual(
      workflowTemplateFixtures.map((template) => template.workflowKey),
    );

    for (const template of workflowTemplateFixtures) {
      const row = screen.getByTestId(
        `settings-workflow-row-${template.workflowKey}`,
      );
      expect(within(row).getByText(template.capabilityBadge)).toBeInTheDocument();
      expect(
        within(row).getByText(template.workflowKey, { exact: true }),
      ).toBeInTheDocument();
    }
  });

  it("uses Vietnamese section labels for templates and thresholds", () => {
    renderSettings();

    expect(
      screen.getByRole("tab", { name: "Mẫu quy trình", selected: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Ngưỡng", selected: false }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cài đặt" })).toBeInTheDocument();
  });
});
