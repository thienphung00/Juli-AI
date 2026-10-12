/**
 * Change strength (D31.7) — mirror of `backend/src/juli_backend/services/change_strength.py`.
 *
 * A change between two window means is compared with the COMBINED band of both
 * windows, √(a² + b²) (each the D28.1 window-mean band, ± % of the mean):
 * |change| ≥ 2 × combined → "clear" ("Thay đổi rõ"); ≥ 1 × → "likely" ("Có thể
 * thay đổi"); otherwise, and always for a zero change → "noise" ("Trong dao
 * động"); a missing change or band → null (nothing is shown). Both helpers are
 * tested on `__tests__/fixtures/change-strength-cases.json`.
 */

export type ChangeStrength = "clear" | "likely" | "noise";

export const CHANGE_STRENGTH_LABELS: Readonly<Record<ChangeStrength, string>> = {
  clear: "Thay đổi rõ",
  likely: "Có thể thay đổi",
  noise: "Trong dao động",
};

export const CLEAR_MULT = 2;
export const LIKELY_MULT = 1;

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** √(a² + b²) of two windows' bands (± %); null when either is missing. */
export function combinedBand(bandA: number | null | undefined, bandB: number | null | undefined): number | null {
  const a = finite(bandA);
  const b = finite(bandB);
  if (a === null || b === null) return null;
  return Math.hypot(a, b);
}

export function changeStrength(
  changePct: number | null | undefined,
  bandA: number | null | undefined,
  bandB: number | null | undefined,
): ChangeStrength | null {
  const change = finite(changePct);
  const combined = combinedBand(bandA, bandB);
  if (change === null || combined === null) return null;
  const size = Math.abs(change);
  if (size === 0) return "noise";
  if (size >= CLEAR_MULT * combined) return "clear";
  if (size >= LIKELY_MULT * combined) return "likely";
  return "noise";
}

/** The on-screen words for a strength the backend sent (unknown / null → null). */
export function changeStrengthLabel(strength: string | null | undefined): string | null {
  return strength && strength in CHANGE_STRENGTH_LABELS ? CHANGE_STRENGTH_LABELS[strength as ChangeStrength] : null;
}
