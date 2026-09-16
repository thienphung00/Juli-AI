import { describe, expect, it } from "vitest";

import {
  IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT,
  IMPACT_PROVENANCE_UNPROVENANCED_TEXT,
  resolveImpactProvenance,
} from "../impact-provenance";

/**
 * Issue #1958 / ADR-099 decision 2 — the pure resolver behind the
 * provenance marker. `impact_readings.series_source` is a NOT NULL enum
 * with NO default precisely so a writer that forgets provenance fails
 * instead of silently recording `measured`. This resolver mirrors that
 * discipline in the view layer: only the two exact enum strings resolve
 * to a named provenance; everything else — absent, null, wrong case, a
 * non-string — fails closed to `unprovenanced`.
 */
describe("resolveImpactProvenance — exact enum match only (AC2/AC3)", () => {
  it("resolves 'synthetic' from the reading's own series_source", () => {
    expect(resolveImpactProvenance({ series_source: "synthetic" })).toBe(
      "synthetic",
    );
  });

  it("resolves 'measured' from the reading's own series_source", () => {
    expect(resolveImpactProvenance({ series_source: "measured" })).toBe(
      "measured",
    );
  });

  it.each([
    ["absent key", {}],
    ["undefined value", { series_source: undefined }],
    ["null value", { series_source: null }],
    ["empty string", { series_source: "" }],
    ["wrong case MEASURED", { series_source: "MEASURED" }],
    ["wrong case Synthetic", { series_source: "Synthetic" }],
    ["padded value", { series_source: " measured " }],
    ["unknown enum member", { series_source: "seeded" }],
    ["non-string value", { series_source: 1 }],
    ["boolean value", { series_source: true }],
  ])(
    "fails closed to 'unprovenanced' on %s — never defaulting to measured",
    (_label, reading) => {
      expect(
        resolveImpactProvenance(reading as { series_source?: unknown }),
      ).toBe("unprovenanced");
    },
  );

  it("fails closed on a missing reading object itself", () => {
    expect(resolveImpactProvenance(null)).toBe("unprovenanced");
    expect(resolveImpactProvenance(undefined)).toBe("unprovenanced");
  });
});

describe("marker copy constants stay in seller Vietnamese", () => {
  it("carries the marker text the issue specifies verbatim", () => {
    expect(IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT).toBe("Số liệu minh hoạ");
  });

  it("carries digit-free unprovenanced copy — never a fabricated figure", () => {
    expect(IMPACT_PROVENANCE_UNPROVENANCED_TEXT).toBe(
      "Chưa rõ nguồn số liệu — không hiển thị như số đo thực",
    );
    expect(IMPACT_PROVENANCE_UNPROVENANCED_TEXT).not.toMatch(/\d/);
  });
});
