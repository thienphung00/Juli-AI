// The platform-free shape of a fill job and of one form's fill: what a platform pack's form map
// returns, what the job panel draws, and what the job runner hands the content script.

import type { FillLog } from "./log";

/** What a form fill gets: the page's document and a clock (injected so tests run with fakes). */
export interface Env {
  doc: Document;
  sleep(ms: number): Promise<void>;
  now(): number;
  /** 0.3.24: every write is recorded here (value before, what was written) for the re-read. */
  log?: FillLog;
  /** The field key the next control write belongs to (see `keyed`). */
  field?: string;
}

export interface Step {
  /** What the person sees in the checklist (Vietnamese). */
  label: string;
  ok: boolean;
  /** Said when it is not ok, or when the person has something to do. */
  note?: string;
  /** The field key(s) whose writes this step stands for: the re-read turns the step ✗ if any differs. */
  keys?: string[];
  /** A step that does not apply on this page (e.g. a control the platform no longer draws): not counted. */
  skipped?: boolean;
}

export interface FillOutcome {
  steps: Step[];
  /** What the person still does, in order (Vietnamese). */
  todo: string[];
  notes: string[];
  /** The keys of the period (start / end) fields of a time-bound form: unfilled ⇒ "do not save". */
  periodKeys?: string[];
  /**
   * 0.3.27 (contract D): what the page shows the platform holds now (before Juli typed), as catalog rows
   * the Connector posts (item_id + description_first_line / item_name / commission_pct).
   */
  current?: CurrentRow[];
  /** 0.3.27 (contract C): a read-back reports `captured` once it read the page; nothing is typed. */
  report?: "captured";
}

/** One item's current values as a page shows them (contract D). */
export interface CurrentRow {
  item_id: string;
  item_name?: string;
  description_first_line?: string;
  commission_pct?: number;
}

/** The fields of a fill job every platform has (a pack's job type extends it). */
export interface CoreJob {
  id: string;
  code: string;
  title: string;
  groupCode: string | null;
  /** The action: the key of the pack's form map. */
  kind: string;
  status: string;
  /** Path (and query) to open, relative to the pack's seller centre origin. */
  openPath: string;
}

/** One action's form on one platform: the page it lives on and how to fill it. */
export interface FormMap<J extends CoreJob = CoreJob> {
  /** The page path (no origin) the action's form lives on. */
  page: RegExp;
  /** True once the page has drawn this form (the runner waits for it, then for a quiet page). */
  ready?(doc: Document, job: J): boolean;
  fill(env: Env, job: J): Promise<FillOutcome>;
}

/** The reply of the service worker to the content script's job request. */
export type JobReply<J extends CoreJob = CoreJob> =
  | { ok: true; value: J }
  | { ok: false; reason: "inactive" | "unpaired" | "unknown_job" | "wrong_page" | "budget" | "error" };
