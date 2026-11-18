// What the Connector core keeps in chrome.storage.local, whatever the platform: the storage
// shape, the shared daily request budget and the fill-job runner's bookkeeping. A platform's own
// bookkeeping (its readers, backfill, ...) is the platform pack's (platforms/<id>/background/state).

import { DAILY_REQUEST_BUDGET, TODAY_REQUEST_RESERVE } from "./config";
import type { TokenInfo } from "./ingest/client";

export interface Storage {
  get(keys?: string | string[] | null): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

/** The fill-job runner's bookkeeping. At most one page is open for a job at a time. */
export interface FillJobsState {
  active?: { id: string; tabId?: number; openedAt: number; counted: boolean; closeWhenDone?: boolean };
  /** Jobs this browser already opened by itself (never again by the poll; the person re-opens). */
  autoOpened: string[];
  lastPoll?: { at: string; status: string };
  /** The last Juli command this browser ran ("Đối chiếu ngay"), and the one still to acknowledge. */
  lastCommand?: string;
  doneCommand?: string;
  /** 0.3.27: the platform's anti-bot page showed on a job tab: no job page opens before this (ms). */
  pausedUntil?: number;
  /** 0.3.27 (contract C): read-backs handed to the readers, by job id, and when (ms). */
  readbacks?: Record<string, number>;
}

/** The shared daily request budget's counter. */
export interface RequestBudget {
  day: string;
  used: number;
}

/** Requests left today (the budget resets with the GMT+7 day). */
export function requestsLeft(state: Pick<CoreState, "budget">, day: string): number {
  const used = state.budget?.day === day ? state.budget.used : 0;
  return Math.max(0, DAILY_REQUEST_BUDGET - used);
}

/** What the 30-day backfill may still spend today: the budget minus the share reserved for today's readers. */
export function backfillRequestsLeft(state: Pick<CoreState, "budget">, day: string): number {
  return Math.max(0, requestsLeft(state, day) - TODAY_REQUEST_RESERVE);
}

/** Count `count` more requests today. Read-modify-write: sync, backfill and the scheduler never overlap. */
export async function addRequests(storage: Storage, day: string, count: number): Promise<void> {
  if (count <= 0) return;
  const raw = (await storage.get(["budget"])) as Partial<CoreState>;
  const used = raw.budget?.day === day ? raw.budget.used : 0;
  await saveState(storage, { budget: { day, used: used + count } });
}

export async function saveState(storage: Storage, patch: Record<string, unknown>): Promise<void> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(patch)) clean[key] = value ?? null;
  await storage.set(clean);
}

/** The keys the core reads (a platform's own state carries more). */
export interface CoreState {
  token?: TokenInfo;
  /** Juli answered 403 consent_required: nothing is sent until the seller retries or pairs again. */
  consentBlocked?: { at: string };
  /** A CAPTCHA / login wall / rate-limit stop of the shop's readers: nothing opens before `until`. */
  readers?: { blocked?: { until: number } };
  budget?: RequestBudget;
  fill?: FillJobsState;
}

export async function loadCoreState(storage: Storage): Promise<CoreState> {
  const raw = (await storage.get(["token", "consentBlocked", "readers", "budget", "fill"])) as Partial<CoreState>;
  return { token: raw.token, consentBlocked: raw.consentBlocked, readers: raw.readers, budget: raw.budget, fill: raw.fill };
}
