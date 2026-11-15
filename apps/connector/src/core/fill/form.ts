// The platform-free shape of a fill job and of one form's fill: what a platform pack's form map
// returns, what the job panel draws, and what the job runner hands the content script.

/** What a form fill gets: the page's document and a clock (injected so tests run with fakes). */
export interface Env {
  doc: Document;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export interface Step {
  /** What the person sees in the checklist (Vietnamese). */
  label: string;
  ok: boolean;
  /** Said when it is not ok, or when the person has something to do. */
  note?: string;
}

export interface FillOutcome {
  steps: Step[];
  /** What the person still does, in order (Vietnamese). */
  todo: string[];
  notes: string[];
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
  fill(env: Env, job: J): Promise<FillOutcome>;
}

/** The reply of the service worker to the content script's job request. */
export type JobReply<J extends CoreJob = CoreJob> =
  | { ok: true; value: J }
  | { ok: false; reason: "inactive" | "unpaired" | "unknown_job" | "wrong_page" | "budget" | "error" };
