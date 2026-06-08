/** Deterministic string hash for stable draft IDs and timestamps (no crypto RNG). */
export function stableHash(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash * 33) ^ input.charCodeAt(i);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function stableHashHex(input: string, length: number): string {
  let seed = input;
  let hex = "";
  while (hex.length < length) {
    hex += stableHash(seed);
    seed = `${seed}:${hex.length}`;
  }
  return hex.slice(0, length);
}

export function deterministicDraftId(contextKey: string): string {
  const hex = stableHashHex(contextKey, 32);
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    "4" + hex.slice(13, 16),
    "8" + hex.slice(17, 20),
    hex.slice(20, 32),
  ].join("-");
}

export function deterministicTimestamp(contextKey: string): string {
  const hex = stableHash(contextKey);
  const dayOffset = parseInt(hex.slice(0, 2), 16) % 28;
  const hour = parseInt(hex.slice(2, 4), 16) % 24;
  const minute = parseInt(hex.slice(4, 6), 16) % 60;
  const day = String(dayOffset + 1).padStart(2, "0");
  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  return `2026-06-${day}T${hh}:${mm}:00.000Z`;
}
