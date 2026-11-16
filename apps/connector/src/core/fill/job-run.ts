// The content script's fill flow for a QUEUED JOB (P97 D85.6). Trigger: the address carries
// `#juli-fill=<job id>` on one of the platform pack's allowed pages. Ask the service worker for the
// job (it checks the page, the shop and Juli's kill switch), look for the platform's password
// prompt, fill the page with the pack's form for the job's action, show the checklist, tell Juli how
// far it got. It never presses a save / confirm button; the person does.

import { FILL_HASH_KEY, FILL_JOB_ID_PATTERN } from "../config";
import type { CoreJob, Env, FillOutcome, FormMap, JobReply } from "./form";
import { type JobLabels, showJobPanel } from "./job-panel";

/** How many of the page's steps are in (Thực hiện shows "3/4 đã điền"). */
export interface FillProgress {
  filled: number;
  total: number;
}

export interface JobTrigger {
  jobId: string;
}

export function parseJobTrigger(loc: { hash: string }): JobTrigger | null {
  const hash = loc.hash.replace(/^#/, "");
  const prefix = `${FILL_HASH_KEY}=`;
  if (!hash.startsWith(prefix)) return null;
  const id = hash.slice(prefix.length);
  return FILL_JOB_ID_PATTERN.test(id) ? { jobId: id } : null;
}

export interface JobDeps<J extends CoreJob = CoreJob> {
  doc: Document;
  loc: { pathname: string; hash: string };
  ask(jobId: string): Promise<JobReply<J>>;
  /** Progress to Juli through the service worker. */
  report(jobId: string, status: "opened" | "filled" | "failed", error?: string, progress?: FillProgress): Promise<void>;
  /** The platform asked for the password again: the service worker stops everything for the shop. */
  halt(jobId: string): Promise<void>;
  /** The password prompt text is on the page (never typed into). */
  passwordPrompt(): boolean;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export type JobResult =
  | { status: "idle" }
  | { status: "refused"; reason: string }
  | { status: "halted" }
  | { status: "blocked"; reason: string }
  | { status: "filled" | "partial"; steps: number };

const REFUSAL: Record<string, string> = {
  inactive: "",
  unpaired: "Connector chưa kết nối với Juli. Kết nối lại rồi mở trang từ Juli.",
  unknown_job: "Juli không còn thấy việc này (đã hủy hoặc đã xong).",
  wrong_page: "Việc này thuộc trang khác nên Juli không điền vào trang này.",
  budget: "Hôm nay Connector đã dùng hết lượt truy cập Seller Centre. Thử lại vào ngày mai.",
  error: "Juli chưa lấy được nội dung việc này. Thử lại sau.",
};

/** The pack's form for the job's action fills the page; an action the pack has no form for, nothing. */
async function fillPage<J extends CoreJob>(env: Env, job: J, forms: Readonly<Record<string, FormMap<J>>>): Promise<FillOutcome> {
  const form = Object.prototype.hasOwnProperty.call(forms, job.kind) ? forms[job.kind] : undefined;
  return form ? form.fill(env, job) : { steps: [], todo: [], notes: [] };
}

/** What the platform pack brings to a job run: its form per action and its panel texts. */
export interface JobPack<J extends CoreJob = CoreJob> {
  forms: Readonly<Record<string, FormMap<J>>>;
  labels: JobLabels;
  /** A wall on the page (CAPTCHA ...) as the job's error code, or null: the job stops, nothing is typed. */
  blockedOn?(doc: Document): string | null;
}

export async function runFillJob<J extends CoreJob>(deps: JobDeps<J>, pack: JobPack<J>): Promise<JobResult> {
  const trigger = parseJobTrigger(deps.loc);
  if (!trigger) return { status: "idle" };
  if (deps.passwordPrompt()) {
    await deps.halt(trigger.jobId);
    showJobPanel(deps.doc, { outcome: "halted", text: pack.labels.halt }, pack.labels);
    return { status: "halted" };
  }
  const reply = await deps.ask(trigger.jobId);
  if (!reply.ok) {
    if (reply.reason === "inactive") return { status: "idle" };
    showJobPanel(deps.doc, { outcome: "refused", text: REFUSAL[reply.reason] ?? REFUSAL.error! }, pack.labels);
    return { status: "refused", reason: reply.reason };
  }
  const job = reply.value;
  const wall = async (): Promise<JobResult | null> => {
    const reason = pack.blockedOn?.(deps.doc) ?? null;
    if (!reason) return null;
    await deps.report(job.id, "failed", reason);
    showJobPanel(deps.doc, { outcome: "blocked", text: pack.labels.blocked ?? pack.labels.halt }, pack.labels);
    return { status: "blocked", reason };
  };
  const walledBefore = await wall();
  if (walledBefore) return walledBefore;
  await deps.report(job.id, "opened");
  const env: Env = { doc: deps.doc, sleep: deps.sleep, now: deps.now };
  const result = await fillPage(env, job, pack.forms);
  // The prompt may have appeared while the page was drawing: stop, do not go on.
  if (deps.passwordPrompt()) {
    await deps.halt(job.id);
    showJobPanel(deps.doc, { outcome: "halted", text: pack.labels.halt }, pack.labels);
    return { status: "halted" };
  }
  const walledAfter = await wall();
  if (walledAfter) return walledAfter;
  const all = result.steps.length > 0 && result.steps.every((s) => s.ok);
  showJobPanel(deps.doc, { outcome: all ? "filled" : "partial", job, result }, pack.labels);
  const progress: FillProgress = { filled: result.steps.filter((s) => s.ok).length, total: result.steps.length };
  if (all) await deps.report(job.id, "filled", undefined, progress);
  else if (progress.total > 0) await deps.report(job.id, "opened", undefined, progress);
  return { status: all ? "filled" : "partial", steps: result.steps.length };
}

