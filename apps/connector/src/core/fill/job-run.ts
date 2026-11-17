// The content script's fill flow for a QUEUED JOB (P97 D85.6). Trigger: the address carries
// `#juli-fill=<job id>` on one of the platform pack's allowed pages. Ask the service worker for the
// job (it checks the page, the shop and Juli's kill switch), look for the platform's password
// prompt, fill the page with the pack's form for the job's action, show the checklist, tell Juli how
// far it got. It never presses a save / confirm button; the person does.

import { FILL_HASH_KEY, FILL_JOB_ID_PATTERN, FILL_WATCH_MS, FILL_WATCH_POLL_MS } from "../config";
import type { CoreJob, Env, FillOutcome, FormMap, JobReply } from "./form";
import { type JobLabels, showJobPanel } from "./job-panel";
import { type FieldCheck, FillLog } from "./log";
import { applyChecks, periodOk, seenNote, verifyWrites, waitForForm } from "./verify";

/** How many of the page's steps are in (Thực hiện shows "3/4 đã điền"). */
export interface FillProgress {
  filled: number;
  total: number;
}

/**
 * 0.3.24: what the fill saw, for Juli (and the revert): each field's value BEFORE Juli wrote it,
 * whether the period of a time-bound form holds the card's dates, and each field's last read.
 */
export interface FillDetail {
  before_values: Record<string, string>;
  period_ok?: boolean;
  fields: FieldCheck[];
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
  report(jobId: string, status: "opened" | "filled" | "failed", error?: string, progress?: FillProgress, detail?: FillDetail): Promise<void>;
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

const NOT_LOADED = "Trang chưa hiện biểu mẫu sau 25 giây; Juli vẫn thử điền.";

/**
 * The pack's form for the job's action fills the page (an action the pack has no form for,
 * nothing): wait for the form and a quiet page, type, then read every field again.
 */
async function fillPage<J extends CoreJob>(env: Env, job: J, pack: JobPack<J>): Promise<{ result: FillOutcome; checks: FieldCheck[] }> {
  const form = Object.prototype.hasOwnProperty.call(pack.forms, job.kind) ? pack.forms[job.kind] : undefined;
  if (!form) return { result: { steps: [], todo: [], notes: [] }, checks: [] };
  const waited = await waitForForm(env, form.ready ? () => form.ready!(env.doc, job) : undefined, pack.dismiss);
  const filled = await form.fill(env, job);
  const checks = await verifyWrites(env, env.log!);
  const result = applyChecks(filled, checks);
  const notes = [...waited.notes, ...(waited.ready ? [] : [NOT_LOADED]), ...result.notes];
  return { result: { ...result, notes }, checks };
}

/**
 * After the panel is up: keeps reading the fields for FILL_WATCH_MS and turns a step ✗ when the
 * page changes a value back (never writes again: the person may be typing).
 */
async function watch(env: Env, log: FillLog, result: FillOutcome, redraw: (r: FillOutcome) => void): Promise<FillOutcome> {
  let current = result;
  for (let waited = 0; waited < FILL_WATCH_MS; waited += FILL_WATCH_POLL_MS) {
    await env.sleep(FILL_WATCH_POLL_MS);
    const bad = new Map<string, string>();
    for (const e of log.entries.values()) {
      let ok = false;
      try {
        ok = env.doc.contains(e.el) && e.ok();
      } catch {
        ok = false;
      }
      if (!ok) bad.set(e.key, env.doc.contains(e.el) ? e.seen() : "");
    }
    if (bad.size === 0) continue;
    let changed = false;
    const steps = current.steps.map((s) => {
      const key = s.ok ? s.keys?.find((k) => bad.has(k)) : undefined;
      if (key === undefined) return s;
      changed = true;
      return { ...s, ok: false, note: seenNote(bad.get(key) ?? "") };
    });
    if (changed) {
      current = { ...current, steps };
      redraw(current);
    }
  }
  return current;
}

/** What the platform pack brings to a job run: its form per action and its panel texts. */
export interface JobPack<J extends CoreJob = CoreJob> {
  forms: Readonly<Record<string, FormMap<J>>>;
  labels: JobLabels;
  /** A wall on the page (CAPTCHA ...) as the job's error code, or null: the job stops, nothing is typed. */
  blockedOn?(doc: Document): string | null;
  /** Closes a known notice of the platform that covers the page (never a save); notes for the panel. */
  dismiss?(env: Env): Promise<string[]>;
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
  const log = new FillLog();
  const env: Env = { doc: deps.doc, sleep: deps.sleep, now: deps.now, log };
  const filled = await fillPage(env, job, pack);
  let result = filled.result;
  // The prompt may have appeared while the page was drawing: stop, do not go on.
  if (deps.passwordPrompt()) {
    await deps.halt(job.id);
    showJobPanel(deps.doc, { outcome: "halted", text: pack.labels.halt }, pack.labels);
    return { status: "halted" };
  }
  const walledAfter = await wall();
  if (walledAfter) return walledAfter;
  const counted = (r: FillOutcome) => r.steps.filter((s) => !s.skipped);
  const allOk = (r: FillOutcome) => counted(r).length > 0 && counted(r).every((s) => s.ok);
  const draw = (r: FillOutcome) =>
    showJobPanel(deps.doc, { outcome: allOk(r) ? "filled" : "partial", job, result: r, ...(periodOk(r) === false ? { periodOk: false } : {}) }, pack.labels);
  draw(result);
  if (log.entries.size > 0) result = await watch(env, log, result, draw);
  const all = allOk(result);
  const progress: FillProgress = { filled: counted(result).filter((s) => s.ok).length, total: counted(result).length };
  const period = periodOk(result);
  const lastRead = new Map(filled.checks.map((c) => [c.key, c]));
  const fields = [...log.entries.values()].map((e) => {
    const okNow = deps.doc.contains(e.el) && safe(() => e.ok(), false);
    return { key: e.key, ok: okNow, seen: (deps.doc.contains(e.el) ? safe(() => e.seen(), "") : lastRead.get(e.key)?.seen ?? "").slice(0, 120) };
  });
  const detail: FillDetail = { before_values: { ...log.before }, fields, ...(period !== undefined ? { period_ok: period } : {}) };
  if (all) await deps.report(job.id, "filled", undefined, progress, detail);
  else if (progress.total > 0) await deps.report(job.id, "opened", undefined, progress, detail);
  return { status: all ? "filled" : "partial", steps: counted(result).length };
}


function safe<T>(read: () => T, fallback: T): T {
  try {
    return read();
  } catch {
    return fallback;
  }
}
