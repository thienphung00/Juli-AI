/**
 * The partner trial account record kept beside the auth session (fast track
 * P32-A). Written after a password sign-in confirmed by `GET /v1/reviewer/me`;
 * read by the shell to enter reviewer mode. Presentation only — the server
 * refuses every write of a reviewer whatever this record says. Pure browser
 * storage, no network call site.
 */

import { readPersistent, removePersistent, writePersistent } from "../persistent-storage";

export const REVIEWER_STORAGE_KEY = "juli_demo_reviewer";

export interface ReviewerRecord {
  readonly platform: string;
  readonly expiresAt: string | null;
}

export function storeReviewerRecord(record: ReviewerRecord): void {
  if (typeof window === "undefined") return;
  writePersistent(REVIEWER_STORAGE_KEY, JSON.stringify(record));
}

export function readReviewerRecord(): ReviewerRecord | null {
  if (typeof window === "undefined") return null;
  const raw = readPersistent(REVIEWER_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ReviewerRecord>;
    if (typeof parsed.platform !== "string" || !parsed.platform) return null;
    return { platform: parsed.platform, expiresAt: typeof parsed.expiresAt === "string" ? parsed.expiresAt : null };
  } catch {
    return null;
  }
}

export function clearReviewerRecord(): void {
  if (typeof window === "undefined") return;
  removePersistent(REVIEWER_STORAGE_KEY);
}
