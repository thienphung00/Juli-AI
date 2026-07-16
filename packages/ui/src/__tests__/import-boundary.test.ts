import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import * as uiExports from "../index";

const srcDir = join(process.cwd(), "src");

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = join(directory, entry.name);

    if (entry.isDirectory()) {
      return collectSourceFiles(fullPath);
    }

    if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      return [fullPath];
    }

    return [];
  });
}

describe("packages/ui import boundaries", () => {
  it("never imports from apps/*", () => {
    const importPattern =
      /(?:from\s+|import\s*\(|require\s*\()\s*["']([^"']+)["']/g;

    for (const filePath of collectSourceFiles(srcDir)) {
      if (filePath.includes("__tests__")) {
        continue;
      }

      const source = readFileSync(filePath, "utf8");

      for (const match of source.matchAll(importPattern)) {
        expect(match[1]).not.toMatch(/^apps\//);
        expect(match[1]).not.toMatch(/^@juli\/demo/);
      }
    }
  });

  it("exports the core element families for apps/demo consumption", () => {
    expect(uiExports.Button).toBeTypeOf("function");
    expect(uiExports.Badge).toBeTypeOf("function");
    expect(uiExports.ConfidenceBadge).toBeTypeOf("function");
    expect(uiExports.StatusChip).toBeTypeOf("function");
    expect(uiExports.FilterChip).toBeTypeOf("function");
    expect(uiExports.InputChip).toBeTypeOf("function");
    expect(uiExports.ProgressBar).toBeTypeOf("function");
    expect(uiExports.RealEstimatedProgressBar).toBeTypeOf("function");
    expect(uiExports.HealthBar).toBeTypeOf("function");
    expect(uiExports.DestinationCard).toBeTypeOf("function");
    expect(uiExports.PrimaryNavigation).toBeTypeOf("function");
  });

  it("exports #413 surface compositions for apps/demo consumption", () => {
    expect(uiExports.Card).toBeTypeOf("function");
    expect(uiExports.InteractiveCard).toBeTypeOf("function");
    expect(uiExports.Dialog).toBeTypeOf("function");
    expect(uiExports.ConfirmDialog).toBeTypeOf("function");
    expect(uiExports.Popover).toBeTypeOf("function");
    expect(uiExports.UnavailableKpiPopover).toBeTypeOf("function");
    expect(uiExports.Form).toBeTypeOf("function");
    expect(uiExports.TextField).toBeTypeOf("function");
    expect(uiExports.PasswordField).toBeTypeOf("function");
    expect(uiExports.OtpField).toBeTypeOf("function");
    expect(uiExports.FormSubmit).toBeTypeOf("function");
    expect(uiExports.Table).toBeTypeOf("function");
    expect(uiExports.TableHeaderCell).toBeTypeOf("function");
    expect(uiExports.TableEmpty).toBeTypeOf("function");
  });

  it("exports #414 feedback, navigation, and chart compositions", () => {
    expect(uiExports.Toast).toBeTypeOf("function");
    expect(uiExports.ToastViewport).toBeTypeOf("function");
    expect(uiExports.LoadingIndicator).toBeTypeOf("function");
    expect(uiExports.LoadingSpinner).toBeTypeOf("function");
    expect(uiExports.LoadingSkeleton).toBeTypeOf("function");
    expect(uiExports.isNavTabActive).toBeTypeOf("function");
    expect(uiExports.PageHeader).toBeTypeOf("function");
    expect(uiExports.MetricSparkline).toBeTypeOf("function");
    expect(uiExports.TrendAreaChart).toBeTypeOf("function");
    expect(uiExports.TrendLineChart).toBeTypeOf("function");
    expect(uiExports.ChartExpandableTile).toBeTypeOf("function");
    expect(uiExports.ChartTextEquivalent).toBeTypeOf("function");
    expect(uiExports.CHART_SERIES_COLORS.positive).toBe("var(--juli-success)");
  });
});
