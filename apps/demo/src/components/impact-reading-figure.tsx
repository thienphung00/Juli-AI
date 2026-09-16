import {
  IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT,
  IMPACT_PROVENANCE_UNPROVENANCED_TEXT,
  resolveImpactProvenance,
  type ProvenancedReading,
} from "../lib/impact-provenance";

/**
 * The one way an impact figure renders in the demo — issue #1958,
 * ADR-099 decision 2. Any surface showing a number from
 * `impact_readings` renders it through this component, so the number and
 * its provenance are inseparable by construction.
 *
 * Three deliberate properties, each load-bearing:
 *
 * - **Provenance comes from the reading itself** (AC2). This component
 *   reads `reading.series_source` and nothing else — no entry mode, no
 *   session, no demo/replay flag. Its module graph is asserted (in
 *   `impact-reading-figure.test.tsx`) never to reach `entry-mode.ts`,
 *   `demo-state.tsx`, `supabase-auth.ts` or `shop-session.ts`, so a
 *   client-side guess cannot be wired in without a red test.
 *
 * - **No suppression path** (AC6). The props are the reading and its
 *   presentation strings — no prop or flag hides the marker, and no
 *   escape hatch exists "for tests". Tests drive the marker through
 *   `series_source`, the same door production data uses. An optional
 *   honesty marker is not an honesty marker.
 *
 * - **Fail closed** (AC3). A reading that arrives without a valid
 *   `series_source` renders as unprovenanced: the figure is WITHHELD and
 *   visible copy says why. Not "measured minus the marker" — a digit
 *   whose provenance was never declared must never read as real. This
 *   mirrors the column's own no-default discipline.
 */
export interface ImpactReadingFigureProps {
  /** The reading as it arrived — provenance is read from it, verbatim. */
  reading: ProvenancedReading;
  /** Seller-facing metric label, e.g. "Doanh thu". */
  label: string;
  /** The pre-formatted figure, e.g. "+12,4%". */
  value: string;
}

export function ImpactReadingFigure({
  reading,
  label,
  value,
}: ImpactReadingFigureProps) {
  const provenance = resolveImpactProvenance(reading);

  return (
    <div
      className={`impact-reading impact-reading--${provenance}`}
      data-testid="impact-reading"
      data-provenance={provenance}
    >
      <p className="impact-reading__label">{label}</p>
      {provenance === "unprovenanced" ? (
        <p
          className="impact-reading__marker impact-reading__marker--unprovenanced"
          data-testid="impact-provenance-marker"
        >
          {IMPACT_PROVENANCE_UNPROVENANCED_TEXT}
        </p>
      ) : (
        <p className="impact-reading__value">{value}</p>
      )}
      {provenance === "synthetic" ? (
        <p
          className="impact-reading__marker impact-reading__marker--synthetic"
          data-testid="impact-provenance-marker"
        >
          <span aria-hidden="true" className="impact-reading__marker-glyph">
            ◆
          </span>
          {IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT}
        </p>
      ) : null}
    </div>
  );
}
