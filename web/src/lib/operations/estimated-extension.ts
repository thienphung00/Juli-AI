/** Percentage width of the estimated upside segment on a Real/Estimated bar (0–100). */
export function computeEstimatedExtensionPct(
  realValue: number,
  estimatedValue: number,
  scaleMax: number,
): number {
  const safeMax = scaleMax > 0 ? scaleMax : 1;
  const realPct = Math.min(100, (realValue / safeMax) * 100);
  const estimatedPct = Math.min(100, (estimatedValue / safeMax) * 100);
  const extensionStartPct = Math.min(realPct, estimatedPct);
  const extensionEndPct = Math.max(realPct, estimatedPct);
  return Math.max(0, extensionEndPct - extensionStartPct);
}

export function hasEstimatedExtension(
  realValue: number,
  estimatedValue: number,
  scaleMax: number,
): boolean {
  return computeEstimatedExtensionPct(realValue, estimatedValue, scaleMax) > 0;
}
