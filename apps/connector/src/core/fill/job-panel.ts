// The panel of a fill job: what was filled (a checklist), what the person still does, and the
// reminder that Juli presses nothing. Own buttons: "Đóng" only. 0.3.28: the clicks are the person's,
// listed as numbered steps (the controls are highlighted on the page).

import type { CoreJob, FillOutcome } from "./form";
import { PANEL_ID } from "./locate";
import { el, NEVER_NOTE, STYLE } from "./panel";

export type JobPanelInput =
  | { outcome: "filled" | "partial"; job: CoreJob; result: FillOutcome; periodOk?: boolean }
  | { outcome: "saved"; job: CoreJob; result: FillOutcome; cardDone?: boolean | null }
  | { outcome: "refused"; text: string }
  | { outcome: "halted"; text: string }
  | { outcome: "blocked"; text: string };

const JOB_STYLE = `${STYLE}
.ok-mark{color:#14532d;font-weight:700}.no-mark{color:#b91c1c;font-weight:700}
.todo{margin:8px 0 0;padding-left:18px}
.banner.stop{background:#b91c1c;color:#fff;font-size:14px}`;

/** The job-panel texts that name the platform. */
export interface JobLabels {
  filled: string;
  /** The platform asked for the password again: everything stops. */
  halt: string;
  /** A verification (CAPTCHA) is in the way: the job stops and the person does it by hand. */
  blocked?: string;
}

/** `name` is the platform as the seller says it (a pack's `labels.name`). */
export function jobLabels(name: string): JobLabels {
  return {
    filled: `Juli đã điền đủ — kiểm tra rồi bấm nút của ${name}`,
    halt: `${name} đang hỏi lại mật khẩu. Juli dừng lại và không mở thêm trang nào; hãy tự xác nhận trong ${name}.`,
    blocked: `${name} đang yêu cầu xác minh (CAPTCHA). Juli dừng việc này và không điền gì; hãy tự xác minh rồi mở lại từ Juli.`,
  };
}

/** 0.3.24: the header says how many of the page's items Juli filled (each one read back). */
export const bannerPartial = (filled: number, total: number): string =>
  `Juli điền được ${filled}/${total} mục. Làm tiếp các mục còn thiếu bằng tay.`;
export const BANNER_JOB_NONE = "Juli chưa điền được mục nào. Làm các mục bằng tay theo thẻ trên Juli.";
/** A time-bound form whose period was not filled: the platform's default period is "now". */
export const BANNER_NO_PERIOD = "Chưa điền thời gian — đừng bấm Xác nhận";
/** 0.3.27 (E10): the person's save landed. */
export const BANNER_SAVED = "Đã lưu — bấm Đã làm trong Juli";
/** E149: Juli recorded "Đã làm" itself, so the person has nothing to press. */
export const BANNER_SAVED_DONE = "Đã lưu — Juli đã ghi nhận «Đã làm»";
/** E149: the save was seen, Juli has not answered yet (it is not yet known whether "Đã làm" is still the person's). */
export const BANNER_SAVED_WAIT = "Đã lưu — Juli đang ghi nhận";

/** The header of a filled / partial job: truthful about how many items were filled. */
export function jobHeader(result: FillOutcome, labels: JobLabels): { text: string; ok: boolean } {
  const steps = result.steps.filter((s) => !s.skipped);
  const filled = steps.filter((s) => s.ok).length;
  if (steps.length > 0 && filled === steps.length) return { text: labels.filled, ok: true };
  if (filled === 0) return { text: BANNER_JOB_NONE, ok: false };
  return { text: bannerPartial(filled, steps.length), ok: false };
}

export function showJobPanel(doc: Document, input: JobPanelInput, labels: JobLabels): HTMLElement {
  doc.getElementById(PANEL_ID)?.remove();
  const host = el(doc, "div");
  host.id = PANEL_ID;
  const root = host.attachShadow({ mode: "open" });
  const box = el(doc, "div", { cls: "box" });
  const head = el(doc, "div", { cls: "head" });
  const who = el(doc, "div");
  const job = input.outcome === "filled" || input.outcome === "partial" || input.outcome === "saved" ? input.job : undefined;
  who.append(el(doc, "div", { cls: "code", text: job ? `Juli · ${job.code}${job.groupCode ? ` · Nhóm ${job.groupCode}` : ""}` : "Juli" }));
  if (job) who.append(el(doc, "div", { cls: "title", text: job.title }));
  const close = el(doc, "button", { text: "Đóng" });
  close.type = "button";
  close.addEventListener("click", () => host.remove());
  head.append(who, close);
  box.append(head);
  if (input.outcome === "refused" || input.outcome === "halted" || input.outcome === "blocked") {
    box.append(el(doc, "div", { cls: "banner", text: input.text }));
  } else if (input.outcome === "saved") {
    box.append(el(doc, "div", { cls: "banner ok", text: input.cardDone === undefined ? BANNER_SAVED_WAIT : input.cardDone === true ? BANNER_SAVED_DONE : BANNER_SAVED }));
  } else {
    if (input.periodOk === false) box.append(el(doc, "div", { cls: "banner stop", text: BANNER_NO_PERIOD }));
    const header = jobHeader(input.result, labels);
    box.append(el(doc, "div", { cls: header.ok ? "banner ok" : "banner", text: header.text }));
    const list = el(doc, "ul");
    // 0.3.28 (F5.2): the person's steps are numbered in the order to do them
    let n = 0;
    for (const s of input.result.steps) {
      if (s.skipped) continue;
      const li = el(doc, "li");
      const num = s.guide ? `${(n += 1)}. ` : "";
      li.append(el(doc, "span", { cls: s.ok ? "ok-mark" : "no-mark", text: s.ok ? "✓ " : "✗ " }), `${num}${s.label}`);
      if (s.note) li.append(` — ${s.note}`);
      list.append(li);
    }
    box.append(list);
    if (input.result.todo.length > 0) {
      box.append(el(doc, "div", { cls: "label", text: "Bạn làm tiếp" }));
      const ol = el(doc, "ol", { cls: "todo" });
      for (const t of input.result.todo) ol.append(el(doc, "li", { text: t }));
      box.append(ol);
    }
    // each notice once (E21)
    for (const n of [...new Set(input.result.notes)]) box.append(el(doc, "div", { cls: "note", text: n }));
  }
  box.append(el(doc, "div", { cls: "note", text: NEVER_NOTE }));
  root.append(el(doc, "style", { text: JOB_STYLE }), box);
  doc.documentElement.append(host);
  return host;
}
