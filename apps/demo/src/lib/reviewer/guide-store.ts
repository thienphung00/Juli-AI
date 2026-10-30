/**
 * The partner reviewer guide's saved state (fast track P77): whether the
 * panel is open and which steps are done, kept per reviewer user id in
 * localStorage. Every access goes through `persistent-storage`, which
 * swallows a storage that throws, so the guide works without storage.
 */

import { readPersistent, writePersistent } from "../persistent-storage";
import { decodeJwtPayload, readAuthSession } from "../supabase-auth";
import { GUIDE_STEPS, type GuideStepId } from "./guide-copy";

export const GUIDE_STORAGE_PREFIX = "juli_reviewer_guide:";

export interface GuideState {
  readonly open: boolean;
  readonly done: readonly GuideStepId[];
}

/** First visit: nothing saved, the panel starts open. */
export const GUIDE_INITIAL: GuideState = { open: true, done: [] };

const KNOWN = new Set<string>(GUIDE_STEPS.map((step) => step.id));

/** The signed-in user's id (JWT `sub`, display-only decode), or "anonymous". */
export function guideUserId(): string {
  const session = readAuthSession();
  const sub = session ? decodeJwtPayload(session.accessToken)?.sub : null;
  return typeof sub === "string" && sub ? sub : "anonymous";
}

export function readGuideState(userId: string): GuideState {
  const raw = readPersistent(GUIDE_STORAGE_PREFIX + userId);
  if (!raw) return GUIDE_INITIAL;
  try {
    const parsed = JSON.parse(raw) as { open?: unknown; done?: unknown };
    const done = Array.isArray(parsed.done)
      ? (parsed.done.filter((id): id is GuideStepId => typeof id === "string" && KNOWN.has(id)) as GuideStepId[])
      : [];
    return { open: parsed.open !== false, done };
  } catch {
    return GUIDE_INITIAL;
  }
}

export function writeGuideState(userId: string, state: GuideState): void {
  writePersistent(GUIDE_STORAGE_PREFIX + userId, JSON.stringify(state));
}
