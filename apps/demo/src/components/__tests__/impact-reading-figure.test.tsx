import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT,
  IMPACT_PROVENANCE_UNPROVENANCED_TEXT,
} from "../../lib/impact-provenance";
import { ENTRY_MODE_STORAGE_KEY, writeEntryMode } from "../../lib/entry-mode";
import { clearAuthSession, storeAuthSession } from "../../lib/supabase-auth";
import { ImpactReadingFigure } from "../impact-reading-figure";

/**
 * Issue #1958 / ADR-099 decision 2 — the provenance marker on every
 * rendered impact figure. A synthetic reading must be structurally
 * incapable of being mistaken for a measured one:
 *
 * - AC1: `series_source: 'synthetic'` renders a visible marker;
 *        `series_source: 'measured'` renders none.
 * - AC2: the marker follows the READING's own `series_source`, never the
 *        entry mode, a session, or any client-side guess.
 * - AC3: a reading without `series_source` renders as unprovenanced and
 *        is never presented as measured (fail-closed — the view layer
 *        must not reintroduce the default the column refuses).
 * - AC6: no prop or flag suppresses the marker. An optional honesty
 *        marker is not an honesty marker.
 */

const SYNTHETIC_READING = { series_source: "synthetic" } as const;
const MEASURED_READING = { series_source: "measured" } as const;

function renderFigure(reading: { series_source?: unknown }) {
  return render(
    <ImpactReadingFigure
      reading={reading}
      label="Doanh thu"
      value="+12,4%"
    />,
  );
}

afterEach(() => {
  clearAuthSession();
  window.sessionStorage.removeItem(ENTRY_MODE_STORAGE_KEY);
});

describe("AC1 — the marker follows series_source", () => {
  it("a synthetic reading renders the visible ◆ provenance marker", () => {
    renderFigure(SYNTHETIC_READING);

    const marker = screen.getByTestId("impact-provenance-marker");
    expect(marker).toBeVisible();
    expect(marker).toHaveTextContent(IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT);
    expect(screen.getByTestId("impact-reading")).toHaveAttribute(
      "data-provenance",
      "synthetic",
    );
    // The figure itself still renders — synthetic readings are real
    // computations over invented series (ADR-099 decision 1), shown
    // honestly, not hidden.
    expect(screen.getByText("+12,4%")).toBeVisible();
  });

  it("a measured reading renders no marker at all", () => {
    renderFigure(MEASURED_READING);

    expect(
      screen.queryByTestId("impact-provenance-marker"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT, {
        exact: false,
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("impact-reading")).toHaveAttribute(
      "data-provenance",
      "measured",
    );
    expect(screen.getByText("+12,4%")).toBeVisible();
  });
});

describe("AC2 — provenance comes from the reading, never the mode or session", () => {
  it("a signed-in session does not remove the marker from a synthetic reading", () => {
    storeAuthSession({
      accessToken: "test-token",
      refreshToken: null,
      expiresIn: 3600,
      tokenType: "bearer",
    });

    renderFigure(SYNTHETIC_READING);

    expect(screen.getByTestId("impact-provenance-marker")).toBeVisible();
  });

  it("the replay entry mode does not add a marker to a measured reading", () => {
    writeEntryMode("replay");

    renderFigure(MEASURED_READING);

    expect(
      screen.queryByTestId("impact-provenance-marker"),
    ).not.toBeInTheDocument();
  });

  it("structurally: the figure's module graph never reaches the mode/session modules", () => {
    // Same walker discipline as replay-module-graph.test.ts: walk the
    // real import graph from the figure component and fail if it ever
    // comes to include a module that could supply a client-side guess —
    // the entry-mode flag, the demo mock state, the auth session, or the
    // acting-shop store. If this test fails, someone has wired the marker
    // to something other than the reading itself.
    const SRC_ROOT = resolve(__dirname, "../..");
    const RESOLVABLE = [".tsx", ".ts", "/index.tsx", "/index.ts"];

    const resolveImport = (fromFile: string, spec: string): string | null => {
      if (!spec.startsWith(".")) return null;
      const target = resolve(dirname(fromFile), spec);
      for (const ext of RESOLVABLE) {
        const candidate = target.endsWith(ext) ? target : `${target}${ext}`;
        try {
          readFileSync(candidate, "utf8");
          return candidate;
        } catch {
          continue;
        }
      }
      return null;
    };

    const importRe =
      /(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?from\s+)?["']([^"']+)["']/g;
    const visited = new Set<string>();
    const queue = [resolve(SRC_ROOT, "components/impact-reading-figure.tsx")];
    while (queue.length > 0) {
      const file = queue.pop() as string;
      if (visited.has(file)) continue;
      const source = readFileSync(file, "utf8");
      visited.add(file);
      let match: RegExpExecArray | null;
      while ((match = importRe.exec(source)) !== null) {
        const resolved = resolveImport(file, match[1]);
        if (resolved && !visited.has(resolved)) queue.push(resolved);
      }
    }

    expect(visited.size).toBeGreaterThanOrEqual(2); // sanity — the walk ran
    const forbidden = [
      "/lib/entry-mode.",
      "/components/demo-state.",
      "/lib/demo-mode-copy.",
      "/lib/supabase-auth.",
      "/lib/shop-session.",
      "/lib/analytics/api-client.",
      "/lib/agent-event-stream.",
    ];
    const reached = [...visited].filter((file) =>
      forbidden.some((fragment) => file.includes(fragment)),
    );
    expect(reached).toEqual([]);
  });
});

describe("AC3 — absent provenance fails closed", () => {
  it("a reading without series_source renders as unprovenanced, never as measured", () => {
    renderFigure({});

    const figure = screen.getByTestId("impact-reading");
    expect(figure).toHaveAttribute("data-provenance", "unprovenanced");
    expect(
      within(figure).getByText(IMPACT_PROVENANCE_UNPROVENANCED_TEXT),
    ).toBeVisible();
  });

  it("withholds the figure itself — a number without provenance never reads as real", () => {
    renderFigure({});

    // Not merely "measured minus the marker": the digit is withheld
    // entirely, the same digit-free discipline as
    // IMPACT_UNAVAILABLE_TEXT (a placeholder number would be a
    // fabricated reading).
    expect(screen.queryByText("+12,4%")).not.toBeInTheDocument();
  });

  it("an unrecognised series_source value also fails closed", () => {
    renderFigure({ series_source: "seeded" });

    expect(screen.getByTestId("impact-reading")).toHaveAttribute(
      "data-provenance",
      "unprovenanced",
    );
    expect(screen.queryByText("+12,4%")).not.toBeInTheDocument();
  });
});

describe("AC6 — the marker is not suppressible", () => {
  it("suppression-shaped props are inert: the marker still renders", () => {
    // If anyone ever ADDS a prop or flag that honours one of these names,
    // this render starts exercising it and the assertion below goes red.
    // That is the guard: the component's only input for provenance is the
    // reading itself.
    const suppressionAttempt = {
      hideProvenance: true,
      hideMarker: true,
      showMarker: false,
      suppressMarker: true,
      marker: false,
      provenance: "measured",
      seriesSource: "measured",
    } as Record<string, unknown>;

    render(
      <ImpactReadingFigure
        reading={SYNTHETIC_READING}
        label="Doanh thu"
        value="+12,4%"
        {...suppressionAttempt}
      />,
    );

    expect(screen.getByTestId("impact-provenance-marker")).toBeVisible();
  });

  it("the component's source declares no suppression-shaped prop", () => {
    const source = readFileSync(
      join(process.cwd(), "src/components/impact-reading-figure.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(
      /hideProvenance|hideMarker|showMarker|suppressMarker/,
    );
  });
});

describe("AC4 — every string resolves through dictionary.md", () => {
  const dictionary = readFileSync(
    join(process.cwd(), "..", "..", "dictionary.md"),
    "utf8",
  );

  it("keys the synthetic marker with EN, VI, _Avoid_ and Definition", () => {
    expect(dictionary).toContain("**`impact.provenance.synthetic`**");
    expect(dictionary).toContain(IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT);
  });

  it("keys the unprovenanced state with EN, VI, _Avoid_ and Definition", () => {
    expect(dictionary).toContain("**`impact.provenance.unprovenanced`**");
    expect(dictionary).toContain(IMPACT_PROVENANCE_UNPROVENANCED_TEXT);
  });

  it("both entries carry all four governed fields", () => {
    for (const key of [
      "impact.provenance.synthetic",
      "impact.provenance.unprovenanced",
    ]) {
      const start = dictionary.indexOf(`**\`${key}\`**`);
      expect(start).toBeGreaterThan(-1);
      const block = dictionary.slice(start, dictionary.indexOf("\n\n", start));
      expect(block).toMatch(/- EN: /);
      expect(block).toMatch(/- VI: /);
      expect(block).toMatch(/- _Avoid_: /);
      expect(block).toMatch(/- Definition: /);
    }
  });
});
