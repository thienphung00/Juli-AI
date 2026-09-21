/**
 * User identifiers for TikTok advanced matching, normalised and hashed the one
 * way TikTok accepts.
 *
 * TikTok's rule is narrow and unforgiving: SHA-256 only, lowercase, with
 * leading and trailing whitespace trimmed *before* hashing. A value normalised
 * differently in the browser than on the server hashes to a different digest,
 * which does not fail loudly — it just quietly matches nobody. So normalisation
 * lives here, in one pure function per field, shared by both channels, and is
 * tested directly rather than through either of them.
 */

/** Raw, unhashed identifiers as the application knows them. */
export interface TikTokIdentity {
  email?: string | null;
  /** A stable, non-reversible id for the person — here, the Supabase user id. */
  externalId?: string | null;
}

/** The wire shape: every value a lowercase hex SHA-256 digest. */
export interface TikTokHashedIdentity {
  email?: string;
  external_id?: string;
}

/**
 * Lowercase and trim. Returns null for anything that is not plausibly an
 * address, so a placeholder string ("", "null", a display name) can never be
 * hashed and sent as if it were a real identifier.
 */
export function normalizeEmail(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") {
    return null;
  }

  const normalized = raw.trim().toLowerCase();
  const at = normalized.indexOf("@");

  // An address needs a local part, an "@", and a dot inside the domain.
  if (at < 1 || normalized.indexOf(".", at) < at + 2 || normalized.endsWith(".")) {
    return null;
  }

  return normalized;
}

/**
 * Trim only. An external id is an opaque token from an identity provider, so
 * lowercasing it would destroy information in a case-sensitive id space —
 * TikTok's lowercase rule is about human-entered values like email addresses.
 */
export function normalizeExternalId(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") {
    return null;
  }

  const normalized = raw.trim();
  return normalized.length > 0 ? normalized : null;
}

/**
 * SHA-256 as lowercase hex, via WebCrypto — the one implementation available
 * both in the browser and in the Node runtime the route handlers run on.
 *
 * Returns null rather than throwing where `crypto.subtle` is absent (it needs
 * a secure context, so a plain-HTTP origin has no `subtle`). Advanced matching
 * is an enrichment; losing it must never take the event itself down, and it
 * must never fall back to sending the value unhashed.
 */
export async function sha256Hex(value: string): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;

  if (!subtle) {
    return null;
  }

  const digest = await subtle.digest("SHA-256", new TextEncoder().encode(value));

  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/**
 * Normalise then hash every identifier present. Fields that normalise to null,
 * or that cannot be hashed, are omitted entirely — never sent as empty strings,
 * which TikTok would treat as a supplied-but-unmatchable value.
 */
export async function hashIdentity(
  identity: TikTokIdentity,
): Promise<TikTokHashedIdentity> {
  const hashed: TikTokHashedIdentity = {};

  const email = normalizeEmail(identity.email);
  if (email) {
    const digest = await sha256Hex(email);
    if (digest) {
      hashed.email = digest;
    }
  }

  const externalId = normalizeExternalId(identity.externalId);
  if (externalId) {
    const digest = await sha256Hex(externalId);
    if (digest) {
      hashed.external_id = digest;
    }
  }

  return hashed;
}
