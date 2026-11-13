// The content script's fill flow for a QUEUED JOB (P97 D85.6). Trigger: the address carries
// `#juli-fill=<job id>` on one of the allowed Seller Centre pages. Ask the service worker for the
// job (it checks the page, the shop and Juli's kill switch), look for Shopee's password prompt,
// fill the page, show the checklist, tell Juli how far it got. It never presses a save / confirm
// button; the person does.

import { FILL_HASH_KEY, FILL_JOB_ID_PATTERN } from "../config";
import { type Env } from "./controls";
import { fillAds, fillAffiliate, fillCombo, type FillOutcome, fillVoucher } from "./fillers";
import { type FillJob, type JobReply } from "./job-types";
import { HALT_TEXT, showJobPanel } from "./job-panel";
import { findControl } from "./locate";
import { highlight, readValue, targetValue, writeValue } from "./write";

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

export interface JobDeps {
  doc: Document;
  loc: { pathname: string; hash: string };
  ask(jobId: string): Promise<JobReply>;
  /** Progress to Juli through the service worker. */
  report(jobId: string, status: "opened" | "filled" | "failed", error?: string): Promise<void>;
  /** Shopee asked for the password again: the service worker stops everything for the shop. */
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
  | { status: "filled" | "partial"; steps: number };

const REFUSAL: Record<string, string> = {
  inactive: "",
  unpaired: "Connector chưa kết nối với Juli. Kết nối lại rồi mở trang từ Juli.",
  unknown_job: "Juli không còn thấy việc này (đã hủy hoặc đã xong).",
  wrong_page: "Việc này thuộc trang khác nên Juli không điền vào trang này.",
  budget: "Hôm nay Connector đã dùng hết lượt truy cập Seller Centre. Thử lại vào ngày mai.",
  error: "Juli chưa lấy được nội dung việc này. Thử lại sau.",
};

async function fillText(env: Env, job: FillJob): Promise<FillOutcome> {
  if (job.payload.kind !== "title" && job.payload.kind !== "description_first_line") return { steps: [], todo: [], notes: [] };
  const field = job.payload.fields[0]!;
  const until = env.now() + 25_000;
  let control: HTMLElement | null = null;
  for (;;) {
    control = findControl(env.doc, field.label);
    if (control || env.now() >= until) break;
    await env.sleep(400);
  }
  let ok = false;
  if (control) {
    const current = readValue(control).replace(/\r/g, "");
    const next = targetValue(current, field.value, field.mode);
    ok = current === next || writeValue(control, next);
    if (ok) highlight(control);
  }
  return {
    steps: [{ label: `${field.label}: ${field.value}`, ok, ...(ok ? {} : { note: "Không thấy ô nhập; dán nội dung bằng tay." }) }],
    todo: ["Kiểm tra rồi bấm Cập nhật / Lưu của Shopee."],
    notes: [],
  };
}

async function fillPage(env: Env, job: FillJob): Promise<FillOutcome> {
  const p = job.payload;
  if (p.kind === "voucher") return fillVoucher(env, p.voucher);
  if (p.kind === "ads_edit") return fillAds(env, p.ads);
  if (p.kind === "affiliate_commission") return fillAffiliate(env, p.affiliate);
  if (p.kind === "combo") return fillCombo(env, p.combo);
  return fillText(env, job);
}

export async function runFillJob(deps: JobDeps): Promise<JobResult> {
  const trigger = parseJobTrigger(deps.loc);
  if (!trigger) return { status: "idle" };
  if (deps.passwordPrompt()) {
    await deps.halt(trigger.jobId);
    showJobPanel(deps.doc, { outcome: "halted", text: HALT_TEXT });
    return { status: "halted" };
  }
  const reply = await deps.ask(trigger.jobId);
  if (!reply.ok) {
    if (reply.reason === "inactive") return { status: "idle" };
    showJobPanel(deps.doc, { outcome: "refused", text: REFUSAL[reply.reason] ?? REFUSAL.error! });
    return { status: "refused", reason: reply.reason };
  }
  const job = reply.value;
  await deps.report(job.id, "opened");
  const env: Env = { doc: deps.doc, sleep: deps.sleep, now: deps.now };
  const result = await fillPage(env, job);
  // The prompt may have appeared while the page was drawing: stop, do not go on.
  if (deps.passwordPrompt()) {
    await deps.halt(job.id);
    showJobPanel(deps.doc, { outcome: "halted", text: HALT_TEXT });
    return { status: "halted" };
  }
  const all = result.steps.length > 0 && result.steps.every((s) => s.ok);
  showJobPanel(deps.doc, { outcome: all ? "filled" : "partial", job, result });
  if (all) await deps.report(job.id, "filled");
  return { status: all ? "filled" : "partial", steps: result.steps.length };
}

