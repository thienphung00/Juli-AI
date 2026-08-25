/**
 * Minimal WCAG 2.x relative-luminance / contrast-ratio math (hex + solid
 * rgba only -- every pairing this test file checks resolves to one of
 * those two forms). No new dependency: this is ~30 lines of the published
 * formula (WCAG 2.1 §1.4.3 / §1.4.11), not a library.
 */

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function parseColor(color: string): { r: number; g: number; b: number; a: number } {
  const hexMatch = /^#([0-9a-f]{6})$/i.exec(color.trim());
  if (hexMatch) {
    const hex = hexMatch[1];
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16),
      a: 1,
    };
  }

  const rgbaMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(
    color.trim(),
  );
  if (rgbaMatch) {
    return {
      r: Number(rgbaMatch[1]),
      g: Number(rgbaMatch[2]),
      b: Number(rgbaMatch[3]),
      a: rgbaMatch[4] === undefined ? 1 : Number(rgbaMatch[4]),
    };
  }

  throw new Error(`wcag-contrast: unsupported color format "${color}"`);
}

/** Alpha-composites `fg` over an opaque `bg`, returning a solid hex-ish RGB. */
export function flattenOverBackground(fg: string, bg: string): { r: number; g: number; b: number } {
  const fgColor = parseColor(fg);
  const bgColor = parseColor(bg);
  return {
    r: Math.round(fgColor.a * fgColor.r + (1 - fgColor.a) * bgColor.r),
    g: Math.round(fgColor.a * fgColor.g + (1 - fgColor.a) * bgColor.g),
    b: Math.round(fgColor.a * fgColor.b + (1 - fgColor.a) * bgColor.b),
  };
}

function relativeLuminance({ r, g, b }: { r: number; g: number; b: number }): number {
  const R = srgbToLinear(r);
  const G = srgbToLinear(g);
  const B = srgbToLinear(b);
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

/**
 * WCAG contrast ratio between two opaque colors (hex or solid rgb/rgba --
 * an rgba input is treated as already-opaque at its own channel values,
 * i.e. callers must flatten translucent colors with `flattenOverBackground`
 * first if the alpha matters).
 */
export function contrastRatio(colorA: string, colorB: string): number {
  const lumA = relativeLuminance(parseColor(colorA));
  const lumB = relativeLuminance(parseColor(colorB));
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

/** WCAG AA normal-text minimum (1.4.3). */
export const WCAG_AA_TEXT_MIN = 4.5;

/** WCAG AA minimum for non-text UI components / focus indicators (1.4.11). */
export const WCAG_AA_UI_MIN = 3.0;
