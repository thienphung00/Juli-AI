/**
 * Impact-reading provenance — issue #1958, ADR-099 decision 2.
 *
 * `impact_readings.series_source` is a `measured | synthetic` enum,
 * NOT NULL, **with no default**: a writer that forgets to declare
 * provenance fails instead of silently recording `measured`. This module
 * is the view layer's mirror of that discipline. It resolves provenance
 * from the READING ITSELF — never from the entry mode, a replay flag, an
 * auth session, or any other client-side guess (AC2: a signed-in seller
 * looking at genuinely synthetic data must still see the marker).
 *
 * Fail-closed (AC3): anything other than the two exact enum strings —
 * an absent key, null, a wrong-cased value, an unknown member, a
 * non-string — resolves to `unprovenanced`. Do not "fix" a reading here;
 * the column deliberately refuses a default and so does this resolver.
 */

/** The two provenances ADR-099's column can actually carry. */
type ImpactSeriesSource = "measured" | "synthetic";

/**
 * What the view layer renders: the column's two members, plus the
 * fail-closed state for a reading that arrived without one.
 */
type ImpactProvenance = ImpactSeriesSource | "unprovenanced";

/**
 * The minimal shape a rendered reading must expose. `unknown` on purpose:
 * this module validates the value rather than trusting a caller's cast.
 */
export interface ProvenancedReading {
  series_source?: unknown;
}

/**
 * Marker text for a synthetic reading — dictionary.md
 * `impact.provenance.synthetic`. Rendered with a leading ◆ glyph
 * (decorative, aria-hidden) by `ImpactReadingFigure`.
 */
export const IMPACT_PROVENANCE_SYNTHETIC_MARKER_TEXT = "Số liệu minh hoạ";

/**
 * Visible copy for the fail-closed state — dictionary.md
 * `impact.provenance.unprovenanced`. Deliberately digit-free: the figure
 * itself is withheld, because a number whose provenance was never
 * declared must not read as real (the same discipline as
 * `IMPACT_UNAVAILABLE_TEXT` in `impact-block-shell.tsx`).
 */
export const IMPACT_PROVENANCE_UNPROVENANCED_TEXT =
  "Chưa rõ nguồn số liệu — không hiển thị như số đo thực";

/**
 * Resolve a reading's provenance from its own `series_source`, exactly.
 *
 * Only the two exact enum strings resolve to a named provenance;
 * everything else fails closed to `unprovenanced`. Case-normalising,
 * trimming, or defaulting here would reintroduce in the view layer the
 * default ADR-099 decision 2 deliberately refused at the column.
 */
export function resolveImpactProvenance(
  reading: ProvenancedReading | null | undefined,
): ImpactProvenance {
  const source = reading?.series_source;

  if (source === "measured" || source === "synthetic") {
    return source;
  }

  return "unprovenanced";
}
