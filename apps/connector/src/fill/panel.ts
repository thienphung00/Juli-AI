// The small panel the Connector shows on the edit page: what it filled (or why it did not), the
// text with copy buttons, the cover image as a download link, a step list for the changes it
// does not type. The page's own buttons are never touched: this panel has only its own "Sao
// chép" and "Đóng" buttons, which act when the PERSON clicks them.

import { PANEL_ID } from "./locate";
import type { FillKey, FillRefusal, FillRequest, FillStep } from "./types";

export type PanelOutcome = "filled" | "not_found" | "page_only" | "refused";

export interface PanelInput {
  outcome: PanelOutcome;
  request?: FillRequest;
  filled?: readonly FillKey[];
  refusal?: FillRefusal;
}

export const BANNER_FILLED = "Juli đã điền — kiểm tra rồi bấm Lưu của Shopee";
export const BANNER_NOT_FOUND =
  "Juli chưa tìm thấy ô nhập trên trang này nên không điền gì. Dán nội dung bằng nút Sao chép.";
export const BANNER_PAGE_ONLY =
  "Trang đã mở. Làm theo các bước bên dưới rồi bấm nút của Shopee — Juli không bấm thay bạn.";
export const NEVER_NOTE = "Juli không bấm Lưu, Cập nhật, Xác nhận hay Ẩn thay bạn.";

export const REFUSAL_TEXT: Record<FillRefusal, string> = {
  inactive: "",
  unpaired: "Connector chưa kết nối với Juli. Kết nối lại rồi mở trang từ Juli.",
  disabled: "Juli chưa bật tính năng điền cho shop này.",
  not_found: "Juli không tìm thấy thẻ này.",
  not_approved: "Thẻ chưa được đồng ý hoặc đã làm xong nên Juli không điền.",
  unsupported: "Loại thay đổi này Juli không điền; hãy làm theo thẻ trên Juli.",
  wrong_item: "Thẻ này thuộc sản phẩm khác nên Juli không điền vào trang này.",
  error: "Juli chưa lấy được nội dung thẻ. Thử lại sau.",
};

export const STYLE = `
:host{all:initial}
.box{position:fixed;top:72px;right:16px;z-index:2147483000;width:340px;max-height:80vh;overflow:auto;
 font:13px/1.45 system-ui,sans-serif;color:#1f1f24;background:#fff;border:1px solid #e5e0e4;
 border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.18);padding:12px}
.head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:6px}
.code{font-weight:700;color:#be185d}
.title{color:#6b6b76;font-size:12px}
.banner{padding:8px 10px;border-radius:8px;margin:6px 0;background:#fdeef4;color:#831843;font-weight:600}
.banner.ok{background:#e8f7ee;color:#14532d}
.note{color:#6b6b76;font-size:12px;margin:4px 0 8px}
.field{border:1px solid #eee;border-radius:8px;padding:8px;margin:6px 0}
.label{font-weight:600}
.value{white-space:pre-wrap;word-break:break-word;margin:4px 0}
button{font:inherit;border:1px solid #d6d0d4;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer}
a.dl{display:inline-block;margin:4px 0;color:#be185d}
ol{padding-left:18px;margin:6px 0}
li{margin:4px 0}
`;

type Doc = Document;

export function el<K extends keyof HTMLElementTagNameMap>(
  doc: Doc,
  tag: K,
  props: { cls?: string; text?: string } = {},
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (props.cls) node.className = props.cls;
  if (props.text !== undefined) node.textContent = props.text;
  return node;
}

export interface PanelDeps {
  /** Writes to the clipboard; called only from the person's own click on a "Sao chép" button. */
  copy(text: string): Promise<void>;
}

function copyButton(doc: Doc, text: string, deps: PanelDeps): HTMLButtonElement {
  const button = el(doc, "button", { text: "Sao chép" });
  button.type = "button";
  button.addEventListener("click", () => {
    void deps
      .copy(text)
      .then(() => (button.textContent = "Đã chép"))
      .catch(() => (button.textContent = "Không chép được"));
  });
  return button;
}

function stepList(doc: Doc, steps: readonly FillStep[], deps: PanelDeps, checkable: boolean): HTMLElement {
  const list = el(doc, "ol");
  for (const s of steps) {
    const item = el(doc, "li");
    if (checkable) {
      const box = doc.createElement("input");
      box.type = "checkbox";
      item.append(box, " ");
    }
    item.append(`${s.field}${s.after ? `: ${s.after}` : ""} `);
    if (s.copy) item.append(copyButton(doc, s.copy, deps));
    list.append(item);
  }
  return list;
}

/** Draws (or redraws) the panel and returns its host element. */
export function showPanel(doc: Doc, input: PanelInput, deps: PanelDeps): HTMLElement {
  doc.getElementById(PANEL_ID)?.remove();
  const host = el(doc, "div");
  host.id = PANEL_ID;
  const root = host.attachShadow({ mode: "open" });
  const style = el(doc, "style", { text: STYLE });
  const box = el(doc, "div", { cls: "box" });
  const req = input.request;

  const head = el(doc, "div", { cls: "head" });
  const who = el(doc, "div");
  who.append(el(doc, "div", { cls: "code", text: req ? `Juli · ${req.code}` : "Juli" }));
  if (req) who.append(el(doc, "div", { cls: "title", text: req.title }));
  const close = el(doc, "button", { text: "Đóng" });
  close.type = "button";
  close.addEventListener("click", () => host.remove());
  head.append(who, close);
  box.append(head);

  const banner = (text: string, ok = false) => box.append(el(doc, "div", { cls: ok ? "banner ok" : "banner", text }));
  if (input.outcome === "refused") {
    banner(REFUSAL_TEXT[input.refusal ?? "error"]);
  } else if (input.outcome === "filled") {
    banner(BANNER_FILLED, true);
  } else if (input.outcome === "not_found") {
    banner(BANNER_NOT_FOUND);
  } else {
    banner(BANNER_PAGE_ONLY);
  }
  box.append(el(doc, "div", { cls: "note", text: NEVER_NOTE }));

  if (req) {
    for (const dep of req.dependencies) {
      box.append(el(doc, "div", { cls: "note", text: `Chỉ làm sau khi ${dep} đã chạy xong.` }));
    }
    for (const f of req.fields) {
      const field = el(doc, "div", { cls: "field" });
      const done = input.filled?.includes(f.key);
      field.append(el(doc, "div", { cls: "label", text: `${f.label}${done ? " — đã điền" : ""}` }));
      field.append(el(doc, "div", { cls: "value", text: f.value }));
      field.append(copyButton(doc, f.value, deps));
      box.append(field);
    }
    for (const d of req.downloads) {
      const link = el(doc, "a", { cls: "dl", text: d.label });
      link.href = d.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("download", "");
      box.append(link);
    }
    if (req.checklist.length > 0) {
      box.append(el(doc, "div", { cls: "label", text: "Các bước (tự tick khi xong)" }));
      box.append(stepList(doc, req.checklist, deps, true));
    } else if (req.pageOnly || (req.fields.length === 0 && req.downloads.length === 0)) {
      box.append(stepList(doc, req.steps, deps, false));
    }
  }
  root.append(style, box);
  doc.documentElement.append(host);
  return host;
}
