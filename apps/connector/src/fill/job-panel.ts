// The panel of a fill job: what was filled (a checklist), what the person still does, and the
// reminder that Juli presses nothing. Own buttons: "Đóng" only.

import type { FillOutcome } from "./fillers";
import type { FillJob } from "./job-types";
import { PANEL_ID } from "./locate";
import { el, NEVER_NOTE, STYLE } from "./panel";

export type JobPanelInput =
  | { outcome: "filled" | "partial"; job: FillJob; result: FillOutcome }
  | { outcome: "refused"; text: string }
  | { outcome: "halted"; text: string };

const JOB_STYLE = `${STYLE}
.ok-mark{color:#14532d;font-weight:700}.no-mark{color:#b91c1c;font-weight:700}
.todo{margin:8px 0 0;padding-left:18px}`;

export const BANNER_JOB_FILLED = "Juli đã điền — kiểm tra rồi bấm nút của Shopee";
export const BANNER_JOB_PARTIAL = "Juli điền được một phần. Làm tiếp các mục còn thiếu bằng tay.";
export const HALT_TEXT =
  "Shopee đang hỏi lại mật khẩu. Juli dừng lại và không mở thêm trang nào; hãy tự xác nhận trong Shopee.";

export function showJobPanel(doc: Document, input: JobPanelInput): HTMLElement {
  doc.getElementById(PANEL_ID)?.remove();
  const host = el(doc, "div");
  host.id = PANEL_ID;
  const root = host.attachShadow({ mode: "open" });
  const box = el(doc, "div", { cls: "box" });
  const head = el(doc, "div", { cls: "head" });
  const who = el(doc, "div");
  const job = input.outcome === "filled" || input.outcome === "partial" ? input.job : undefined;
  who.append(el(doc, "div", { cls: "code", text: job ? `Juli · ${job.code}${job.groupCode ? ` · Nhóm ${job.groupCode}` : ""}` : "Juli" }));
  if (job) who.append(el(doc, "div", { cls: "title", text: job.title }));
  const close = el(doc, "button", { text: "Đóng" });
  close.type = "button";
  close.addEventListener("click", () => host.remove());
  head.append(who, close);
  box.append(head);
  if (input.outcome === "refused" || input.outcome === "halted") {
    box.append(el(doc, "div", { cls: "banner", text: input.text }));
  } else {
    box.append(
      el(doc, "div", {
        cls: input.outcome === "filled" ? "banner ok" : "banner",
        text: input.outcome === "filled" ? BANNER_JOB_FILLED : BANNER_JOB_PARTIAL,
      }),
    );
    const list = el(doc, "ul");
    for (const s of input.result.steps) {
      const li = el(doc, "li");
      li.append(el(doc, "span", { cls: s.ok ? "ok-mark" : "no-mark", text: s.ok ? "✓ " : "✗ " }), s.label);
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
    for (const n of input.result.notes) box.append(el(doc, "div", { cls: "note", text: n }));
  }
  box.append(el(doc, "div", { cls: "note", text: NEVER_NOTE }));
  root.append(el(doc, "style", { text: JOB_STYLE }), box);
  doc.documentElement.append(host);
  return host;
}
