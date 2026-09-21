/**
 * A deduplication key shared by the browser and the server copy of one event.
 *
 * TikTok merges a Pixel event and an Events API event into a single conversion
 * when they carry the same event name AND the same `event_id`, and arrive
 * within 48 hours of each other. That is the entire mechanism — without a
 * shared id the two channels double-count, so every `track()` call in this
 * package mints one id and hands the same value to both channels.
 *
 * Uniqueness only has to hold across a 48-hour window within one data source,
 * so the fallback below is sufficient where `randomUUID` is unavailable — it
 * needs a secure context, which an origin served over plain HTTP (a local
 * `next dev` on a LAN address, say) is not. Falling back beats throwing: a
 * missing id does not degrade tracking, it breaks deduplication outright.
 */
export function newEventId(): string {
  const webCrypto: Crypto | undefined = globalThis.crypto;

  if (webCrypto && typeof webCrypto.randomUUID === "function") {
    return webCrypto.randomUUID();
  }

  if (webCrypto && typeof webCrypto.getRandomValues === "function") {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 14)}`;
}
