// The content script's fill flow for a QUEUED JOB (P97 D85.6). Trigger: the address carries
// `#juli-fill=<job id>` on one of the platform pack's allowed pages. Ask the service worker for the
// job (it checks the page, the shop and Juli's kill switch), look for the platform's password
// prompt, fill the page with the pack's form for the job's action, show the checklist, tell Juli how
// far it got. It never presses a save / confirm button; the person does.

import { FILL_FOLLOW_MS, FILL_HASH_KEY, FILL_JOB_ID_PATTERN, FILL_WATCH_MS, FILL_WATCH_POLL_MS } from "../config";
import type { CoreJob, CurrentRow, Env, FillOutcome, FormMap, JobReply } from "./form";
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
  /** Progress to Juli through the service worker (`ref`: the id of what the person's save created). */
  report(
    jobId: string,
    status: "opened" | "filled" | "saved" | "captured" | "failed",
    error?: string,
    progress?: FillProgress,
    detail?: FillDetail,
    ref?: string,
  ): Promise<void>;
  /** 0.3.27 (contract D): posts what the page shows the platform holds now (absent: nothing is posted). */
  postCurrent?(rows: CurrentRow[]): Promise<void>;
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
  // each notice once, however many turns it was seen on (E21)
  const notes = [...new Set([...waited.notes, ...(waited.ready ? [] : [NOT_LOADED]), ...result.notes])];
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

/** 0.3.27 (E10, E44, F2.3, F3.1): how a pack sees the person's save of a job's page. */
export interface SaveWatch<J extends CoreJob = CoreJob> {
  /** The save landed (a redirect to the list, the platform's "thành công" toast, the ended row). */
  detect(doc: Document, loc: { pathname: string; hash: string }, job: J): boolean;
  /** The id of what the save created, read from the page it landed on, or null (not drawn yet). */
  capture?(doc: Document, job: J): string | null;
}

/** What the platform pack brings to a job run: its form per action and its panel texts. */
export interface JobPack<J extends CoreJob = CoreJob> {
  forms: Readonly<Record<string, FormMap<J>>>;
  labels: JobLabels;
  /** A wall on the page (CAPTCHA ...) as the job's error code, or null: the job stops, nothing is typed. */
  blockedOn?(doc: Document): string | null;
  /** Closes a known notice of the platform that covers the page (never a save); notes for the panel. */
  dismiss?(env: Env): Promise<string[]>;
  /** 0.3.27: the person's save, watched after the panel is up. */
  saved?: SaveWatch<J>;
}

/** The steps re-read from the log: ✓ when every write of the step reads the card's value, ✗ with what the page shows. */
export function recheck(env: Env, log: FillLog, result: FillOutcome): FillOutcome {
  const reads = new Map<string, { ok: boolean; seen: string }>();
  for (const e of log.entries.values()) {
    const there = env.doc.contains(e.el);
    const seen = there ? safe(() => e.seen(), "") : "";
    reads.set(e.key, { ok: there && safe(() => e.ok(), false) && seen.trim() !== "", seen });
  }
  const steps = result.steps.map((s) => {
    const keyed = (s.keys ?? []).filter((k) => reads.has(k));
    if (s.skipped || keyed.length === 0 || keyed.length !== (s.keys ?? []).length) return s;
    const bad = keyed.find((k) => !reads.get(k)!.ok);
    if (bad === undefined) return s.ok ? s : { ...s, ok: true, note: undefined };
    return s.ok || s.note !== seenNote(reads.get(bad)!.seen) ? { ...s, ok: false, note: seenNote(reads.get(bad)!.seen) } : s;
  });
  return { ...result, steps };
}

const signature = (r: FillOutcome) => r.steps.map((s) => `${s.ok ? 1 : 0}${s.note ?? ""}`).join("|");

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
  if (result.current && result.current.length > 0 && deps.postCurrent) await deps.postCurrent(result.current).catch(() => undefined);
  draw(result);
  if (result.report === "captured") {
    await deps.report(job.id, "captured");
    return { status: "filled", steps: counted(result).length };
  }
  if (log.entries.size > 0) result = await watch(env, log, result, draw);
  const lastRead = new Map(filled.checks.map((c) => [c.key, c]));
  const progressOf = (r: FillOutcome): FillProgress => ({ filled: counted(r).filter((s) => s.ok).length, total: counted(r).length });
  const detailOf = (r: FillOutcome): FillDetail => {
    const period = periodOk(r);
    const fields = [...log.entries.values()].map((e) => {
      const okNow = deps.doc.contains(e.el) && safe(() => e.ok(), false);
      const seen = (deps.doc.contains(e.el) ? safe(() => e.seen(), "") : lastRead.get(e.key)?.seen ?? "").slice(0, 120);
      // 0.3.27 (E45): an empty read is never ok
      return { key: e.key, ok: okNow && seen.trim() !== "", seen };
    });
    return { before_values: { ...log.before }, fields, ...(period !== undefined ? { period_ok: period } : {}) };
  };
  const tell = async (r: FillOutcome) => {
    if (allOk(r)) await deps.report(job.id, "filled", undefined, progressOf(r), detailOf(r));
    else if (progressOf(r).total > 0) await deps.report(job.id, "opened", undefined, progressOf(r), detailOf(r));
  };
  await tell(result);
  const all = allOk(result);
  const steps = counted(result).length;
  if (pack.saved || log.entries.size > 0) await follow(deps, env, log, job, pack, result, draw, tell, progressOf, detailOf);
  return { status: all ? "filled" : "partial", steps };
}

/**
 * 0.3.27 (F2.6): after the report, follow the page. A changed read is drawn and told to Juli once
 * it reads the same on two turns in a row (the person may be typing); the save, once seen, turns
 * the panel to "Đã lưu — bấm Đã làm trong Juli", is told as `saved`, and the created id (when the
 * pack can read it from the page the save landed on) as `captured`. Never writes, never presses.
 */
async function follow<J extends CoreJob>(
  deps: JobDeps<J>,
  env: Env,
  log: FillLog,
  job: J,
  pack: JobPack<J>,
  start: FillOutcome,
  draw: (r: FillOutcome) => void,
  tell: (r: FillOutcome) => Promise<void>,
  progressOf: (r: FillOutcome) => FillProgress,
  detailOf: (r: FillOutcome) => FillDetail,
): Promise<void> {
  let shown = start;
  let pending: string | null = null;
  const turns = Math.ceil(FILL_FOLLOW_MS / FILL_WATCH_POLL_MS);
  for (let turn = 0; turn < turns; turn += 1) {
    await deps.sleep(FILL_WATCH_POLL_MS);
    if (pack.saved && safe(() => pack.saved!.detect(deps.doc, deps.loc, job), false)) {
      await deps.report(job.id, "saved", undefined, progressOf(shown), detailOf(shown));
      showJobPanel(deps.doc, { outcome: "saved", job, result: shown }, pack.labels);
      const capture = pack.saved.capture;
      if (!capture) return;
      for (let wait = 0; wait < 30; wait += 1) {
        const ref = safe(() => capture(deps.doc, job), null);
        if (ref) {
          await deps.report(job.id, "captured", undefined, undefined, undefined, ref);
          return;
        }
        await deps.sleep(1_000);
      }
      return;
    }
    if (log.entries.size === 0) continue;
    const next = recheck(env, log, shown);
    const sig = signature(next);
    if (sig === signature(shown)) {
      pending = null;
      continue;
    }
    if (pending !== sig) {
      pending = sig;
      continue;
    }
    pending = null;
    shown = next;
    draw(shown);
    await tell(shown);
  }
}

function safe<T>(read: () => T, fallback: T): T {
  try {
    return read();
  } catch {
    return fallback;
  }
}
