// The origin check for page → content-script messages (pure, unit-tested).

export interface MessageLike {
  source: unknown;
  origin: string;
  data: unknown;
}

const KINDS = new Set(["capture", "sync-result", "backfill-result"]);

/** Only messages this very window posted, from Seller Centre, on our channel. */
export function isPageMessage(
  event: MessageLike,
  self: unknown,
  expectedOrigin: string,
  channel: string,
): boolean {
  if (event.source !== self || event.origin !== expectedOrigin) return false;
  const data = event.data as { channel?: unknown; kind?: unknown } | null;
  return (
    typeof data === "object" &&
    data !== null &&
    data.channel === channel &&
    typeof data.kind === "string" &&
    KINDS.has(data.kind)
  );
}
