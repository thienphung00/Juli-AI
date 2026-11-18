// The minimum Connector version Juli asks for (426 `connector_upgrade_required`): kept in storage so
// the popup can say "Cập nhật Juli Connector lên <v>" until this install is at that version.

export const UPGRADE_KEY = "upgradeRequired";

function parts(version: string): number[] | null {
  const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(version.trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** True when `version` is a dotted version below `minimum` (anything unparseable is not "too old"). */
export function isBelow(version: string, minimum: string): boolean {
  const a = parts(version);
  const b = parts(minimum);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return (a[i] ?? 0) < (b[i] ?? 0);
  return false;
}

interface Store {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

/** Remember Juli's minimum (only when this install really is below it). */
export async function noteUpgradeRequired(storage: Store, version: string, minimum: string): Promise<void> {
  if (isBelow(version, minimum)) await storage.set({ [UPGRADE_KEY]: minimum });
}

/** The minimum still to reach, or null (the key is dropped once this install has caught up). */
export async function pendingUpgrade(storage: Store, version: string): Promise<string | null> {
  const minimum = (await storage.get([UPGRADE_KEY]))[UPGRADE_KEY];
  if (typeof minimum !== "string") return null;
  if (isBelow(version, minimum)) return minimum;
  await storage.set({ [UPGRADE_KEY]: null });
  return null;
}
